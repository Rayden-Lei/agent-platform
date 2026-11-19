"""GitHub 导入的**抓取链路**（skill_github 的 _get / _list_dir / _download / _find_skill_md / fetch_skill）。

与 test_skill_github.py 的分工：那个文件把 fetch_skill 整体打桩，测的是路由的编排与落库回滚；
这里不碰路由，专测「拿到地址之后怎么发请求、怎么判断状态码、怎么找 SKILL.md、怎么筛资源」。

为什么值得单独测：这是平台里唯一允许服务端主动访问「用户给的任意地址」的入口，
重定向跟随、状态码翻译、体积上限任何一处写错都是实打实的洞或线上故障。
全部用 httpx.MockTransport，不发真实网络请求。
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.services import skill_github
from app.services.skill_github import RepoRef, SkillFetchError

API = "https://api.github.com/repos/owner/repo"


def _routes(monkeypatch, table: dict):
    """把 skill_github 的 HTTP 出口换成按 URL 路由的 MockTransport。

    table 的键是完整 URL；值是 httpx.Response 或接收 request 的函数。
    未命中的 URL 一律回 404，避免用例漏配时静默拿到别的响应。
    同时把 _assert_public_host 打成空操作：那层要真解析 DNS，用例不该依赖网络。
    """
    seen: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        # 精确匹配：不能用 startswith —— 仓库根地址 /repos/o/r 是每个 contents 地址的前缀，
        # 前缀匹配会让"查默认分支"那条响应把后续所有请求都吃掉。
        value = table.get(url)
        if value is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return value(request) if callable(value) else value

    def _factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(_handler), follow_redirects=False, trust_env=False)

    monkeypatch.setattr(skill_github, "_client", _factory)
    monkeypatch.setattr(skill_github, "_assert_public_host", lambda host: None)
    return seen


def _contents_url(path: str = "", ref: str | None = None) -> str:
    url = API + ("/contents" + (f"/{path}" if path else ""))
    return f"{url}?ref={ref}" if ref else url


# --------------------------------------------------------------------------- _get：重定向

def test_get_follows_redirect_inside_allowed_hosts(monkeypatch):
    """白名单内的重定向要跟：GitHub 会把仓库改名后的旧地址 301 到新地址。"""
    calls = _routes(monkeypatch, {
        "https://api.github.com/old": httpx.Response(301, headers={"location": "https://api.github.com/new"}),
        "https://api.github.com/new": httpx.Response(200, json={"ok": True}),
    })
    resp = skill_github._get("https://api.github.com/old")
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    assert calls == ["https://api.github.com/old", "https://api.github.com/new"]


def test_get_refuses_redirect_to_foreign_host(monkeypatch):
    """**关键安全断言**：跟到白名单外的域名就等于白名单失效（可被导向内网或元数据服务）。"""
    _routes(monkeypatch, {
        "https://api.github.com/x": httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data/"}),
    })
    with pytest.raises(SkillFetchError) as ei:
        skill_github._get("https://api.github.com/x")
    assert "不在允许范围内" in str(ei.value)


def test_get_gives_up_after_too_many_redirects(monkeypatch):
    """一直 302 同一个地址：必须停下并报错，不能无限跟（否则就是一个打不完的循环）。"""
    _routes(monkeypatch, {
        "https://api.github.com/loop": httpx.Response(302, headers={"location": "https://api.github.com/loop"}),
    })
    with pytest.raises(SkillFetchError) as ei:
        skill_github._get("https://api.github.com/loop")
    assert "重定向次数过多" in str(ei.value)


@pytest.mark.parametrize("exc,fragment", [
    (httpx.TimeoutException("slow"), "超时"),
    (httpx.ConnectError("refused"), "连接 GitHub 失败"),
])
def test_get_translates_transport_errors(monkeypatch, exc, fragment):
    """网络故障要翻译成人话：使用者看到的应该是"检查网络"，不是 httpx 的堆栈。"""
    def _boom(request):
        raise exc

    _routes(monkeypatch, {"https://api.github.com/x": _boom})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._get("https://api.github.com/x")
    assert fragment in str(ei.value)


# --------------------------------------------------------------------------- 状态码翻译

@pytest.mark.parametrize("status,body,fragment", [
    (404, "", "不存在"),
    (401, "", "私有库"),
    (403, "API rate limit exceeded", "限流"),
    (403, "forbidden by policy", "拒绝了请求"),
    (500, "boom", "GitHub 返回 500"),
])
def test_status_error_speaks_human(status, body, fragment):
    """每个状态码都要给出"改哪里"的指引，而不是把数字丢给使用者。"""
    resp = httpx.Response(status, text=body)
    assert fragment in str(skill_github._status_error(resp, "目录 skills/pdf"))


def test_status_error_only_names_the_path_for_404():
    """只有 404 是"这个路径不对"，才带上路径；401/403 是仓库级问题，
    带上"目录 skills/pdf"会让人以为换个目录就能绕过去。"""
    assert "目录 skills/pdf" in str(skill_github._status_error(httpx.Response(404), "目录 skills/pdf"))
    assert "目录 skills/pdf" not in str(skill_github._status_error(httpx.Response(401), "目录 skills/pdf"))


# --------------------------------------------------------------------------- _list_dir

def test_list_dir_returns_entries(monkeypatch):
    entries = [{"name": "SKILL.md", "type": "file", "size": 10, "path": "skills/pdf/SKILL.md"}]
    calls = _routes(monkeypatch, {_contents_url("skills/pdf", "main"): httpx.Response(200, json=entries)})
    got = skill_github._list_dir(RepoRef("owner", "repo", "main", "skills/pdf"), "skills/pdf")
    assert got == entries
    assert calls == [_contents_url("skills/pdf", "main")]


def test_list_dir_root_404_says_repo_missing(monkeypatch):
    """根目录 404 的真实原因是仓库不存在，说"目录不存在"会把人引到错方向。"""
    _routes(monkeypatch, {_contents_url("", "main"): httpx.Response(404, json={})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._list_dir(RepoRef("owner", "repo", "main", ""), "")
    assert "仓库 owner/repo 不存在或不可见" in str(ei.value)


def test_list_dir_subdir_404_uses_status_error(monkeypatch):
    """子目录 404 才是"目录写错了"，走通用状态码翻译。"""
    _routes(monkeypatch, {_contents_url("a/b", "main"): httpx.Response(404, json={})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._list_dir(RepoRef("owner", "repo", "main", "a/b"), "a/b")
    assert "目录 a/b 不存在" in str(ei.value)


def test_list_dir_rejects_non_json(monkeypatch):
    _routes(monkeypatch, {_contents_url("x", "main"): httpx.Response(200, text="<html>nope</html>")})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._list_dir(RepoRef("owner", "repo", "main", "x"), "x")
    assert "不是 JSON" in str(ei.value)


def test_list_dir_rejects_file_path(monkeypatch):
    """地址指到了文件而不是目录：要说清楚，否则会接着去列它的"子项"然后拿到一堆 404。"""
    _routes(monkeypatch, {_contents_url("x", "main"): httpx.Response(200, json={"name": "x", "type": "file"})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._list_dir(RepoRef("owner", "repo", "main", "x"), "x")
    assert "是一个文件，不是目录" in str(ei.value)


# --------------------------------------------------------------------------- _download

def _b64(raw: bytes) -> dict:
    return {"size": len(raw), "encoding": "base64", "content": base64.b64encode(raw).decode("ascii")}


def test_download_decodes_base64(monkeypatch):
    _routes(monkeypatch, {_contents_url("a.py", "main"): httpx.Response(200, json=_b64(b"print(1)"))})
    assert skill_github._download(RepoRef("owner", "repo", "main", "a.py"), "a.py", limit=1024) == b"print(1)"


def test_download_rejects_oversize_by_declared_size(monkeypatch):
    """先看 GitHub 声明的 size 就拒：不必先把内容拉下来再判断。"""
    _routes(monkeypatch, {_contents_url("big.py", "main"): httpx.Response(
        200, json={"size": 4096, "encoding": "base64", "content": ""})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._download(RepoRef("owner", "repo", "main", "big.py"), "big.py", limit=1024)
    assert "超过 1KB 上限" in str(ei.value)


def test_download_rejects_oversize_after_decode(monkeypatch):
    """声明的 size 可以撒谎，解码后的真实长度也要再校验一次。"""
    payload = b"x" * 4096
    _routes(monkeypatch, {_contents_url("liar.py", "main"): httpx.Response(
        200, json={"size": 10, "encoding": "base64", "content": base64.b64encode(payload).decode()})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._download(RepoRef("owner", "repo", "main", "liar.py"), "liar.py", limit=1024)
    assert "解码后有 4KB" in str(ei.value)


def test_download_rejects_encoding_none(monkeypatch):
    """超过 1MB 的文件 GitHub 不返回内容：要明确报错，不能悄悄返回空串。"""
    _routes(monkeypatch, {_contents_url("huge.py", "main"): httpx.Response(
        200, json={"size": 2 * 1024 * 1024, "encoding": "none", "content": ""})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._download(RepoRef("owner", "repo", "main", "huge.py"), "huge.py", limit=8 * 1024 * 1024)
    assert "超过 1MB" in str(ei.value)


def test_download_rejects_unknown_encoding(monkeypatch):
    _routes(monkeypatch, {_contents_url("w.py", "main"): httpx.Response(
        200, json={"size": 3, "encoding": "gzip", "content": "abc"})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._download(RepoRef("owner", "repo", "main", "w.py"), "w.py", limit=1024)
    assert "编码无法识别" in str(ei.value)


def test_download_rejects_directory_payload(monkeypatch):
    _routes(monkeypatch, {_contents_url("d", "main"): httpx.Response(200, json=[{"name": "a"}])})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._download(RepoRef("owner", "repo", "main", "d"), "d", limit=1024)
    assert "是目录，不是文件" in str(ei.value)


def test_download_rejects_non_json(monkeypatch):
    _routes(monkeypatch, {_contents_url("a.py", "main"): httpx.Response(200, text="not json")})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._download(RepoRef("owner", "repo", "main", "a.py"), "a.py", limit=1024)
    assert "返回的不是 JSON" in str(ei.value)


def test_download_propagates_status_error(monkeypatch):
    _routes(monkeypatch, {_contents_url("a.py", "main"): httpx.Response(401, text="")})
    with pytest.raises(SkillFetchError) as ei:
        skill_github._download(RepoRef("owner", "repo", "main", "a.py"), "a.py", limit=1024)
    assert "私有库" in str(ei.value)


# --------------------------------------------------------------------------- _find_skill_md

def _dir(*names, types=None, prefix=""):
    """构造 contents API 的目录条目。path 是**仓库内完整路径**（GitHub 实际返回的就是完整路径，
    只写文件名会让 _download 拿到 "helper.py" 而不是 "skills/pdf/helper.py"）。"""
    return [{"name": n, "type": (types or {}).get(n, "dir"), "path": f"{prefix}/{n}".strip("/")} for n in names]


def test_find_skill_md_when_url_points_at_the_file():
    """地址直接指到 SKILL.md：不用发任何请求。"""
    ref = RepoRef("owner", "repo", "main", "skills/pdf/SKILL.md")
    assert skill_github._find_skill_md(ref) == ("skills/pdf/SKILL.md", "skills/pdf")


def test_find_skill_md_in_the_given_directory(monkeypatch):
    _routes(monkeypatch, {_contents_url("skills/pdf", "main"): httpx.Response(
        200, json=_dir("SKILL.md", "helper.py", types={"SKILL.md": "file", "helper.py": "file"}))})
    ref = RepoRef("owner", "repo", "main", "skills/pdf")
    assert skill_github._find_skill_md(ref) == ("skills/pdf/SKILL.md", "skills/pdf")


def test_find_skill_md_under_unique_skills_subdir(monkeypatch):
    """贴的是仓库根，SKILL.md 在 skills/pdf/ 下：要能自己找下去。"""
    _routes(monkeypatch, {
        _contents_url("", "main"): httpx.Response(200, json=_dir("skills", "README.md",
                                                                 types={"README.md": "file"})),
        _contents_url("skills", "main"): httpx.Response(200, json=_dir("pdf")),
        _contents_url("skills/pdf", "main"): httpx.Response(200, json=_dir("SKILL.md", types={"SKILL.md": "file"})),
    })
    ref = RepoRef("owner", "repo", "main", "")
    assert skill_github._find_skill_md(ref) == ("skills/pdf/SKILL.md", "skills/pdf")


def test_find_skill_md_under_single_nested_dir(monkeypatch):
    """没有 skills/ 目录，但唯一一个子目录里有 SKILL.md：也算找到了。"""
    _routes(monkeypatch, {
        _contents_url("", "main"): httpx.Response(200, json=_dir("pdf", "docs")),
        _contents_url("pdf", "main"): httpx.Response(200, json=_dir("SKILL.md", types={"SKILL.md": "file"})),
        _contents_url("docs", "main"): httpx.Response(200, json=_dir("guide.md", types={"guide.md": "file"})),
    })
    ref = RepoRef("owner", "repo", "main", "")
    assert skill_github._find_skill_md(ref) == ("pdf/SKILL.md", "pdf")


def test_find_skill_md_reports_ambiguity(monkeypatch):
    """多个技能时要让人选，不能随便挑一个导入 —— 挑错了使用者还不知道。"""
    _routes(monkeypatch, {
        _contents_url("", "main"): httpx.Response(200, json=_dir("skills")),
        _contents_url("skills", "main"): httpx.Response(200, json=_dir("pdf", "excel")),
        _contents_url("skills/pdf", "main"): httpx.Response(200, json=_dir("SKILL.md", types={"SKILL.md": "file"})),
        _contents_url("skills/excel", "main"): httpx.Response(200, json=_dir("SKILL.md", types={"SKILL.md": "file"})),
    })
    with pytest.raises(SkillFetchError) as ei:
        skill_github._find_skill_md(RepoRef("owner", "repo", "main", ""))
    assert "2 个技能" in str(ei.value)
    assert "pdf" in str(ei.value) and "excel" in str(ei.value)


def test_find_skill_md_raises_when_absent(monkeypatch):
    _routes(monkeypatch, {
        _contents_url("", "main"): httpx.Response(200, json=_dir("docs")),
        _contents_url("docs", "main"): httpx.Response(200, json=_dir("a.md", types={"a.md": "file"})),
    })
    with pytest.raises(SkillFetchError) as ei:
        skill_github._find_skill_md(RepoRef("owner", "repo", "main", ""))
    assert "没找到 SKILL.md" in str(ei.value)


# --------------------------------------------------------------------------- fetch_skill

SKILL_MD = b"---\nname: pdf\ndescription: d\n---\n\n# body\n"


def test_fetch_skill_resolves_default_branch(monkeypatch):
    """地址里没写分支：要问一次仓库的默认分支，不能猜 main（很多仓库是 master）。"""
    calls = _routes(monkeypatch, {
        API: httpx.Response(200, json={"default_branch": "master"}),
        # 没写分支时 _find_skill_md 会先按无 ref 查一次（拿不到就 404），拿到默认分支后重查
        _contents_url("skills/pdf", None): httpx.Response(404, json={}),
        _contents_url("skills/pdf", "master"): httpx.Response(
            200, json=_dir("SKILL.md", "helper.py", types={"SKILL.md": "file", "helper.py": "file"},
                           prefix="skills/pdf")),
        _contents_url("skills/pdf/SKILL.md", "master"): httpx.Response(200, json=_b64(SKILL_MD)),
        _contents_url("skills/pdf/helper.py", "master"): httpx.Response(200, json=_b64(b"print(1)")),
    })
    out = skill_github.fetch_skill("https://github.com/owner/repo/tree/master/skills/pdf")
    assert out["ref"] == "master"
    assert out["repo"] == "owner/repo"
    assert out["skill_md"].startswith("---")
    assert [f["name"] for f in out["files"]] == ["helper.py"]
    assert out["files"][0]["content"] == b"print(1)"


def test_fetch_skill_skips_meta_and_binary_files(monkeypatch):
    """资源只收文本类：license/README 属于元信息，png/zip 对 load_skill 没用，都要列进 skipped 让人看见。"""
    _routes(monkeypatch, {
        _contents_url("s", "main"): httpx.Response(200, json=[
            {"name": "SKILL.md", "type": "file", "size": len(SKILL_MD), "path": "s/SKILL.md"},
            {"name": "LICENSE", "type": "file", "size": 5, "path": "s/LICENSE"},
            {"name": "README.md", "type": "file", "size": 5, "path": "s/README.md"},
            {"name": "logo.png", "type": "file", "size": 5, "path": "s/logo.png"},
            {"name": "sub", "type": "dir", "size": 0, "path": "s/sub"},
            {"name": "run.py", "type": "file", "size": 6, "path": "s/run.py"},
        ]),
        _contents_url("s/SKILL.md", "main"): httpx.Response(200, json=_b64(SKILL_MD)),
        _contents_url("s/run.py", "main"): httpx.Response(200, json=_b64(b"run()\n")),
    })
    out = skill_github.fetch_skill("https://github.com/owner/repo/tree/main/s")
    assert [f["name"] for f in out["files"]] == ["run.py"]
    assert "LICENSE" in out["skipped"] and "README.md" in out["skipped"]
    assert "logo.png" in out["skipped"]
    # 目录条目既不是资源也不该出现在 skipped 里（它不是"被跳过的文件"）
    assert not any("sub" in s for s in out["skipped"])


def test_fetch_skill_skips_files_over_size_limit(monkeypatch):
    _routes(monkeypatch, {
        _contents_url("s", "main"): httpx.Response(200, json=[
            {"name": "SKILL.md", "type": "file", "size": len(SKILL_MD), "path": "s/SKILL.md"},
            {"name": "big.py", "type": "file", "size": 900 * 1024, "path": "s/big.py"},
        ]),
        _contents_url("s/SKILL.md", "main"): httpx.Response(200, json=_b64(SKILL_MD)),
    })
    out = skill_github.fetch_skill("https://github.com/owner/repo/tree/main/s")
    assert out["files"] == []
    assert any("900KB" in s and "上限" in s for s in out["skipped"])


def test_fetch_skill_skips_beyond_file_count_limit(monkeypatch):
    monkeypatch.setattr(skill_github, "MAX_FILES", 1)
    _routes(monkeypatch, {
        _contents_url("s", "main"): httpx.Response(200, json=[
            {"name": "SKILL.md", "type": "file", "size": len(SKILL_MD), "path": "s/SKILL.md"},
            {"name": "a.py", "type": "file", "size": 1, "path": "s/a.py"},
            {"name": "b.py", "type": "file", "size": 1, "path": "s/b.py"},
        ]),
        _contents_url("s/SKILL.md", "main"): httpx.Response(200, json=_b64(SKILL_MD)),
        _contents_url("s/a.py", "main"): httpx.Response(200, json=_b64(b"a")),
    })
    out = skill_github.fetch_skill("https://github.com/owner/repo/tree/main/s")
    assert [f["name"] for f in out["files"]] == ["a.py"]
    assert any("文件上限" in s for s in out["skipped"])


def test_fetch_skill_skips_beyond_total_bytes_limit(monkeypatch):
    """整次导入的总量上限：单个文件都合规，合起来超了也要挡（一个仓库不能撑爆内存）。

    SKILL.md 本身也计入总量（41 字节），所以上限取 41+80+10：a.py 放得下，再塞 b.py 就超。
    """
    monkeypatch.setattr(skill_github, "MAX_TOTAL_BYTES", 41 + 80 + 10)
    _routes(monkeypatch, {
        _contents_url("s", "main"): httpx.Response(200, json=[
            {"name": "SKILL.md", "type": "file", "size": len(SKILL_MD), "path": "s/SKILL.md"},
            {"name": "a.py", "type": "file", "size": 80, "path": "s/a.py"},
            {"name": "b.py", "type": "file", "size": 80, "path": "s/b.py"},
        ]),
        _contents_url("s/SKILL.md", "main"): httpx.Response(200, json=_b64(SKILL_MD)),
        _contents_url("s/a.py", "main"): httpx.Response(200, json=_b64(b"x" * 80)),
    })
    out = skill_github.fetch_skill("https://github.com/owner/repo/tree/main/s")
    assert [f["name"] for f in out["files"]] == ["a.py"]
    assert any("MB 上限" in s or "上限" in s for s in out["skipped"])


def test_fetch_skill_reports_missing_repo(monkeypatch):
    _routes(monkeypatch, {API: httpx.Response(404, json={})})
    with pytest.raises(SkillFetchError) as ei:
        skill_github.fetch_skill("https://github.com/owner/repo")
    assert "不存在" in str(ei.value)
