"""内置工具的参数声明（FR-030 的补充，2026-11-05）。

HTTP 工具的参数声明原本由人在工具页填在 tools.config.parameters 里；内置工具是代码写死的，
没有声明，于是工具页的在线测试退化成"手写 JSON 框"，工作流的工具节点也无从生成输入项。
这里把内置工具的声明也列出来，由 tool_service 在对外序列化时一并返回（不落库，避免和代码不一致），
于是三种工具类型共用同一套"按声明生成表单"的路径。

声明格式与 tools/schema.ToolParameters 一致（JSON Schema 子集：只支持标量、无嵌套）。
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
}
