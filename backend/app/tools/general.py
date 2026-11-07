"""通用内置工具：文本、编码、随机、JSON 取值、HTTP 请求、联网搜索。

与 calculator / current_time 的区别：那几个是"每个智能体都无条件挂上"的基础工具，
这里是按需挂在智能体上的能力型工具（工具页勾选后才暴露给模型）。

设计原则（都是踩过的坑）：
- 不抛异常给模型看堆栈：可预期的输入错误一律返回 {"error": "人话"}，让模型自己纠正
- 有资源上限：输入长度、返回体积、并发与超时都设死，别让一次调用拖垮后端
- 不发 IO 到不该去的地方：HTTP 请求与联网搜索都有域名白名单，默认拒绝内网地址
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import logging
import random
import re
import socket
from urllib.parse import urlsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---- 通用上限：模型生成的参数不可信，全部按最坏情况设 ----
TEXT_MAX_CHARS = 100_000          # 文本统计的输入上限（纯保护性，不开放配置）
JSON_MAX_BYTES = 1_000_000        # json_query 的输入上限（同上）

# 各工具自己的配置默认值。**配置属于工具，不属于系统**：
# 存在 tools.config（非敏感项）与 tools.secret_enc（密钥），在工具页按工具单独改。
# 这里的默认值只在工具行没有对应键时兜底，改了 .env 不生效——.env 只提供一份初始值。
TOOL_CONFIG_DEFAULTS: dict[str, dict] = {
    "web_search": {
        "endpoint": "https://api.wsa.cloud.tencent.com/SearchPro",
        "default_limit": 5,
        "max_limit": 10,
        "timeout": 20,
    },
    "http_request": {
        "allowed_hosts": "",
        "timeout": 20,
        "max_bytes": 200_000,
    },
}


def tool_config(name: str, config: dict | None, key: str) -> object:
    """取某个工具自己的配置项**原始值**：工具行里的值优先，没有则用 TOOL_CONFIG_DEFAULTS 兜底。

    配置随工具行走（tools.config），因此同一平台上的两个 web_search 工具可以指向
    不同的搜索服务；不是全局一份。

    返回的是未经校验的原始值：页面上存下来的是字符串，库里的历史行也可能是数字，
    键没在 TOOL_CONFIG_DEFAULTS 里声明时是 None。要参与计算一律用下面三个取用函数，
    别自己对返回值做 float() / int()——那正是配置缺失时抛 TypeError 的来源。
    """
    conf = config or {}
    if key in conf and conf[key] not in (None, ""):
        return conf[key]
    return TOOL_CONFIG_DEFAULTS.get(name, {}).get(key)


def _as_int(raw: object) -> int | None:
    """把配置里的原始值收敛成整数；转不出来返回 None，兜底交给调用处。"""
    if isinstance(raw, (int, float, str)):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


def _as_float(raw: object) -> float | None:
    """把配置里的原始值收敛成小数，语义同 _as_int。"""
    if isinstance(raw, (int, float, str)):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def tool_config_str(name: str, config: dict | None, key: str) -> str:
    """取文本配置项：工具行里的值优先，没有则用默认值（缺省是空串）。"""
    raw = tool_config(name, config, key)
    if isinstance(raw, str):
        return raw
    return "" if raw is None else str(raw)


def tool_config_int(name: str, config: dict | None, key: str) -> int:
    """取整数配置项。页面表单存下来的值是字符串（"30"），历史行里也见过数字，两种都认。

    真转不出来说明配置被写坏了：退回 TOOL_CONFIG_DEFAULTS 并留日志——调用处要的是一个
    确定的数，不该因为一处坏配置在请求路径上抛 TypeError / ValueError。
    """
    raw = tool_config(name, config, key)
    value = _as_int(raw)
    if value is not None:
        return value
    default = _as_int(tool_config(name, None, key)) or 0
    logger.warning("工具配置 %s.%s 不是整数：%r，改用默认值 %s", name, key, raw, default)
    return default


def tool_config_float(name: str, config: dict | None, key: str) -> float:
    """取小数配置项，语义同 tool_config_int。"""
    raw = tool_config(name, config, key)
    value = _as_float(raw)
    if value is not None:
        return value
    default = _as_float(tool_config(name, None, key)) or 0.0
    logger.warning("工具配置 %s.%s 不是小数：%r，改用默认值 %s", name, key, raw, default)
    return default


def _err(message: str) -> dict:
    return {"error": message}


# --------------------------------------------------------------------------- 文本

def text_stats(text: str) -> dict:
    """统计文本的字符数、词数、行数。

    中文按字计、英文按词计：单纯按空格切词对中文毫无意义（整段会算成 1 个词），
    所以分别给出 char_count（含空白）与 word_count（英文词 + 中文按字）。
    """
    if not isinstance(text, str):
        return _err("text 必须是字符串")
    if len(text) > TEXT_MAX_CHARS:
        return _err(f"文本过长（{len(text)} 字，上限 {TEXT_MAX_CHARS} 字）")

    chars_no_space = len(re.sub(r"\s", "", text))
    # 中文按字算，英文按空格切词；两者相加是"词数"最贴近直觉的近似
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    return {
        "char_count": len(text),
        "char_count_no_space": chars_no_space,
        "word_count": cjk + latin_words,
        "line_count": text.count("\n") + 1 if text else 0,
    }


# --------------------------------------------------------------------------- 随机

def random_int(min_value: int = 1, max_value: int = 100) -> dict:
    """生成 [min, max] 闭区间内的随机整数。"""
    try:
        lo, hi = int(min_value), int(max_value)
    except (TypeError, ValueError):
        return _err("min 与 max 必须是整数")
    if lo > hi:
        return _err(f"min({lo}) 不能大于 max({hi})")
    # 区间过大时 random.randint 本身没问题，但结果没意义；给个宽松上限挡住误用
    if hi - lo > 10**12:
        return _err("区间过大（上限 1e12）")
    return {"result": random.randint(lo, hi)}


def random_choice(items: str) -> dict:
    """从若干选项里随机挑一个。items 用换行或英文逗号分隔。"""
    if not isinstance(items, str) or not items.strip():
        return _err("items 不能为空，用换行或逗号分隔候选项")
    parts = [p.strip() for p in re.split(r"[\n,]", items) if p.strip()]
    if not parts:
        return _err("没有解析出任何候选项")
    if len(parts) > 1000:
        return _err(f"候选项过多（{len(parts)} 个，上限 1000）")
    return {"result": random.choice(parts)}


# --------------------------------------------------------------------------- 编码

def base64_encode(text: str) -> dict:
    """把文本按 UTF-8 编码成 base64。"""
    if not isinstance(text, str):
        return _err("text 必须是字符串")
    if len(text) > TEXT_MAX_CHARS:
        return _err(f"文本过长（上限 {TEXT_MAX_CHARS} 字）")
    return {"result": base64.b64encode(text.encode("utf-8")).decode("ascii")}


def base64_decode(encoded: str) -> dict:
    """把 base64 解回文本（按 UTF-8）。"""
    if not isinstance(encoded, str):
        return _err("encoded 必须是字符串")
    raw = re.sub(r"\s", "", encoded)
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as e:
        return _err(f"不是合法的 base64：{e}")
    try:
        return {"result": data.decode("utf-8")}
    except UnicodeDecodeError:
        # 二进制内容解不成文本：给出长度而不是抛错，模型可以据此判断"这不是文本"
        return _err(f"解码成功但内容不是 UTF-8 文本（{len(data)} 字节）")


# --------------------------------------------------------------------------- JSON

_PATH_SEG = re.compile(r"\.?([^.[\]]+)|\[(\d+)\]")


def json_query(json_text: str, path: str) -> dict:
    """按点路径从 JSON 里取值，如 data.items[0].name。

    路径语法：a.b.c 取嵌套字段，a[0] 取数组下标。空路径返回整个文档。
    """
    if not isinstance(json_text, str):
        return _err("json 必须是字符串")
    if len(json_text.encode("utf-8", errors="replace")) > JSON_MAX_BYTES:
        return _err(f"JSON 过大（上限 {JSON_MAX_BYTES // 1000} KB）")
    try:
        doc = json.loads(json_text)
    except json.JSONDecodeError as e:
        return _err(f"不是合法 JSON：{e}")

    cur = doc
    for seg, idx in _PATH_SEG.findall(path or ""):
        if idx:
            if not isinstance(cur, list):
                return _err(f"路径 {path} 在 {seg or idx} 处期望数组，实际是 {type(cur).__name__}")
            i = int(idx)
            if i >= len(cur):
                return _err(f"路径 {path} 的下标 {i} 越界（数组长度 {len(cur)}）")
            cur = cur[i]
        else:
            if not isinstance(cur, dict):
                return _err(f"路径 {path} 在 {seg} 处期望对象，实际是 {type(cur).__name__}")
            if seg not in cur:
                return _err(f"路径 {path} 的字段 {seg} 不存在，可用字段：{sorted(cur)[:20]}")
            cur = cur[seg]
    return {"result": cur}


# --------------------------------------------------------------------------- HTTP

# 内网地址段：SSRF 防护。模型能构造任意 URL，不挡的话等于给它一个打内网的口子。
_PRIVATE_NETS = [
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
              "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10")
]


def _host_allowed(host: str, allowed: str = "") -> tuple[bool, str]:
    """域名白名单 + 内网地址拦截。allowed 是这个工具自己的白名单（逗号分隔）。

    白名单为空时**只拦内网**、放行公网：让工具开箱可用。
    配了白名单则严格按白名单（支持 *.example.com 后缀通配）。
    """
    if not host:
        return False, "URL 缺少主机名"

    # 先把域名解析成 IP 再判内网：否则 http://127.0.0.1 换个域名照样能绕过去
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, f"域名无法解析：{host}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in net for net in _PRIVATE_NETS):
            return False, f"不允许访问内网地址（{host} → {ip}）"

    allow = (allowed or "").strip()
    if not allow:
        return True, ""
    patterns = [p.strip().lower() for p in allow.split(",") if p.strip()]
    h = host.lower()
    for p in patterns:
        if p == h:
            return True, ""
        if p.startswith("*.") and (h == p[2:] or h.endswith(p[1:])):
            return True, ""
    return False, f"域名不在白名单内：{host}（允许：{', '.join(patterns)}）"


async def http_request(url: str, method: str = "GET", headers: str = "", body: str = "",
                       *, config: dict | None = None) -> dict:
    """发起一次 HTTP 请求。config 是这个工具自己的配置行（tools.config）。

    headers 是 JSON 对象字符串（如 {"Accept": "application/json"}），body 是原样发送的文本。
    返回状态码、响应头与响应体；响应体超过上限会截断并标注。
    """
    if not isinstance(url, str) or not url.strip():
        return _err("url 不能为空")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return _err("只支持 http / https")
    ok, reason = _host_allowed(parts.hostname or "", tool_config_str("http_request", config, "allowed_hosts"))
    if not ok:
        logger.warning("http_request 拒绝访问：url=%r reason=%s", url[:200], reason)
        return _err(reason)

    hdrs: dict[str, str] = {}
    if headers and headers.strip():
        try:
            parsed = json.loads(headers)
        except json.JSONDecodeError:
            return _err("headers 必须是 JSON 对象字符串，如 {\"Accept\": \"application/json\"}")
        if not isinstance(parsed, dict):
            return _err("headers 必须是 JSON 对象")
        hdrs = {str(k): str(v) for k, v in parsed.items()}

    m = (method or "GET").strip().upper()
    if m not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
        return _err(f"不支持的方法：{m}")

    timeout = tool_config_float("http_request", config, "timeout")
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.request(m, url.strip(), headers=hdrs, content=body or None)
    except httpx.TimeoutException:
        return _err(f"请求超时（{timeout:.0f}s）")
    except httpx.HTTPError as e:
        logger.warning("http_request 请求失败：url=%r error=%s", url[:200], e)
        return _err(f"请求失败：{type(e).__name__}: {e}")

    max_bytes = tool_config_int("http_request", config, "max_bytes")
    raw = resp.content[:max_bytes]
    truncated = len(resp.content) > max_bytes
    try:
        text = raw.decode(resp.encoding or "utf-8", errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")
    return {
        "status": resp.status_code,
        "headers": dict(list(resp.headers.items())[:30]),
        "body": text,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------- 联网搜索

def web_search(query: str, limit: int = 0, *, config: dict | None = None, api_key: str = "") -> dict:
    """用腾讯云 SearchPro 搜索网页。config / api_key 都来自这个工具自己的行。

    协议照 wechat-ai/searchpro（POST /SearchPro，Bearer 鉴权），但不依赖那个项目。
    limit 传 0 表示用工具配置里的默认条数。
    """
    q = (query or "").strip()
    if not q:
        return _err("query 不能为空")
    if len(q) > 2000:
        return _err(f"关键词过长（{len(q)} 字，上限 2000）")

    # 地址、密钥、条数、超时全部来自这个工具自己的配置（工具页可改，下一次调用即生效）
    key = (api_key or "").strip()
    if not key:
        return _err("联网搜索未配置 API Key：去「工具」页编辑 web_search 填上，或在本机 .env 设置 SEARCHPRO_KEY 后新建工具")
    endpoint = tool_config_str("web_search", config, "endpoint").strip()
    if not endpoint:
        return _err("联网搜索未配置接口地址：去「工具」页编辑 web_search 填写")

    max_limit = tool_config_int("web_search", config, "max_limit")
    default_limit = tool_config_int("web_search", config, "default_limit")
    want = int(limit) if str(limit or "").strip() not in ("", "0") else default_limit
    n = max(1, min(want, max_limit))

    timeout = tool_config_float("web_search", config, "timeout")
    payload = {"Query": q}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
    except httpx.TimeoutException:
        return _err(f"搜索超时（{timeout:.0f}s）")
    except httpx.HTTPError as e:
        logger.warning("web_search 请求失败：query=%r error=%s", q[:80], e)
        return _err(f"搜索请求失败：{type(e).__name__}: {e}")

    if resp.status_code != 200:
        return _err(f"搜索接口返回 HTTP {resp.status_code}：{resp.text[:200]}")

    try:
        data = resp.json()
    except json.JSONDecodeError:
        return _err(f"搜索接口返回的不是 JSON：{resp.text[:200]}")

    body = data.get("Response") if isinstance(data.get("Response"), dict) else data
    err = body.get("Error")
    if isinstance(err, dict):
        return _err(f"搜索失败：{err.get('Code')} {err.get('Message')}")

    raw_pages = body.get("Pages")
    if not isinstance(raw_pages, list):
        return _err("搜索接口没有返回 Pages 字段")

    results = []
    for item in raw_pages[:n]:
        # Pages 元素历史上是"JSON 字符串套 JSON"，这里两种形态都兼容
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                continue
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "site": str(item.get("site") or ""),
            "date": str(item.get("date") or ""),
            "score": item.get("score"),
            "passage": str(item.get("passage") or "")[:500],
        })
    return {"query": q, "count": len(results), "results": results}
