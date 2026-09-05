"""工具参数声明（FR-030）：`tools.config.parameters` 的 JSON Schema 子集。

三件事：声明本身的校验（ToolParameters）、按声明生成 pydantic 参数模型（build_args_model）、
调用前校验并规范化参数（validate_args / check_tool_args）。智能体对话、测试接口、工作流 tool 节点共用同一套规则。
"""
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, field_validator, model_validator

from app.db.models import Tool

PROPERTY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_PROPERTIES = 20
_PY_TYPES = {"string": str, "number": float, "integer": int, "boolean": bool}


class ToolProperty(BaseModel):
    """单个参数：只支持四种标量类型；enum 只对 string 有意义。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "number", "integer", "boolean"]
    description: str = ""
    enum: list[str] | None = None

    @model_validator(mode="after")
    def _enum_only_for_string(self) -> "ToolProperty":
        if self.enum is not None:
            if self.type != "string":
                raise ValueError("enum 只支持 string 类型的参数")
            if not self.enum:
                raise ValueError("enum 不能是空列表")
        return self


class ToolParameters(BaseModel):
    """参数声明整体：固定 object，不支持嵌套对象与数组。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["object"] = "object"
    properties: dict[str, ToolProperty] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)

    @field_validator("properties")
    @classmethod
    def _check_property_names(cls, value: dict[str, ToolProperty]) -> dict[str, ToolProperty]:
        if len(value) > MAX_PROPERTIES:
            raise ValueError(f"参数最多 {MAX_PROPERTIES} 个，当前 {len(value)} 个")
        for name in value:
            if not PROPERTY_NAME_RE.match(name):
                raise ValueError(f"参数名 {name!r} 不合法，应匹配 ^[A-Za-z_][A-Za-z0-9_]*$")
        return value

    @model_validator(mode="after")
    def _required_must_be_declared(self) -> "ToolParameters":
        unknown = [name for name in self.required if name not in self.properties]
        if unknown:
            raise ValueError(f"required 引用了未声明的参数：{', '.join(unknown)}")
        return self


def format_validation_error(exc: ValidationError) -> str:
    """把 pydantic 的错误列表压成一行"位置: 原因"，给 422 / 400 的 detail 与回给模型的工具结果用。"""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"])
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return "; ".join(parts)


def parse_parameters(config: dict | None) -> ToolParameters:
    """从 tools.config 取参数声明；未声明视为无参数工具。声明不合法抛 ValidationError。"""
    raw = (config or {}).get("parameters")
    return ToolParameters() if raw is None else ToolParameters.model_validate(raw)


def build_args_model(parameters: ToolParameters, model_name: str = "ToolArgs") -> type[BaseModel]:
    """按声明生成参数模型：必填无默认值，可选默认 None，enum 转 Literal，未声明的键一律拒绝。"""
    fields: dict[str, Any] = {}
    for name, prop in parameters.properties.items():
        py_type: Any = Literal[tuple(prop.enum)] if prop.enum else _PY_TYPES[prop.type]
        if name in parameters.required:
            fields[name] = (py_type, Field(..., description=prop.description))
        else:
            fields[name] = (py_type | None, Field(None, description=prop.description))
    return create_model(model_name, __config__=ConfigDict(extra="forbid"), **fields)


def validate_args(parameters: ToolParameters, args: dict | None) -> tuple[dict, str]:
    """校验并规范化参数（"3" → 3 这类宽松转换保留）。返回 (参数, 错误文本)，错误文本为空即通过。"""
    try:
        parsed = build_args_model(parameters).model_validate(args or {})
    except ValidationError as e:
        return {}, format_validation_error(e)
    return parsed.model_dump(exclude_none=True), ""


def check_tool_args(tool: Tool, args: dict | None) -> dict:
    """调用 HTTP 工具前按其声明校验参数，不合法抛 ValueError("参数校验失败：...")；内置工具原样放行（它们有原生签名）。"""
    if tool.type != "http":
        return args or {}
    normalized, error = validate_args(parse_parameters(tool.config), args)
    if error:
        raise ValueError(f"参数校验失败：{error}")
    return normalized
