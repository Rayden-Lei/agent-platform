"""工具参数 schema（`12-差距补齐开发计划.md` 2.2，FR-030）：声明校验（422）、参数模型、测试接口 400、LangChain 工具暴露、工作流节点。

外部 HTTP 一律不发：monkeypatch executor._execute_http 计数。
"""
import asyncio

import pytest
from pydantic import ValidationError

from app.tools import executor, langchain_tools
from app.tools.langchain_tools import build_tools
from app.tools.schema import ToolParameters, build_args_model, validate_args

WEATHER = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "description": "城市名", "enum": ["北京", "上海"]},
        "days": {"type": "integer", "description": "预报天数"},
        "detail": {"type": "boolean"},
    },
    "required": ["city"],
}


def _http_tool_payload(name: str, parameters: dict | None) -> dict:
    config = {"url": "http://upstream.test/weather", "method": "GET"}
    if parameters is not None:
        config["parameters"] = parameters
    return {"name": name, "description": "天气查询", "type": "http", "config": config, "timeout": 5}


@pytest.fixture
def http_calls(monkeypatch):
    """替换真实 HTTP 调用：记录收到的参数并返回固定结果。"""
    calls: list = []

    async def _fake(tool, args):
        calls.append(args)
        return {"result": "ok", "echo": args}

    monkeypatch.setattr(executor, "_execute_http", _fake)
    monkeypatch.setattr(langchain_tools, "_execute_http", _fake)  # 该模块在 import 时就绑定了引用
    return calls


@pytest.fixture
def make_tool(client, auth_headers):
    created: list[int] = []

    def _make(name: str, parameters: dict | None) -> dict:
        r = client.post("/api/v1/tools", headers=auth_headers, json=_http_tool_payload(name, parameters))
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
        return r.json()

    yield _make
    for tid in created:
        client.delete(f"/api/v1/tools/{tid}", headers=auth_headers)


# ---------- 声明校验（schema 层，422） ----------

@pytest.mark.parametrize("parameters, fragment", [
    ({"type": "object", "properties": {"tags": {"type": "array"}}}, "tags.type"),
    ({"type": "object", "properties": {"city": {"type": "string"}}, "required": ["x"]}, "required 引用了未声明的参数：x"),
    ({"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(21)}}, "参数最多 20 个"),
    ({"type": "object", "properties": {"1abc": {"type": "string"}}}, "参数名 '1abc' 不合法"),
    ({"type": "object", "properties": {"n": {"type": "integer", "enum": ["1"]}}}, "enum 只支持 string"),
    ({"type": "array", "properties": {}}, "type"),
], ids=["array类型", "required引用未声明", "超过20个", "参数名不合法", "enum用于非string", "顶层非object"])
def test_invalid_parameters_declaration_returns_422(client, auth_headers, parameters, fragment):
    r = client.post("/api/v1/tools", headers=auth_headers, json=_http_tool_payload("pytest-bad-schema", parameters))
    assert r.status_code == 422, r.text
    err = r.json()["detail"][0]
    assert err["loc"] == ["body", "config"]
    assert "config.parameters 不合法" in err["msg"] and fragment in err["msg"]


def test_valid_declaration_is_normalized_on_save(make_tool):
    t = make_tool("pytest-schema-normalized", {"properties": {"city": {"type": "string"}}})
    assert t["config"]["parameters"] == {"type": "object", "properties": {"city": {"type": "string", "description": ""}}, "required": []}


# ---------- 参数模型 ----------

def test_args_model_validates_and_coerces():
    params = ToolParameters.model_validate(WEATHER)
    args, error = validate_args(params, {"city": "北京", "days": "3"})
    assert error == "" and args == {"city": "北京", "days": 3}  # 宽松转换保留，可选未传的不出现
    schema = build_args_model(params).model_json_schema()
    assert set(schema["properties"]) == {"city", "days", "detail"} and schema["required"] == ["city"]


@pytest.mark.parametrize("args, fragment", [
    ({}, "city"),
    ({"city": "北京", "days": "三"}, "days"),
    ({"city": "广州"}, "city"),
    ({"city": "北京", "extra": 1}, "extra"),
], ids=["缺必填", "integer给中文", "枚举外", "未声明的键"])
def test_args_model_rejects_bad_args(args, fragment):
    _, error = validate_args(ToolParameters.model_validate(WEATHER), args)
    assert fragment in error


def test_parameters_model_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        ToolParameters.model_validate({"type": "object", "properties": {}, "additionalProperties": False})


# ---------- 测试接口 ----------

def test_test_call_missing_required_returns_400_without_request(client, auth_headers, make_tool, http_calls):
    t = make_tool("pytest-schema-test400", WEATHER)
    r = client.post(f"/api/v1/tools/{t['id']}/test", headers=auth_headers, json={"args": {"days": 1}})
    assert r.status_code == 400, r.text
    assert r.json()["detail"].startswith("参数校验失败：") and "city" in r.json()["detail"]
    assert http_calls == []


def test_test_call_with_valid_args_passes_normalized_args(client, auth_headers, make_tool, http_calls):
    t = make_tool("pytest-schema-test200", WEATHER)
    r = client.post(f"/api/v1/tools/{t['id']}/test", headers=auth_headers, json={"args": {"city": "上海", "days": "2"}})
    assert r.status_code == 200, r.text
    assert http_calls == [{"city": "上海", "days": 2}]


def test_tool_without_parameters_accepts_only_empty_args(client, auth_headers, make_tool, http_calls):
    t = make_tool("pytest-schema-noargs", None)
    ok = client.post(f"/api/v1/tools/{t['id']}/test", headers=auth_headers, json={"args": {}})
    assert ok.status_code == 200, ok.text and http_calls == [{}]
    bad = client.post(f"/api/v1/tools/{t['id']}/test", headers=auth_headers, json={"args": {"q": "x"}})
    assert bad.status_code == 400 and "q" in bad.json()["detail"]
    assert len(http_calls) == 1


# ---------- LangChain 暴露 ----------

def test_langchain_tool_exposes_schema_and_returns_validation_error_as_text(make_tool, http_calls, caplog):
    from app.db.models import Tool
    from app.db.session import SessionLocal

    t = make_tool("pytest_schema_lc", WEATHER)
    db = SessionLocal()
    try:
        tool_db = db.get(Tool, t["id"])
        lc_tool = build_tools([tool_db])[-1]
    finally:
        db.close()
    assert lc_tool.name == "pytest_schema_lc"
    assert set(lc_tool.args) == {"city", "days", "detail"}
    # 不符合声明：返回错误文本让模型纠正，不抛异常、不发请求
    text = asyncio.run(lc_tool.ainvoke({"city": "北京", "days": "三"}))
    assert text.startswith("参数校验失败：") and "days" in text
    assert http_calls == []
    assert any("不符合声明的参数" in r.getMessage() for r in caplog.records)
    # 符合声明：结构化参数直接交给 HTTP 执行
    out = asyncio.run(lc_tool.ainvoke({"city": "北京", "days": 3}))
    assert '"echo": {"city": "北京", "days": 3}' in out
    assert http_calls == [{"city": "北京", "days": 3}]


def test_langchain_tool_without_parameters_has_no_args(make_tool):
    from app.db.models import Tool
    from app.db.session import SessionLocal

    t = make_tool("pytest_schema_lc_noargs", None)
    db = SessionLocal()
    try:
        lc_tool = build_tools([db.get(Tool, t["id"])])[-1]
    finally:
        db.close()
    assert lc_tool.args == {}


# ---------- 工作流 tool 节点 ----------

def test_workflow_tool_node_with_invalid_fixed_args_fails(client, auth_headers, make_tool, http_calls):
    t = make_tool("pytest-schema-wf", WEATHER)
    graph = {
        "nodes": [
            {"id": "s", "type": "start", "config": {}},
            {"id": "t", "type": "tool", "config": {"tool_name": t["name"], "args": {"days": "三"}}},
            {"id": "e", "type": "end", "config": {}},
        ],
        "edges": [{"from": "s", "to": "t"}, {"from": "t", "to": "e"}],
    }
    wf = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "pytest-schema-wf", "description": "", "graph": graph})
    assert wf.status_code == 200, wf.text
    try:
        r = client.post(f"/api/v1/workflows/{wf.json()['id']}/run", headers=auth_headers, json={"input": "x"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"
        assert "参数校验失败" in r.json()["error"] and "city" in r.json()["error"]
        assert http_calls == []
    finally:
        client.delete(f"/api/v1/workflows/{wf.json()['id']}", headers=auth_headers)
