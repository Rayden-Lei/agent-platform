"""工具参数回填迁移（`12-差距补齐开发计划.md` 2.3，FR-030）：缺声明的 HTTP 工具被回填并列入清单；已声明的不动；重复执行为空。"""
import importlib.util
import pathlib

from app.db.session import engine

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrations" / "20260905_160000_v9w0x1_tools_parameters_backfill.py"
EMPTY = {"type": "object", "properties": {}, "required": []}


def _load_script():
    spec = importlib.util.spec_from_file_location("tools_parameters_backfill", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create(client, auth_headers, name: str, config: dict) -> int:
    r = client.post("/api/v1/tools", headers=auth_headers, json={"name": name, "description": "回填测试", "type": "http", "config": config, "timeout": 5})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _config_of(client, auth_headers, tool_id: int) -> dict:
    items = client.get("/api/v1/tools", headers=auth_headers, params={"q": "pytest-backfill", "page_size": 100}).json()["items"]
    return next(i for i in items if i["id"] == tool_id)["config"]


def test_backfill_fills_missing_declaration_and_second_run_touches_nothing(client, auth_headers):
    script = _load_script()
    legacy = _create(client, auth_headers, "pytest-backfill-legacy", {"url": "http://upstream.test/x", "method": "GET"})
    declared = _create(client, auth_headers, "pytest-backfill-declared", {"url": "http://upstream.test/y", "parameters": {"properties": {"q": {"type": "string"}}}})
    builtin = client.post("/api/v1/tools", headers=auth_headers, json={"name": "pytest-backfill-builtin", "description": "x", "type": "builtin", "config": {}}).json()["id"]
    try:
        with engine.begin() as conn:
            affected = script.backfill(conn)
        ids = [tool_id for tool_id, _ in affected]
        assert (legacy, "pytest-backfill-legacy") in affected
        assert declared not in ids and builtin not in ids  # 已声明的与内置工具不在清单里
        assert _config_of(client, auth_headers, legacy) == {"url": "http://upstream.test/x", "method": "GET", "parameters": EMPTY}
        assert _config_of(client, auth_headers, declared)["parameters"]["properties"] == {"q": {"type": "string", "description": ""}}
        assert "parameters" not in _config_of(client, auth_headers, builtin)
        # 第二次执行：无事可做
        with engine.begin() as conn:
            assert script.backfill(conn) == []
    finally:
        for tool_id in (legacy, declared, builtin):
            client.delete(f"/api/v1/tools/{tool_id}", headers=auth_headers)
