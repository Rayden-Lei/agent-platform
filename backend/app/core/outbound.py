"""出站请求的安全边界：内网地址拦截 + 域名白名单 + 安全的重定向跟随。

为什么要抽出来
-------------
2026-11-15 之前这套规则在三个地方各写了一份（tools/general.py 的 _PRIVATE_NETS、
tools/permission.py 的 _host_matches、services/skill_github.py 的 _PRIVATE_NETS），
而**工作流的 HTTP 节点一份都没有** —— 它能直接请求 169.254.169.254 这类云元数据地址，
成了平台里唯一没有出站防护的路径（2026-11-14 审计）。

同一个安全规则散在多处，漏一处就是一个洞。这里收成一份，谁要发外部请求就调它。

两种默认值，别混用
-----------------
- check_host(host, allowed=[...])：按白名单严格判断，空列表等于一律拒绝。
  用于「地址由管理员填、模型改不了」的场景（工具行、工作流 HTTP 节点）。
- check_host(host, allowed=None)：只拦内网、放行公网。
  用于「开箱即用」的内置工具，默认「公网可达但碰不到内网」已是安全下限。

这个区别以前靠两处注释解释，容易再写错，现在由参数类型自己说明。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# 内网与保留地址段：这些地址上的服务不该被平台代任何人之手访问
PRIVATE_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
        "169.254.0.0/16",   # link-local：云厂商元数据服务（169.254.169.254）就在这一段
        "::1/128", "fc00::/7", "fe80::/10",
        "0.0.0.0/8",        # 等价于本机
    )
]

# 跟随重定向的最大跳数：超过就放弃，避免 A→B→A 的循环
MAX_REDIRECTS = 3


class OutboundBlocked(Exception):
    """出站请求被安全规则拒绝。message 是给人看的原因，调用方直接展示或包装。"""


def pattern_matches(host: str, pattern: str) -> bool:
    """单个白名单项与主机的匹配。三种写法都要认（界面上三种都在用）：

    - 精确：`api.example.com` 只放行它自己
    - 隐式后缀：`api.example.com` 同时覆盖 `v2.api.example.com`
      （必须带点前缀判断，否则 `notapi.example.com` 会被误放行）
    - 显式通配：`*.openai.com` 匹配任意层级子域，但**不含** `openai.com` 本身
      （与 TLS 通配证书语义一致；要连根域就再写一条 `openai.com`）

    隐式后缀这条口径历史上就有（工具行与内置工具都用），收紧会让存量配置静默失效，
    所以保留；它不削弱安全性 —— 覆盖的仍是同一个注册域下的子域。
    """
    host = (host or "").lower()
    pattern = (pattern or "").strip().lower().lstrip(".")
    if not host or not pattern:
        return False
    if pattern.startswith("*"):
        suffix = pattern[1:]  # ".example.com"
        if not suffix.startswith("."):
            return False
        # 通配吃掉子域，但 *.example.com 不匹配 example.com 本身
        return host.endswith(suffix) and host != suffix[1:]
    return host == pattern or host.endswith("." + pattern)


# DNS 解析器：默认走系统。测试与特殊部署可以替换（比如内网解析走指定 DNS）。
# 做成模块级变量而不是参数，是为了不让每个调用方都多传一个「无关」参数；
# 需要定制的场景在测试里 monkeypatch 它即可。
_resolver = socket.getaddrinfo


def resolve_ips(host: str) -> list:
    """域名 → IP 列表。解析失败抛 OutboundBlocked（连不上就不该继续）。"""
    try:
        infos = _resolver(host, None)
    except (socket.gaierror, UnicodeError) as e:
        raise OutboundBlocked("域名无法解析：" + host) from e
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def check_host(host: str, allowed: list[str] | None = None) -> None:
    """校验目标主机能否访问。不通过抛 OutboundBlocked。

    Args:
        host: 目标主机名（不含端口与协议）。
        allowed: 白名单。None 表示「只要不是内网就放行」；空列表表示「一律拒绝」。

    Raises:
        OutboundBlocked: 缺主机名、解析失败、解析到内网、或不在白名单内。

    Note:
        先解析再判内网：只比对字符串的话，自建 DNS 指向内网的域名就能绕过。
        解析结果里**任何一个** IP 落在内网段就拒绝（防多 A 记录挑一个内网 IP）。
    """
    if not host:
        raise OutboundBlocked("URL 缺少主机名")
    for ip in resolve_ips(host):
        if any(ip in net for net in PRIVATE_NETS):
            raise OutboundBlocked("不允许访问内网地址（" + host + " 解析到 " + str(ip) + "）")
    if allowed is None:
        return
    patterns = [str(p).strip() for p in (allowed or []) if str(p).strip()]
    if not patterns:
        raise OutboundBlocked("没有配置允许访问的域名，已拒绝：" + host)
    if not any(pattern_matches(host, p) for p in patterns):
        raise OutboundBlocked("域名不在白名单内：" + host + "（允许：" + ", ".join(patterns) + "）")


def check_url(url: str, allowed: list[str] | None = None) -> None:
    """按完整 URL 校验（取出主机名后走 check_host）。"""
    check_host(urlparse(url).hostname or "", allowed)


def _next_hop(current: str, resp: httpx.Response) -> str | None:
    """这一跳是不是重定向；是则返回下一跳的绝对地址，否则 None。

    抽出来给同步与异步两个实现共用：重定向的判定口径只能有一份，
    两边各写一遍迟早会出现"同步拦住了、异步没拦住"的分叉（就是本次审计的成因）。
    """
    if resp.status_code not in (301, 302, 303, 307, 308):
        return None
    location = resp.headers.get("location") or ""
    if not location:
        return None  # 重定向却没有 Location：原样返回，让调用方按状态码处理
    return str(httpx.URL(current).join(location))


def request_with_checked_redirects(
    url: str,
    *,
    allowed: list[str] | None = None,
    method: str = "GET",
    timeout: float = 30,
    max_redirects: int = MAX_REDIRECTS,
    **kwargs,
) -> httpx.Response:
    """发一次请求，**手工跟随重定向并逐跳校验目标主机**（同步版）。

    为什么不能直接用 follow_redirects=True：它会把请求安静地送到任意主机 ——
    初始地址过了白名单，对方 302 到 169.254.169.254 就绕过了全部检查。
    （services/skill_github.py 早就踩过这个坑并手工跟，这里把它固化成公共实现。）

    Raises:
        OutboundBlocked: 初始地址或任意一跳的重定向目标不合法。
    """
    check_url(url, allowed)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        current = url
        for _ in range(max_redirects + 1):
            resp = client.request(method.upper(), current, **kwargs)
            nxt = _next_hop(current, resp)
            if nxt is None:
                return resp
            check_url(nxt, allowed)  # 每一跳都重新校验，不只第一跳
            if resp.status_code == 303:
                method = "GET"
                kwargs.pop("json", None)
            current = nxt
    raise OutboundBlocked("重定向次数超过 " + str(max_redirects) + " 次，已放弃：" + url)


async def arequest_with_checked_redirects(
    url: str,
    *,
    allowed: list[str] | None = None,
    method: str = "GET",
    timeout: float = 30,
    max_redirects: int = MAX_REDIRECTS,
    **kwargs,
) -> httpx.Response:
    """异步版：语义与 request_with_checked_redirects 完全相同，供 async 调用方使用。

    为什么必须有这一份：内置 http_request 是 async 的，原先直接用
    `httpx.AsyncClient(follow_redirects=True)` —— 首跳过了 _host_allowed 之后，
    对方 302 到 169.254.169.254 就绕过全部检查（2026-11-18 审计的 P0）。
    同步版不能拿来凑合：在事件循环里跑同步 httpx 会阻塞整个 worker。
    """
    check_url(url, allowed)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        current = url
        for _ in range(max_redirects + 1):
            resp = await client.request(method.upper(), current, **kwargs)
            nxt = _next_hop(current, resp)
            if nxt is None:
                return resp
            check_url(nxt, allowed)  # 每一跳都重新校验，不只第一跳
            if resp.status_code == 303:
                method = "GET"
                kwargs.pop("json", None)
            current = nxt
    raise OutboundBlocked("重定向次数超过 " + str(max_redirects) + " 次，已放弃：" + url)
