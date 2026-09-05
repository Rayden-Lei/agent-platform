"""Prompt 模板渲染（FR-028）：纯字符串替换，两个纯函数。

不引入 Jinja 之类的模板引擎：避免表达式能力带来的注入面，也让"模板里写了什么就渲染什么"可预期。
占位符形如 {{name}}，name 匹配 ^[A-Za-z_][A-Za-z0-9_]*$；不支持转义字面量 {{。
"""
import re
from dataclasses import dataclass, field

VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


@dataclass
class RenderResult:
    text: str
    missing: list[str] = field(default_factory=list)  # 必填且既没传值也没有默认值的变量
    unused: list[str] = field(default_factory=list)  # 声明了但内容里没引用的变量


def extract_variables(content: str) -> set[str]:
    """内容里引用到的变量名集合。"""
    return set(_PLACEHOLDER_RE.findall(content or ""))


def _has_value(value) -> bool:
    return value is not None and value != ""


def render(content: str, declared: list[dict], values: dict | None) -> RenderResult:
    """按声明渲染：传了值用值，否则用默认值；必填且两者皆无 → 记入 missing（文本里保留占位符不替换）。

    declared 每项 {name, description, required, default}；values 里未声明的键忽略。
    调用方决定 missing 非空时是报 400 还是照常使用文本。
    """
    values = values or {}
    referenced = extract_variables(content)
    resolved: dict[str, str] = {}
    missing: list[str] = []
    unused: list[str] = []
    for item in declared or []:
        name = item.get("name")
        if not name:
            continue
        if name not in referenced:
            unused.append(name)
        value = values.get(name)
        if not _has_value(value):
            value = item.get("default")
        if _has_value(value):
            resolved[name] = str(value)
        elif item.get("required"):
            missing.append(name)

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        return resolved[name] if name in resolved else match.group(0)

    return RenderResult(text=_PLACEHOLDER_RE.sub(_replace, content or ""), missing=missing, unused=unused)
