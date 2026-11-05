"""工作流输入输出契约（docs/15 FR-077 / WF-04）：开始节点声明输入变量，结束节点声明输出。

三件事：声明的校验（start_variables / end_outputs）、运行入参的校验与宽松转换（normalize_inputs）、
state 的构造（build_initial_state）。保存、测试运行、正式运行、定时任务共用同一套规则；
引擎与调度器只认这里的结论，不再有"没声明变量就当隐式 input"的兜底（D-32 一次切换）。

变量引用统一写成 {{start.变量名}}：start 是开始节点在 state 里的约定键，
state.input 也保留同一份字典，存量图迁移后 {{input}} 仍然指向它。
"""
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.exceptions import BizError
from app.tools.schema import PROPERTY_NAME_RE, format_validation_error

MAX_VARIABLES = 20
VAR_TYPES = ("text", "number", "integer", "boolean")

# 变量名的提示口径与工具参数一致（同一个正则，避免两套规则）
VAR_NAME_HINT = "名称须以字母或下划线开头，只能含字母、数字与下划线"


class WorkflowVariable(BaseModel):
    """一个输入变量：类型只支持四种标量，可选默认值与说明。必填靠"没有默认值"表达。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["text", "number", "integer", "boolean"] = "text"
    description: str = ""
    default: Any | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        name = (value or "").strip()
        if not PROPERTY_NAME_RE.match(name):
            raise ValueError(f"变量名 {name!r} 不合法，{VAR_NAME_HINT}")
        return name

    @model_validator(mode="after")
    def _default_matches_type(self) -> "WorkflowVariable":
        if self.default is None:
            return self
        converted, error = convert_value(self.default, self.type)
        if error:
            raise ValueError(f"变量 {self.name} 的默认值不合法：{error}")
        object.__setattr__(self, "default", converted)
        return self


class WorkflowOutput(BaseModel):
    """结束节点的一个输出：name 是响应里的键，ref 是变量引用（如 {{node_x.data}}）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    ref: str

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        name = (value or "").strip()
        if not PROPERTY_NAME_RE.match(name):
            raise ValueError(f"输出名 {name!r} 不合法，{VAR_NAME_HINT}")
        return name

    @field_validator("ref")
    @classmethod
    def _check_ref(cls, value: str) -> str:
        ref = (value or "").strip()
        if not ref:
            raise ValueError("输出必须引用一个变量，如 {{node_1.data}}")
        return ref


class StartConfig(BaseModel):
    """开始节点 config：variables 为输入变量声明。"""

    model_config = ConfigDict(extra="forbid")

    variables: list[WorkflowVariable] = Field(default_factory=list)

    @field_validator("variables")
    @classmethod
    def _check_variables(cls, value: list[WorkflowVariable]) -> list[WorkflowVariable]:
        if len(value) > MAX_VARIABLES:
            raise ValueError(f"输入变量最多 {MAX_VARIABLES} 个，当前 {len(value)} 个")
        seen: set[str] = set()
        for v in value:
            if v.name in seen:
                raise ValueError(f"输入变量 {v.name} 重名")
            seen.add(v.name)
        return value


class EndConfig(BaseModel):
    """结束节点 config：outputs 为输出声明。"""

    model_config = ConfigDict(extra="forbid")

    outputs: list[WorkflowOutput] = Field(default_factory=list)

    @field_validator("outputs")
    @classmethod
    def _check_outputs(cls, value: list[WorkflowOutput]) -> list[WorkflowOutput]:
        if len(value) > MAX_VARIABLES:
            raise ValueError(f"输出最多 {MAX_VARIABLES} 个，当前 {len(value)} 个")
        seen: set[str] = set()
        for o in value:
            if o.name in seen:
                raise ValueError(f"输出 {o.name} 重名")
            seen.add(o.name)
        return value


def convert_value(value: Any, var_type: str) -> tuple[Any, str]:
    """按声明转换一个输入值（"3" → 3），返回 (值, 错误文本)。空串由调用方按未填处理。"""
    if value is None:
        return None, ""
    if var_type == "boolean":
        if isinstance(value, bool):
            return value, ""
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "是"):
            return True, ""
        if text in ("false", "0", "no", "否", ""):
            return False, ""
        return None, f"{value!r} 不是布尔值，请填 true 或 false"
    if var_type == "integer":
        try:
            return int(str(value).strip()), ""
        except (TypeError, ValueError):
            return None, f"{value!r} 不是整数"
    if var_type == "number":
        try:
            return float(str(value).strip()), ""
        except (TypeError, ValueError):
            return None, f"{value!r} 不是数字"
    return value if isinstance(value, str) else str(value), ""


def _parse_list(config: Any, model: type[BaseModel], field: str) -> list:
    """把节点 config[field] 解析成声明列表：未配置视为空；不合法抛 BizError(400)
    （图是外部输入，不能静默吞掉——库里存了坏声明时运行要明确报错）。"""
    if config is None:
        return []
    if not isinstance(config, dict):
        raise BizError(400, "节点配置必须是对象")
    items = config.get(field)
    if items is None:
        return []
    if not isinstance(items, list):
        raise BizError(400, f"节点配置 {field} 必须是数组")
    try:
        return [model.model_validate(item) for item in items]
    except ValidationError as e:
        raise BizError(400, f"节点配置 {field} 不合法：{format_validation_error(e)}")


def start_variables(graph: dict) -> list[WorkflowVariable]:
    """图里开始节点声明的输入变量（多个开始节点时按节点顺序合并；重名由保存时的图校验拦下）。"""
    result: list[WorkflowVariable] = []
    for node in (graph or {}).get("nodes") or []:
        if node.get("type") == "start":
            result.extend(_parse_list(node.get("config"), WorkflowVariable, "variables"))
    return result


def end_outputs(graph: dict) -> list[WorkflowOutput]:
    """图里结束节点声明的输出。"""
    result: list[WorkflowOutput] = []
    for node in (graph or {}).get("nodes") or []:
        if node.get("type") == "end":
            result.extend(_parse_list(node.get("config"), WorkflowOutput, "outputs"))
    return result


def normalize_inputs(variables: list[WorkflowVariable], raw: dict | None) -> dict:
    """按声明校验运行入参并宽松转换；返回 state.input。

    - 未声明的键一律拒绝（避免"以为填了其实没生效"）；
    - 没填（None 或全空白）的变量：有默认值用默认值，否则报缺少必填输入；
    - 类型不符按声明报错，不做静默猜测。
    """
    provided = raw or {}
    if not isinstance(provided, dict):
        raise BizError(400, "inputs 必须是对象")
    errors: list[str] = []
    values: dict[str, Any] = {}
    declared = {v.name for v in variables}
    unknown = [k for k in provided if k not in declared]
    if unknown:
        errors.append(f"未声明的输入变量：{', '.join(sorted(unknown))}（开始节点声明的是：{', '.join(sorted(declared)) or '无'}）")
    for var in variables:
        raw_value = provided.get(var.name)
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            if var.default is not None:
                values[var.name] = var.default
            else:
                errors.append(f"缺少必填输入 {var.name}")
            continue
        converted, error = convert_value(raw_value, var.type)
        if error:
            errors.append(f"{var.name}: {error}")
            continue
        values[var.name] = converted
    if errors:
        raise BizError(400, "输入校验失败：" + "；".join(errors))
    return values


def main_input(values: dict) -> Any:
    """主输入：条件表达式与代码节点里的 input 变量指向它。

    规则写在这一处，避免各处各猜一套：
    - 声明里有一个名叫 input 的变量 → 取它（最常见，也是存量图的语义）；
    - 只有这一个变量 → 取它（单输入工作流不用再记别的规则）；
    - 其余（0 个，或多个却没有 input）→ 整个字典，节点用 {{start.变量名}} 取具体值。

    保留"主输入"这个概念的原因：{{input}}、条件表达式里的 input、代码节点里的 input 三处
    都是围绕"这个工作流的主要输入"写的，统一指到同一个值，存量图与新增声明才能同时成立。
    """
    if "input" in values:
        return values["input"]
    if len(values) == 1:
        return next(iter(values.values()))
    return values


def build_initial_state(graph: dict, raw_inputs: dict | None) -> dict:
    """首跑的初始 state：按开始节点声明校验入参。

    - input：主输入（见 main_input），条件表达式与代码节点的 input 指它；
    - vars：声明的全部变量，运行时取值用；
    - node_outputs.start：同一份变量字典，让 {{start.变量名}} 走 _resolve_ref 的通用路径。
    """
    values = normalize_inputs(start_variables(graph), raw_inputs)
    return {"input": main_input(values), "vars": values, "node_outputs": {"start": values}, "steps": []}
