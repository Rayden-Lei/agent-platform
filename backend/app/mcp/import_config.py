"""MCP 服务器配置的「粘贴识别」（docs/17 §5，傻瓜化）。

解决的问题：使用者手上通常只有一段从别人那里抄来的配置，形式五花八门 ——
  - Claude / Cursor 的 mcpServers JSON
  - 一行命令式的 `npx -y @modelcontextprotocol/server-github`（stdio，本平台不支持）
  - 一个纯 URL
  - `url + token` 两条信息
让人手动拆成「地址 / 传输 / 白名单 / 凭据 / 额外请求头」五个字段，是这一页最大的摩擦点。

本模块只做**识别与预填**，不落库：识别结果回前端填进表单，使用者确认后走正常的 POST /mcp-servers。
因此不存在"粘贴能绕过校验"的第二套入口 —— 白名单、凭据、重名仍由服务层判。

设计取舍：
- **宁可少猜，不要猜错**。识别不出来就少填一个字段并在 notes 里说清缺什么，
  而不是硬塞一个看起来像的值（比如把命令里的第一个 token 当 URL）。
- 凭据永远不写进 headers：后端 secret_header_keys 会 400 拒掉，这里直接把 token 类键提进 secret。
- stdio 配置能认出来，但**明确拒绝**并给出原因 —— 让使用者立刻知道"这个不是配错了，是本平台不支持"。
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

# 键名里出现这些词的请求头当凭据（与 mcp_service.SECRET_HEADER_MARKERS 同口径，
# 那边判"禁止写进 headers"，这边主动提取到 secret）
_SECRET_MARKERS = ("authorization", "cookie", "token", "key", "secret", "password")
# 传输推断用的路径特征
_SSE_HINTS = ("/sse", "/events", "/stream")


class McpConfigError(ValueError):
    """粘贴的内容无法识别。message 直接回给使用者，要说清看到了什么、期待什么。"""


def _looks_secret(key: str) -> bool:
    return any(m in key.lower() for m in _SECRET_MARKERS)


def _host_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise McpConfigError(f"地址必须以 http:// 或 https:// 开头，这个是 {parsed.scheme or '（没有协议）'}")
    if not parsed.hostname:
        raise McpConfigError(f"地址缺少主机名：{url}")
    return parsed.hostname


def _guess_transport(url: str) -> str:
    """按路径猜传输类型。猜错的代价只是测试连接报错，使用者能改，所以这里可以猜。"""
    low = url.lower()
    return "sse" if any(low.endswith(h) or h + "?" in low for h in _SSE_HINTS) else "http"


def _split_headers(headers: dict) -> tuple[dict[str, str], str | None]:
    """把请求头拆成（非敏感头, 凭据）。

    Authorization 只认 `Bearer xxx` 形式并把 xxx 提成 secret；别的形式（如 `Basic xxx`、
    自定义 scheme）整条留在 secret 里 —— 本平台的 secret 只按 Bearer 发，
    擅自改写会让使用者以为配好了却一直 401。
    """
    plain: dict[str, str] = {}
    secret: str | None = None
    for key, value in (headers or {}).items():
        k, v = str(key), str(value)
        if k.lower() == "authorization":
            if v.lower().startswith("bearer "):
                secret = v[7:].strip() or secret
            else:
                # 不是 Bearer：整条放 secret 里原样带（后端只发 Bearer，这里退化成无凭据并说明）
                raise McpConfigError(
                    f"Authorization 头的格式是 {v.split(' ')[0] if ' ' in v else v}，"
                    "本平台只支持 Bearer Token；请把 token 单独填到「凭据」里"
                )
        elif _looks_secret(k):
            secret = v or secret
        else:
            plain[k] = v
    return plain, secret


def _from_mapping(obj: dict) -> dict:
    """认 mcpServers / servers 这层包装，取其中一个条目。"""
    # Claude Desktop / Cursor：{"mcpServers": {"名字": {...}}}
    for wrapper in ("mcpServers", "servers", "mcp_servers"):
        inner = obj.get(wrapper)
        if isinstance(inner, dict) and inner:
            first_key = next(iter(inner))
            entry = inner[first_key]
            if not isinstance(entry, dict):
                raise McpConfigError(f"{wrapper}.{first_key} 不是一个对象")
            return _from_entry(first_key, entry)
    return _from_entry("", obj)


def _from_entry(name_hint: str, entry: dict) -> dict:
    """单个服务器条目 → 平台字段。"""
    # stdio 明确拒绝：本平台不做 stdio（等于在服务器上执行配置里写的任意命令）
    command = entry.get("command") or entry.get("args")
    if command and not entry.get("url"):
        cmd = entry.get("command") or ""
        raise McpConfigError(
            f"这是 stdio 形式的配置（{' '.join(str(c) for c in [cmd, *(entry.get('args') or [])]).strip()[:80]}），"
            "本平台不支持 stdio —— 那等于在我们服务器上执行这段命令。"
            "请改用对方提供的 HTTP / SSE 地址；如果对方只给 stdio，需要在它那侧加一层 HTTP 网关"
        )

    url = str(entry.get("url") or entry.get("endpoint") or entry.get("serverUrl") or "").strip()
    if not url:
        raise McpConfigError(
            "没找到服务器地址。可识别的内容：URL 本身、mcpServers 形式的 JSON（要有 url 字段）、"
            "或「地址 + 凭据」两行。收到的内容里既没有 http(s) 地址，也不是已知的配置结构"
        )

    host = _host_of(url)
    plain, secret = _split_headers(entry.get("headers") or {})
    # 顶层 token / apiKey 这类键也当凭据
    for key in ("token", "apiKey", "api_key", "secret", "password"):
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            secret = secret or raw.strip()

    transport = entry.get("transport") or entry.get("type")
    transport = str(transport).lower() if transport else ""
    # 有些配置写 "type": "streamableHttp" / "sse" / "http"
    if transport not in ("http", "sse"):
        transport = _guess_transport(url)

    return {
        "name": (str(entry.get("name") or name_hint or "").strip())[:64] or None,
        "url": url,
        "transport": transport,
        "headers": plain,
        "secret": secret,
        # 白名单由这里直接给出：host 从地址里取，使用者不用再手抄一遍域名
        "allowed_hosts": [host],
    }


def parse_config(text: str) -> dict:
    """把一段粘贴内容识别成 MCP 服务器字段。识别不出的部分为 None，由前端留空让使用者补。

    返回：
      {name, url, transport, headers, secret, allowed_hosts, notes: [...]}
    notes 是给使用者看的说明（识别到什么、为什么这样填、还缺什么）。
    """
    raw = (text or "").strip()
    if not raw:
        raise McpConfigError("粘贴内容是空的")

    notes: list[str] = []

    # 1) JSON 配置块（可能是整段 mcpServers，也可能是单个条目）
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise McpConfigError(f"这段内容看起来是 JSON，但解析失败：{e.msg}（第 {e.lineno} 行）") from e
        if not isinstance(obj, dict):
            raise McpConfigError("JSON 顶层必须是对象")
        result = _from_mapping(obj)
        notes.append("已按 JSON 配置识别")
        if result.get("secret"):
            notes.append("已把凭据提取到「凭据」字段（它就是后端加密保存的那一项）")
        return {**result, "notes": notes}

    # 2) 单个 URL（可能后面跟 token / 空格分隔）
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    url_line = next((ln for ln in lines if re.match(r"^https?://", ln, re.I)), None)
    if url_line:
        url = url_line.split()[0]
        host = _host_of(url)
        # 同一行或后续行里出现的 token 当凭据
        secret = None
        rest = " ".join(lines)
        for pattern in (r"Bearer\s+(\S+)", r"(?:token|key|secret|api_key)\s*[=:]\s*(\S+)", r"sk-\S+"):
            m = re.search(pattern, rest, re.I)
            if m:
                secret = m.group(1) if m.groups() else m.group(0)
                break
        transport = _guess_transport(url)
        notes.append(f"已从地址推断传输类型为 {transport.upper()}")
        notes.append(f"已把 {host} 填入白名单")
        if secret:
            notes.append("已提取凭据")
        return {
            "name": None, "url": url, "transport": transport, "headers": {},
            "secret": secret, "allowed_hosts": [host], "notes": notes,
        }

    # 3) 命令式（npx / uvx / docker run）—— stdio，明确拒绝
    if re.match(r"^(npx|uvx|uv|docker|node|python|pipx)\b", raw, re.I):
        raise McpConfigError(
            "这是 stdio 启动命令，本平台不支持 stdio —— 那等于在我们服务器上执行这条命令。"
            "请改用对方提供的 HTTP / SSE 地址"
        )

    raise McpConfigError(
        "无法识别的配置。支持三种粘贴形式：① 服务器地址（http/https 开头）；"
        "② Claude/Cursor 的 mcpServers JSON；③ 「地址 + 凭据」两行"
    )
