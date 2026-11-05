"""技能资源与脚本执行（docs/17 §4.5，P2.6）：白名单、路径穿越、大小上限、沙箱执行。

负向优先。对象存储一律打桩（本机没起 MinIO），只验证"该调的调了、不该调的没调"；
脚本执行走真实沙箱（basic 模式，本机可跑），验证结果与限额真的生效。
"""
import json
import uuid

import pytest

from app.db.models import Skill
from app.db.session import SessionLocal
from app.services import skill_resource
from app.tools.langchain_tools import build_tools


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def stored(monkeypatch):
    """MinIO 打桩：记下写了什么、删了什么，读的时候从内存里取。"""
    files: dict[str, bytes] = {}
    calls: list[tuple] = []

    def _upload(name, data, ctype):
        files[name] = data
        calls.append(("upload", name, len(data)))

    def _remove(name):
        files.pop(name, None)
        calls.append(("remove", name))

    def _read(name, limit=None):
        if name not in files:
            raise ValueError(f"对象 {name} 不存在")
        data = files[name]
        if limit is not None and len(data) > limit:
            raise ValueError(f"对象 {name} 超过上限 {limit} 字节")
        return data

    def _stat(name):
        return {"size": len(files[name]), "content_type": "text/plain"} if name in files else None

    monkeypatch.setattr(skill_resource.minio_client, "upload_file", _upload)
    monkeypatch.setattr(skill_resource.minio_client, "remove_object", _remove)
    monkeypatch.setattr(skill_resource.minio_client, "read_bytes", _read)
    monkeypatch.setattr(skill_resource.minio_client, "stat_object", _stat)
    return {"files": files, "calls": calls}


@pytest.fixture
def make_skill(client, auth_headers, stored):
    """造技能，结束时删掉。

    **依赖 stored**：删技能会连带清对象存储里的资源（skill_service.delete_skill → drop_all）。
    不声明这个依赖时，stored 会先于本 fixture 拆掉，teardown 里的删除就打到真 MinIO 上，
    每个用例白等 5 秒连接超时再报 urllib3 错误 —— 2026-11-05 踩过。
    """
    created: list[int] = []

    def _make(**changes) -> dict:
        body = {"name": "pytest-res-" + _uid(), "display_name": "资源测试", "description": "测试用",
                "content": "正文", "always_on": False, "is_enabled": True}
        body.update(changes)
        r = client.post("/api/v1/skills", headers=auth_headers, json=body)
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
        return r.json()

    yield _make
    for sid in created:
        client.delete(f"/api/v1/skills/{sid}", headers=auth_headers)


ADD_SCRIPT = b'''
import json, sys
p = json.loads(sys.stdin.read() or "{}")
inp = p.get("input") or {}
print(json.dumps({"sum": inp.get("a", 0) + inp.get("b", 0)}))
'''


def _upload(client, auth_headers, skill_id: int, name: str, data: bytes):
    return client.post(f"/api/v1/skills/{skill_id}/resources", headers=auth_headers,
                       files={"file": (name, data, "text/x-python")})


def test_upload_script_and_run(client, auth_headers, make_skill, stored):
    """上传脚本 → 装配出 run_skill_script → 执行拿到结果。"""
    s = make_skill()
    r = _upload(client, auth_headers, s["id"], "add.py", ADD_SCRIPT)
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["name"] == "add.py" and entry["type"] == "file" and entry["size"] == len(ADD_SCRIPT)
    assert entry["object"] == f"skills/{s['id']}/add.py"

    db = SessionLocal()
    try:
        tools = build_tools([], skills=[db.get(Skill, s["id"])])
        assert "run_skill_script" in [t.name for t in tools]
        out = next(t for t in tools if t.name == "run_skill_script").invoke(
            {"skill": s["name"], "path": "add.py", "input": '{"a": 3, "b": 4}'})
        assert json.loads(out) == {"sum": 7}
    finally:
        db.close()


def test_no_script_no_tool(client, auth_headers, make_skill, stored):
    """没有登记 .py 资源的技能不暴露执行工具：一个永远返回「脚本不存在」的工具只会诱导模型乱试。"""
    s = make_skill()
    db = SessionLocal()
    try:
        names = [t.name for t in build_tools([], skills=[db.get(Skill, s["id"])])]
        assert "load_skill" in names and "run_skill_script" not in names
    finally:
        db.close()


def test_reject_non_python_resource(client, auth_headers, make_skill, stored):
    """首版只跑 Python：沙箱按 python 起进程，收 .sh 等于给了一个没按 shell 加固的口子。"""
    s = make_skill()
    r = _upload(client, auth_headers, s["id"], "run.sh", b"echo hi")
    assert r.status_code == 400, r.text
    assert ".py" in r.json()["detail"]


def test_reject_path_traversal_resource_name(client, auth_headers, make_skill, stored):
    """资源名会被拼进对象名，允许 .. 就等于让模型读到别的技能的资源。"""
    s = make_skill()
    for bad in ("../evil.py", "a/../../evil.py", "/abs/evil.py"):
        r = _upload(client, auth_headers, s["id"], bad, ADD_SCRIPT)
        assert r.status_code in (400, 422), f"{bad} 应被拒，实际 {r.status_code}"


def test_resource_size_limit(client, auth_headers, make_skill, stored):
    s = make_skill()
    big = b"x" * (skill_resource.RESOURCE_MAX_BYTES + 1)
    r = _upload(client, auth_headers, s["id"], "big.py", big)
    assert r.status_code == 413, r.text


def test_run_unregistered_path_404(client, auth_headers, make_skill, stored):
    """越权负向：脚本路径必须在该技能的 resources 里，别处的路径拿不到。"""
    s = make_skill()
    _upload(client, auth_headers, s["id"], "add.py", ADD_SCRIPT)
    db = SessionLocal()
    try:
        tool = next(t for t in build_tools([], skills=[db.get(Skill, s["id"])]) if t.name == "run_skill_script")
        out = tool.invoke({"skill": s["name"], "path": "../other/add.py", "input": ""})
        # 路径穿越在进白名单查找之前就被资源名校验拦住，报"资源名不合法"；
        # 换成同目录下不存在的文件名则报"脚本不存在"。两种都必须拒绝，且都不能读到别的技能。
        assert "不合法" in out or "脚本不存在" in out
        missing = tool.invoke({"skill": s["name"], "path": "not-there.py", "input": ""})
        assert "脚本不存在" in missing
    finally:
        db.close()


def test_run_unbound_skill_rejected(client, auth_headers, make_skill, stored):
    """越权负向：传一个没装配进来的技能名。"""
    s = make_skill()
    _upload(client, auth_headers, s["id"], "add.py", ADD_SCRIPT)
    other = make_skill(name="pytest-other-" + _uid())
    db = SessionLocal()
    try:
        tool = next(t for t in build_tools([], skills=[db.get(Skill, other["id"])]) if t.name == "run_skill_script") \
            if any(r.get("name", "").endswith(".py") for r in (db.get(Skill, other["id"]).resources or [])) else None
        assert tool is None, "另一个技能没脚本，不该有执行工具"
        # 用绑定了脚本的那个技能装配，然后传别的技能名
        tool2 = next(t for t in build_tools([], skills=[db.get(Skill, s["id"])]) if t.name == "run_skill_script")
        assert "技能不存在" in tool2.invoke({"skill": other["name"], "path": "add.py", "input": ""})
    finally:
        db.close()


def test_delete_resource_removes_object(client, auth_headers, make_skill, stored):
    s = make_skill()
    _upload(client, auth_headers, s["id"], "add.py", ADD_SCRIPT)
    obj = f"skills/{s['id']}/add.py"
    assert obj in stored["files"]
    r = client.delete(f"/api/v1/skills/{s['id']}/resources/add.py", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert obj not in stored["files"], "删资源要连对象一起删，否则桶里留垃圾"
    assert ("remove", obj) in stored["calls"]


def test_upload_same_name_overwrites(client, auth_headers, make_skill, stored):
    """同名上传是覆盖（技能页改脚本就是这个动作），不是追加两条。"""
    s = make_skill()
    _upload(client, auth_headers, s["id"], "add.py", ADD_SCRIPT)
    _upload(client, auth_headers, s["id"], "add.py", b'print("new")')
    detail = client.get(f"/api/v1/skills/{s['id']}", headers=auth_headers).json()
    assert len(detail["resources"]) == 1


def test_delete_skill_cleans_objects(client, auth_headers, make_skill, stored):
    """删技能要把它的资源对象一起清掉：库里删行不会连带删 MinIO 对象，不清就是永久垃圾。"""
    s = make_skill()
    _upload(client, auth_headers, s["id"], "add.py", ADD_SCRIPT)
    obj = f"skills/{s['id']}/add.py"
    assert obj in stored["files"]
    assert client.delete(f"/api/v1/skills/{s['id']}", headers=auth_headers).status_code == 200
    assert obj not in stored["files"]


def test_list_resources_marks_missing(client, auth_headers, make_skill, stored):
    """对象被外部删掉时列表要标出来，不能假装还在。"""
    s = make_skill()
    _upload(client, auth_headers, s["id"], "add.py", ADD_SCRIPT)
    stored["files"].clear()
    items = client.get(f"/api/v1/skills/{s['id']}/resources", headers=auth_headers).json()
    assert items[0]["missing"] is True and items[0]["size"] is None


def test_script_error_returned_to_model(client, auth_headers, make_skill, stored):
    """脚本报错要以结构化错误回给模型（它自己纠正），不是让整个对话挂掉。"""
    s = make_skill()
    _upload(client, auth_headers, s["id"], "boom.py", b"raise ValueError('boom-in-script')")
    db = SessionLocal()
    try:
        tool = next(t for t in build_tools([], skills=[db.get(Skill, s["id"])]) if t.name == "run_skill_script")
        out = json.loads(tool.invoke({"skill": s["name"], "path": "boom.py", "input": ""}))
        assert "boom-in-script" in out["error"]
    finally:
        db.close()


def test_script_cannot_read_host_env(client, auth_headers, make_skill, stored):
    """脚本同样在沙箱里跑：进程环境里的密钥拿不到。"""
    s = make_skill()
    _upload(client, auth_headers, s["id"], "env.py", b'''
import json, os
print(json.dumps({"db": os.environ.get("DATABASE_URL"), "aes": os.environ.get("AES_KEY")}))
''')
    db = SessionLocal()
    try:
        tool = next(t for t in build_tools([], skills=[db.get(Skill, s["id"])]) if t.name == "run_skill_script")
        out = json.loads(tool.invoke({"skill": s["name"], "path": "env.py", "input": ""}))
        assert out == {"db": None, "aes": None}
    finally:
        db.close()
