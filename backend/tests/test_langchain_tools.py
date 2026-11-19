"""LangChain 工具包装（tools/langchain_tools.py）的白名单与错误回传。

为什么单独测：这些包装决定了**模型能看到什么、能调到哪里**。
- load_skill / run_skill_script 的白名单：不做限制就等于把整个对象存储变成模型的文件系统；
- 参数声明坏掉时要退化成无参数工具，而不是让整轮对话炸掉（库里可能有绕过接口写入的行）；
- 模型传错参数属于"它可以自己纠正"的输入错误，要作为工具结果回给它，不能抛异常中断这一轮。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.exceptions import BizError
from app.db.models import Tool
from app.tools import langchain_tools as lt


def _skill(name: str = "pdf", content: str = "手册正文", resources=None):
    """技能行的替身。resources 必须有：build_tools 按它判断要不要挂 run_skill_script。"""
    return SimpleNamespace(name=name, content=content, resources=resources or [])


# --------------------------------------------------------------------------- calculator

def test_calculator_tool_returns_value():
    assert lt.calculator.invoke({"expression": "(2+3)*4"}) == "20"


def test_calculator_tool_returns_error_text_not_exception():
    """算不出来时回文本而不是抛异常：异常会被 LangGraph 标成工具失败并中断这一轮，
    而表达式写错是模型能自己纠正的输入问题。"""
    got = lt.calculator.invoke({"expression": "1/0"})
    assert got.startswith("计算错误")


def test_calculator_tool_rejects_oversize():
    assert "计算错误" in lt.calculator.invoke({"expression": "9**9**9"})


# --------------------------------------------------------------------------- load_skill

def test_load_skill_returns_content_for_bound_skill():
    load = lt._build_load_skill([_skill("pdf", "PDF 手册")])
    assert load.func(name="pdf") == "PDF 手册"


def test_load_skill_rejects_unbound_name():
    """只认装配时给的这几个技能：模型编一个名字不能读到别的内容。"""
    load = lt._build_load_skill([_skill("pdf")])
    assert "技能不存在" in load.func(name="excel")


# --------------------------------------------------------------------------- run_skill_script

def _script_tool(skills=None):
    return lt._build_run_skill_script(skills or [_skill("pdf")])


def test_run_script_rejects_unbound_skill():
    run = _script_tool()
    assert "技能不存在" in run.func(skill="nope", path="a.py")


def test_run_script_parses_json_input(monkeypatch):
    seen = {}

    def _fake(s, path, payload):
        seen.update(skill=s.name, path=path, payload=payload)
        return SimpleNamespace(ok=True, output="done", stderr="", mode="bwrap")

    monkeypatch.setattr(lt.skill_resource, "run_script", _fake)
    out = _script_tool().func(skill="pdf", path="a.py", input='{"x": 1}')
    assert out == "done"
    assert seen["payload"] == {"input": {"x": 1}}


def test_run_script_treats_non_json_input_as_text(monkeypatch):
    """模型传了非 JSON 字符串：按纯文本给进去，比直接报错更有用。"""
    seen = {}

    def _fake(s, path, payload):
        seen["payload"] = payload
        return SimpleNamespace(ok=True, output="ok", stderr="", mode="bwrap")

    monkeypatch.setattr(lt.skill_resource, "run_script", _fake)
    _script_tool().func(skill="pdf", path="a.py", input="纯文本")
    assert seen["payload"] == {"input": "纯文本"}


def test_run_script_rejects_path_outside_skill(monkeypatch):
    """路径非法（不在这个技能的 resources 里）：回 JSON error 给模型，不抛异常。"""
    def _fake(s, path, payload):
        raise BizError(400, "脚本不存在：../../etc/passwd")

    monkeypatch.setattr(lt.skill_resource, "run_script", _fake)
    out = json.loads(_script_tool().func(skill="pdf", path="../../etc/passwd"))
    assert "脚本不存在" in out["error"]


def test_run_script_reports_execution_failure(monkeypatch):
    def _fake(s, path, payload):
        return SimpleNamespace(ok=False, output="", stderr="Traceback: boom", mode="bwrap", error="退出码 1")

    monkeypatch.setattr(lt.skill_resource, "run_script", _fake)
    out = json.loads(_script_tool().func(skill="pdf", path="a.py"))
    assert "退出码 1" in out["error"]
    assert "boom" in out["stderr"]


def test_run_script_empty_output_is_reported(monkeypatch):
    """脚本跑成功但一个字没输出：要说"没有输出"，不能让模型以为拿到了空结果。"""
    monkeypatch.setattr(lt.skill_resource, "run_script",
                        lambda s, p, payload: SimpleNamespace(ok=True, output="   ", stderr="", mode="bwrap"))
    out = json.loads(_script_tool().func(skill="pdf", path="a.py"))
    assert "没有输出" in out["error"]


# --------------------------------------------------------------------------- HTTP 工具包装

def _http_tool(**kw) -> Tool:
    return Tool(name=kw.get("name", "pytest-http-tool"), description="d", type="http",
                config=kw.get("config", {}), timeout=30, is_enabled=True)


def test_bad_parameter_declaration_degrades_to_no_args(monkeypatch):
    """库里参数声明坏了（绕过接口写库）：退化成无参数工具，不让一个坏工具拖垮整个对话。"""
    def _boom(config):
        raise ValidationError.from_exception_data("ToolParameters", [])

    monkeypatch.setattr(lt, "parse_parameters", _boom)
    wrapped = lt._build_http_tool(_http_tool())
    assert wrapped.name == "pytest-http-tool"
    # 无参数工具：模型只能以 {} 调用
    assert wrapped.args == {}


@pytest.mark.anyio
async def test_http_tool_filters_none_kwargs(monkeypatch):
    """LangChain 会把可选参数的默认 None 一并传进来：不过滤会变成 ?days= 这种空查询参数。"""
    seen = {}

    async def _fake(t, args, ctx=None):
        seen.update(args)
        return {"ok": True}

    monkeypatch.setattr(lt, "execute_tool", _fake)
    wrapped = lt._build_http_tool(_http_tool())
    out = await wrapped.coroutine(days=None, q="x")
    assert seen == {"q": "x"}
    assert json.loads(out) == {"ok": True}


def test_validation_error_message_is_readable():
    """参数校验失败要把字段与原因说清楚，模型才能改对。"""
    wrapped = lt._build_http_tool(_http_tool(config={
        "url": "https://example.test/x",
        "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]},
    }))
    err = wrapped.handle_validation_error
    assert err is not None
    msg = err(ValidationError.from_exception_data("x", [{"type": "missing", "loc": ("days",), "input": {}}]))
    assert "参数校验失败" in msg


# --------------------------------------------------------------------------- 装配

def test_build_tools_skips_disabled():
    """停用的工具仍绑在智能体上，但不暴露给模型：工具页的启停开关靠这里生效。"""
    disabled = _http_tool(name="pytest-disabled")
    disabled.is_enabled = False
    names = [t.name for t in lt.build_tools([disabled])]
    assert "pytest-disabled" not in names
    assert "current_time" in names and "calculator" in names


def test_build_tools_skips_unknown_builtin():
    """库里残留了已删掉的内置工具名：跳过，不让整轮装配炸掉。"""
    ghost = Tool(name="pytest-ghost-tool", description="", type="builtin", config={}, timeout=30, is_enabled=True)
    names = [t.name for t in lt.build_tools([ghost])]
    assert "pytest-ghost-tool" not in names


def test_build_tools_adds_load_skill_only_when_skills_given():
    """没绑技能时不追加 load_skill：一个永远返回「技能不存在」的工具只会诱导模型乱试。"""
    assert "load_skill" not in [t.name for t in lt.build_tools([])]
    assert "load_skill" in [t.name for t in lt.build_tools([], skills=[_skill("pdf")])]


def test_build_tools_wraps_optional_builtin():
    """能力型内置工具按名字从分发表取实现，参数声明来自 builtin.BUILTIN_PARAMETERS。"""
    t = Tool(name="text_stats", description="d", type="builtin", config={}, timeout=30, is_enabled=True)
    wrapped = {x.name: x for x in lt.build_tools([t])}["text_stats"]
    assert "text" in wrapped.args
