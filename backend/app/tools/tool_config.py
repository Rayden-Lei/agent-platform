"""各内置工具自己的配置项声明（工具页按此生成表单）。

为什么放在这里而不是系统参数：配置属于工具。平台上可以同时存在两个 web_search
工具，一个指向腾讯云、一个指向自建服务——全局只有一份配置做不到这件事。

三类配置项：
- 普通项（endpoint / limit / timeout …）存 tools.config
- 密钥项（kind="secret"）存 tools.secret_enc（加密），任何接口不回传明文
- 参数声明（parameters）由 tools/builtin.py 提供，不在本表

格式与前端表单一一对应：kind 决定控件，min/max/step 决定数字框范围。
"""
from __future__ import annotations

from dataclasses import dataclass

KIND_STR = "str"
KIND_INT = "int"
KIND_SECRET = "secret"


@dataclass(frozen=True)
class ToolConfigField:
    key: str               # 存进 tools.config 的键名（secret 项除外）
    label: str
    description: str
    kind: str = KIND_STR
    min: float = 0
    max: float = 0
    step: float = 1
    unit: str = ""
    placeholder: str = ""
    default: object = ""


# key 是工具名（与 tools/general.py 里的实现一一对应）
TOOL_CONFIG_FIELDS: dict[str, list[ToolConfigField]] = {
    "web_search": [
        ToolConfigField(
            "endpoint", "搜索接口地址",
            "联网搜索调用的接口。默认腾讯云 SearchPro；换成自建或其它兼容服务时改这里。",
            kind=KIND_STR, placeholder="https://api.wsa.cloud.tencent.com/SearchPro",
            default="https://api.wsa.cloud.tencent.com/SearchPro",
        ),
        # secret 类型特殊：值存 secret_enc，页面上看到的是 has_secret 与掩码
        ToolConfigField(
            "api_key", "搜索 API Key",
            "联网搜索的鉴权密钥。保存后不再回显，只能覆盖或清除。",
            kind=KIND_SECRET, placeholder="sk-...",
        ),
        ToolConfigField(
            "default_limit", "默认返回条数",
            "模型没指定条数时返回几条。",
            kind=KIND_INT, min=1, max=10, default=5, unit="条",
        ),
        ToolConfigField(
            "max_limit", "最多返回条数",
            "模型显式要求更多时也不超过这个数。",
            kind=KIND_INT, min=1, max=20, default=10, unit="条",
        ),
        ToolConfigField(
            "timeout", "搜索超时",
            "单次搜索的等待上限，超时即返回错误，不重试。",
            kind=KIND_INT, min=3, max=60, default=20, unit="秒",
        ),
    ],
    "http_request": [
        ToolConfigField(
            "allowed_hosts", "目标域名白名单",
            "逗号分隔，支持 *.example.com 后缀通配。留空 = 放行所有公网域名（内网地址段始终拦死）。",
            kind=KIND_STR, placeholder="api.example.com,*.openai.com",
        ),
        ToolConfigField(
            "timeout", "请求超时",
            "单次请求的等待上限。",
            kind=KIND_INT, min=3, max=120, default=20, unit="秒",
        ),
        ToolConfigField(
            "max_bytes", "返回体上限",
            "响应体超过这个大小会被截断，避免把几十 MB 的页面塞进上下文。",
            kind=KIND_INT, min=10_000, max=2_000_000, default=200_000, unit="字节",
        ),
    ],
}
