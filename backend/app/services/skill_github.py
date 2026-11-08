"""从 GitHub 地址导入技能（2026-11-08）。

为什么需要：SKILL.md 生态基本都托管在 GitHub（anthropics/skills、各种 skill marketplace），
只能粘贴文本意味着每次导入都要手点 raw 链接、还要自己把脚本资源一个个上传 —— 那不是一个
能用一万次的功能。这里做「贴一个地址，把 SKILL.md 与它的资源一起拉下来」。

**安全是这里的第一约束**：这是平台里唯一允许服务端主动访问「用户给的任意地址」的入口。
所以：

- 只认 GitHub（github.com / raw.githubusercontent.com / codeload），其余域名直接拒。
  不是"顺手也支持任意 URL" —— 那等于把任意 URL 抓取能力暴露给 admin/developer，
  一个 SSRF 就能读云厂商元数据（169.254.169.254）或内网服务。
- 解析出来的 IP 仍要过内网段检查（DNS 重绑定攻击：域名解析结果可以变）。
- 不跟随重定向到非 GitHub 域名（httpx 的 follow_redirects 会跟到任意地方）。
- 体积与文件数都有上限（一个恶意仓库不能拿来撑爆内存/磁盘）。
- 超时、连接错误都翻译成使用者看得懂的话，不吐 traceback。
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ---- 限制。数值的取舍：够用即可，重点是"恶意/异常输入不会撑爆进程" ----
MAX_FILES = 40                      # 一个技能目录最多带多少个资源
MAX_FILE_BYTES = 512 * 1024         # 单文件上限，与 skill_resource.RESOURCE_MAX_BYTES 一致
MAX_TOTAL_BYTES = 8 * 1024 * 1024   # 整次导入的下载总量
MAX_SKILL_MD_BYTES = 1024 * 1024    # SKILL.md 本身（正文另有 64KB 上限，解析后再校验）
TIMEOUT_SECONDS = 20.0

ALLOWED_HOSTS = {"github.com", "www.github.com", "raw.githubusercontent.com", "codeload.github.com"}

# 只拉这些后缀当资源：文本类 + 代码类。二进制（png/zip）不拉 ——
# 本平台的资源是给 load_skill 读、run_skill_script 跑的，拉一堆图片没有意义还占空间。
TEXT_SUFFIXES = (
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".sh", ".js", ".ts", ".sql", ".csv",
)

# 这些文件名是元信息，不作为资源（它们已经进了技能字段）
META_FILES = {"skill.md", "license", "license.txt", "license.md", ".gitignore", "readme.md"}

_PRIVATE_NETS = [
    ipaddress.ip_network(n)
    for n in ("0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
              "192.168.0.0/16", "100.64.0.0/10", "::1/128", "fc00::/7", "fe80::/10")
]


class SkillFetchError(ValueError):
    """抓取失败。message 直接回给使用者，要能看懂哪里不对、怎么办。"""


@dataclass
class RepoRef:
    """一个 GitHub 仓库里的位置：owner/repo、ref（分支/tag/commit）、path（目录或文件）。"""
    owner: str
    repo: str
    ref: str | None
    path: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


# --------------------------------------------------------------------------- 地址解析

_BLOB_RE = re.compile(r"^/([^/]+)/([^/]+)/(?:blob|tree)/([^/]+)/(.*)$")
_RAW_RE = re.compile(r"^/([^/]+)/([^/]+)/([^/]+)/(.*)$")


def parse_url(url: str) -> RepoRef:
    """把使用者贴的地址解析成 (owner, repo, ref, path)。

    支持的形态（都是使用者从浏览器地址栏直接复制会得到的样子）：
    - https://github.com/owner/repo                     → 仓库根
    - https://github.com/owner/repo/tree/main/skills/x  → 目录
    - https://github.com/owner/repo/blob/main/skills/x/SKILL.md → 单个文件
    - https://raw.githubusercontent.com/owner/repo/main/skills/x/SKILL.md → 单个文件
    - git@github.com:owner/repo.git 之类的写法不接受（那是克隆地址，不是浏览地址），
      但给出明确提示告诉使用者该贴什么，而不是"无法解析"了事。
    """
    raw = (url or "").strip()
    if not raw:
        raise SkillFetchError("请填写 GitHub 地址，例如 https://github.com/anthropics/skills/tree/main/skills/pdf")

    # 容忍不带协议的写法：github.com/owner/repo
    if "://" not in raw and not raw.startswith("git@"):
        raw = "https://" + raw

    if raw.startswith("git@"):
        raise SkillFetchError(
            "这是 git 克隆地址，不是浏览地址。请打开仓库页面，把浏览器地址栏里的 "
            "https://github.com/owner/repo/tree/分支/路径 这样的地址贴过来")

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise SkillFetchError(
            f"只支持从 GitHub 导入，这个地址的主机是 {host or '(空)'}。"
            "支持 github.com 与 raw.githubusercontent.com —— 不开放任意地址抓取，"
            "那样服务端会被拿去做内网探测")

    path = parsed.path or "/"

    if host == "raw.githubusercontent.com":
        m = _RAW_RE.match(path)
        if not m:
            raise SkillFetchError("raw 地址格式不对，应形如 raw.githubusercontent.com/owner/repo/分支/路径/SKILL.md")
        owner, repo, ref, rest = m.groups()
        return RepoRef(owner, repo, ref, rest)

    m = _BLOB_RE.match(path)
    if m:
        owner, repo, ref, rest = m.groups()
        return RepoRef(owner, repo, ref, rest)

    # 只剩 /owner/repo 或 /owner/repo/
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise SkillFetchError("地址里缺少仓库名，应形如 https://github.com/owner/repo")
    if len(parts) > 2:
        raise SkillFetchError(
            "看不懂这个 GitHub 地址。目录请用 /tree/分支/路径，单个文件用 /blob/分支/路径")
    return RepoRef(parts[0], parts[1], None, "")


# --------------------------------------------------------------------------- 出站安全

def _assert_public_host(host: str) -> None:
    """域名解析结果不能落在内网段。

    GitHub 的域名不会解析到内网，这一层是防 DNS 重绑定：攻击者控制一个域名、
    先解析到公网让校验通过、再解析到 169.254.169.254。虽然上面已经限定只认 GitHub 域名、
    理论上走不到这里，但"只靠域名白名单"是不该有的单点，多校验一次成本几乎为零。
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SkillFetchError(f"解析不了 {host}，检查网络或地址是否正确") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in net for net in _PRIVATE_NETS):
            raise SkillFetchError(f"{host} 解析到内网地址 {ip}，已拒绝")


def _client() -> httpx.Client:
    """GitHub 专用客户端：不跟随重定向到别的域名。

    follow_redirects=True 会安静地跟到任意主机 —— 域名白名单就白做了。
    这里手动跟，且每一步都重新校验主机。
    """
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                        headers={"User-Agent": "agent-platform-skill-import",
                                 "Accept": "application/vnd.github+json"})


def _get(url: str, *, accept: str | None = None) -> httpx.Response:
    """GET 一次，手工处理最多 3 次重定向，每次校验目标主机仍在白名单内。"""
    _assert_public_host(urlparse(url).hostname or "")
    with _client() as client:
        for _ in range(4):
            headers = {"Accept": accept} if accept else None
            try:
                resp = client.get(url, headers=headers)
            except httpx.TimeoutException as e:
                raise SkillFetchError(f"连接 GitHub 超时（{TIMEOUT_SECONDS:.0f} 秒），检查网络后重试") from e
            except httpx.HTTPError as e:
                raise SkillFetchError(f"连接 GitHub 失败：{e}") from e
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location") or ""
                nxt = httpx.URL(url).join(loc)
                if (nxt.host or "").lower() not in ALLOWED_HOSTS:
                    raise SkillFetchError(f"GitHub 把请求重定向到了 {nxt.host}，不在允许范围内")
                url = str(nxt)
                continue
            return resp
    raise SkillFetchError("GitHub 重定向次数过多")


def _status_error(resp: httpx.Response, what: str) -> SkillFetchError:
    """把 GitHub 的状态码翻译成人话。使用者看到的应该是"改哪里"，不是"404"。"""
    if resp.status_code == 404:
        return SkillFetchError(
            f"{what} 不存在。检查三件事：① 仓库是不是私有（私有库需要 token，当前不支持）；"
            "② 分支名写对了吗（很多仓库是 main，不是 master）；③ 路径有没有多打一个字")
    if resp.status_code == 403:
        body = (resp.text or "")[:200]
        if "rate limit" in body.lower():
            return SkillFetchError("GitHub 接口限流了（未登录每小时 60 次），等几分钟再试")
        return SkillFetchError(f"GitHub 拒绝了请求（403）：{body}")
    if resp.status_code == 401:
        return SkillFetchError("仓库需要登录才能访问（私有库），当前只支持公开仓库")
    return SkillFetchError(f"GitHub 返回 {resp.status_code}：{(resp.text or '')[:200]}")


# --------------------------------------------------------------------------- 抓取

def _api_base(ref: RepoRef) -> str:
    return f"https://api.github.com/repos/{ref.owner}/{ref.repo}"


def _list_dir(ref: RepoRef, path: str) -> list[dict]:
    """列出目录内容（GitHub contents API）。返回 [{name, type, size, download_url, path}]。"""
    suffix = f"/{path.strip('/')}" if path.strip("/") else ""
    url = f"{_api_base(ref)}{'/contents' + suffix}"
    if ref.ref:
        url += f"?ref={ref.ref}"
    resp = _get(url, accept="application/vnd.github+json")
    if resp.status_code == 404 and not path.strip("/"):
        # 根目录 404 基本只有一种原因：仓库本身不存在或不可见。
        # 这时候说"目录 (仓库根) 不存在"会把人引到错的方向。
        raise SkillFetchError(
            f"仓库 {ref.slug} 不存在或不可见。检查 owner/repo 有没有写错；"
            "私有仓库当前不支持（需要 token）")
    if resp.status_code != 200:
        raise _status_error(resp, f"目录 {path}")
    try:
        data = resp.json()
    except ValueError as e:
        raise SkillFetchError("GitHub 返回的不是 JSON，可能是地址指向了别的东西") from e
    if not isinstance(data, list):
        # 指向的是一个文件而不是目录
        raise SkillFetchError(f"{path} 是一个文件，不是目录")
    return data


def _download(ref: RepoRef, path: str, *, limit: int) -> bytes:
    """取一个文件的内容，走 **Contents API**（`?ref=` + base64 content）。

    为什么不用 raw.githubusercontent.com：那个域名在部分网络环境（含本项目所在的开发机）
    连不上 —— GitHub 主站的 API 可达，raw 域名超时。用 API 取可以复用同一条可达链路，
    而且返回体自带 size 与 encoding，能先判大小再解码。

    GitHub 对超过 1MB 的文件不返回 base64 content（encoding 为 none），这里直接拒并提示，
    不悄悄返回空内容。
    """
    url = f"{_api_base(ref)}/contents/{path.lstrip('/')}"
    if ref.ref:
        url += f"?ref={ref.ref}"
    resp = _get(url, accept="application/vnd.github+json")
    if resp.status_code != 200:
        raise _status_error(resp, path)
    try:
        data = resp.json()
    except ValueError as e:
        raise SkillFetchError(f"{path} 返回的不是 JSON") from e
    if isinstance(data, list):
        raise SkillFetchError(f"{path} 是目录，不是文件")

    size = int(data.get("size") or 0)
    if size > limit:
        raise SkillFetchError(f"{path} 有 {size // 1024}KB，超过 {limit // 1024}KB 上限")

    if data.get("encoding") == "base64" and data.get("content"):
        import base64

        try:
            raw = base64.b64decode(data["content"])
        except Exception as e:
            raise SkillFetchError(f"{path} 内容解码失败") from e
        if len(raw) > limit:
            raise SkillFetchError(f"{path} 解码后有 {len(raw) // 1024}KB，超过 {limit // 1024}KB 上限")
        return raw
    if data.get("encoding") == "none" or not data.get("content"):
        raise SkillFetchError(
            f"{path} 超过 1MB，GitHub 不返回内容。技能文件不能超过 1MB，请先裁剪")
    raise SkillFetchError(f"{path} 的内容编码无法识别：{data.get('encoding')}")


def _find_skill_md(ref: RepoRef) -> tuple[str, str]:
    """确定 SKILL.md 的位置，返回 (SKILL.md 的仓库内路径, 技能目录路径)。

    使用者的两种意图都要照顾到：
    - 贴的是**仓库根**：在常见位置找 SKILL.md（根目录 / skills/ 下唯一的那个 / 任意一层只有一个）
    - 贴的是**技能目录**：直接读该目录下的 SKILL.md
    """
    path = ref.path.strip("/")

    # 贴的就是 SKILL.md 文件
    if path.lower().endswith("skill.md"):
        return path, path.rsplit("/", 1)[0] if "/" in path else ""

    # 先按"目录里有 SKILL.md"处理
    try:
        entries = _list_dir(ref, path)
    except SkillFetchError:
        raise
    names = {e.get("name", "").lower() for e in entries}
    if "skill.md" in names:
        return f"{path}/SKILL.md" if path else "SKILL.md", path

    # 仓库根没有 SKILL.md：找一层候选目录
    candidates = [e for e in entries if e.get("type") == "dir" and e.get("name") != ".git"]
    # 优先 skills/ 下一层
    skills_dir = next((e for e in candidates if e.get("name", "").lower() == "skills"), None)
    if skills_dir:
        sub = _list_dir(ref, f"{path}/{skills_dir['name']}".strip("/"))
        subs = [e for e in sub if e.get("type") == "dir"]
        found = []
        for s in subs:
            p = f"{path}/{skills_dir['name']}/{s['name']}".strip("/")
            try:
                if any(e.get("name", "").lower() == "skill.md" for e in _list_dir(ref, p)):
                    found.append(p)
            except SkillFetchError:
                continue
        if len(found) == 1:
            return f"{found[0]}/SKILL.md", found[0]
        if len(found) > 1:
            names = "、".join(f.rsplit("/", 1)[-1] for f in found[:12])
            raise SkillFetchError(
                f"这个仓库里有 {len(found)} 个技能（{names}…）。请把地址指到具体那个技能目录，"
                f"例如 https://github.com/{ref.slug}/tree/{ref.ref or 'main'}/{found[0]}")

    # 再试"下一层里只有一个含 SKILL.md"
    found = []
    for c in candidates:
        p = f"{path}/{c['name']}".strip("/")
        try:
            if any(e.get("name", "").lower() == "skill.md" for e in _list_dir(ref, p)):
                found.append(p)
        except SkillFetchError:
            continue
    if len(found) == 1:
        return f"{found[0]}/SKILL.md", found[0]

    raise SkillFetchError(
        "这个位置没找到 SKILL.md。请把地址指到包含 SKILL.md 的那个技能目录，"
        f"例如 https://github.com/{ref.slug}/tree/{ref.ref or 'main'}/skills/某个技能")


def fetch_skill(url: str) -> dict:
    """抓取一个技能：返回 {skill_md, dir_path, ref, files: [{name, content(bytes)}], skipped: [...]}。

    不做解析（那是 skill_import 的事），也不写库 —— 与 /skills/parse 一样，
    结果回给前端确认后再走正常保存路径。
    """
    ref = parse_url(url)
    skill_md_path, dir_path = _find_skill_md(ref)

    if ref.ref is None:
        # 没写分支：用仓库默认分支。多一次请求，但比猜 main 更可靠（很多仓库是 master）。
        resp = _get(_api_base(ref), accept="application/vnd.github+json")
        if resp.status_code != 200:
            raise _status_error(resp, f"仓库 {ref.slug}")
        try:
            ref.ref = resp.json().get("default_branch") or "main"
        except ValueError:
            ref.ref = "main"

    skill_md = _download(ref, skill_md_path, limit=MAX_SKILL_MD_BYTES)

    # 资源：目录下的文本类文件（不含 SKILL.md 与 license 之类）
    entries = _list_dir(ref, dir_path)
    files: list[dict] = []
    skipped: list[str] = []
    total = len(skill_md)
    for e in entries:
        if e.get("type") != "file":
            continue
        name = e.get("name") or ""
        low = name.lower()
        if low == "skill.md":
            continue
        if low in META_FILES:
            skipped.append(name)
            continue
        if not low.endswith(TEXT_SUFFIXES):
            skipped.append(name)
            continue
        if len(files) >= MAX_FILES:
            skipped.append(f"{name}（超过 {MAX_FILES} 个文件上限）")
            continue
        size = int(e.get("size") or 0)
        if size > MAX_FILE_BYTES:
            skipped.append(f"{name}（{size // 1024}KB 超过单文件 {MAX_FILE_BYTES // 1024}KB 上限）")
            continue
        if total + size > MAX_TOTAL_BYTES:
            skipped.append(f"{name}（整次导入超过 {MAX_TOTAL_BYTES // 1024 // 1024}MB 上限）")
            continue
        content = _download(ref, e.get("path") or name, limit=MAX_FILE_BYTES)
        total += len(content)
        files.append({"name": name, "content": content})

    return {
        "skill_md": skill_md.decode("utf-8", errors="replace"),
        "dir_path": dir_path,
        "repo": ref.slug,
        "ref": ref.ref,
        "files": files,
        "skipped": skipped,
    }
