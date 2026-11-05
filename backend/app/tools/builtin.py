"""内置工具的参数声明（FR-030 的补充，2026-11-05）。

HTTP 工具的参数声明原本由人在工具页填在 tools.config.parameters 里；内置工具是代码写死的，
没有声明，于是工具页的在线测试退化成"手写 JSON 框"，工作流的工具节点也无从生成输入项。
这里把内置工具的声明也列出来，由 tool_service 在对外序列化时一并返回（不落库，避免和代码不一致），
于是三种工具类型共用同一套"按声明生成表单"的路径。

声明格式与 tools/schema.ToolParameters 一致（JSON Schema 子集：只支持标量、无嵌套）。

分组：
- BASIC：每个智能体无条件挂上（current_time / calculator），不加进"工具页"的开关列表
- OPTIONAL：能力型工具，按需挂载（tools/general.py 实现），工具页可勾选
"""

# 键是内置工具的 name（与 tools/executor._execute_builtin 的分支一一对应）
BUILTIN_PARAMETERS: dict[str, dict] = {
    "calculator": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "算式，支持数字与 + - * / ** ，如 (2+3)*4",
            },
        },
        "required": ["expression"],
    },
    # 取当前时间不需要参数：声明成空对象，前端据此显示"该工具不需要参数"而不是 JSON 框
    "current_time": {"type": "object", "properties": {}, "required": []},

    # ---- 能力型工具（tools/general.py）----
    "text_stats": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要统计的文本"},
        },
        "required": ["text"],
    },
    "random_int": {
        "type": "object",
        "properties": {
            "min_value": {"type": "integer", "description": "下界（含），默认 1"},
            "max_value": {"type": "integer", "description": "上界（含），默认 100"},
        },
        "required": [],
    },
    "random_choice": {
        "type": "object",
        "properties": {
            "items": {"type": "string", "description": "候选项，用换行或英文逗号分隔"},
        },
        "required": ["items"],
    },
    "base64_encode": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要编码的文本"}},
        "required": ["text"],
    },
    "base64_decode": {
        "type": "object",
        "properties": {"encoded": {"type": "string", "description": "要解码的 base64 文本"}},
        "required": ["encoded"],
    },
    "json_query": {
        "type": "object",
        "properties": {
            "json_text": {"type": "string", "description": "JSON 文档字符串"},
            "path": {"type": "string", "description": "点路径，如 data.items[0].name；留空取整个文档"},
        },
        "required": ["json_text"],
    },
    "http_request": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整地址，仅支持 http / https"},
            "method": {"type": "string", "description": "GET / POST / PUT / DELETE / PATCH / HEAD，默认 GET"},
            "headers": {"type": "string", "description": "请求头的 JSON 对象字符串，可空"},
            "body": {"type": "string", "description": "请求体原文，可空"},
        },
        "required": ["url"],
    },
    "web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "返回条数，1-10，默认 5"},
        },
        "required": ["query"],
    },
}

# 能力型工具：工具页里可以勾选挂到智能体上的那些（BASIC 的两个不在其中）
OPTIONAL_BUILTIN_TOOLS: tuple[str, ...] = (
    "text_stats", "random_int", "random_choice", "base64_encode", "base64_decode",
    "json_query", "http_request", "web_search",
)
