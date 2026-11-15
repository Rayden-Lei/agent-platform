"""认证与鉴权边界：口令长度（bcrypt 72 字节）、API Key 工作流作用域、会话活跃排序。

三处都是 2026-11-14 审计发现的问题：超长中文口令 500 且绕过失败计数、
`/workflows/{id}/parameters` 漏作用域校验（IDOR）、发消息不刷新会话 updated_at 导致排序失效。
"""
from __future__ import annotations

import uuid

from app.db.models import Conversation
from app.db.session import SessionLocal
from tests.conftest import publish_workflow


def _uid() -> str:
    return uuid.uuid4().hex[:6]


# ===== 口令长度：bcrypt 72 字节 =====

def test_long_multibyte_password_is_422_not_500(client, auth_headers):
    """43 个汉字就超过 72 字节。bcrypt 5 会抛 ValueError，必须转成 422 而不是 500。

    改造前直接调 bcrypt.hashpw，异常穿透到通用异常处理 → 500，
    而且用户没被创建、管理员看不出原因。
    """
    long_pw = "中" * 30  # 90 字节
    r = client.post("/api/v1/users", headers=auth_headers, json={
        "username": "pytest-longpw-" + _uid(), "password": long_pw, "role": "caller",
    })
    assert r.status_code == 422, r.text
    assert "口令过长" in r.text or "72" in r.text


def test_password_at_72_byte_boundary_is_accepted(client, auth_headers):
    """边界值：正好 72 字节必须能用（不能把上限写成 < 72）。"""
    username = "pytest-edgepw-" + _uid()
    pw = "a" * 72
    r = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": pw, "role": "caller"})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    try:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": pw})
        assert login.status_code == 200, login.text
    finally:
        client.delete(f"/api/v1/users/{uid}", headers=auth_headers)


def test_login_with_overlong_password_counts_as_failure_not_error(client, auth_headers):
    """登录时超长口令必须按"密码错误"处理并累加失败计数，不能抛 500 绕过锁定。

    改造前 verify_password 抛 ValueError，auth_service 走不到 _incr_fail，
    于是暴力尝试既不锁定、也在错误监控里制造 500 噪音。
    """
    username = "pytest-loginlong-" + _uid()
    created = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "Short-Passw0rd", "role": "caller"})
    assert created.status_code == 200, created.text
    uid = created.json()["id"]
    try:
        r = client.post("/api/v1/auth/login", json={"username": username, "password": "中" * 30})
        # 422（被字段校验挡）或 401（按密码错误处理）都可接受，但绝不能是 500
        assert r.status_code in (401, 422), r.text
        assert r.status_code != 500
    finally:
        client.delete(f"/api/v1/users/{uid}", headers=auth_headers)


# ===== API Key 工作流作用域 =====

def test_workflow_parameters_requires_scope_for_api_key(client, auth_headers):
    """只有 A 作用域的 Key 不能读 B 的输入输出声明（2026-11-14 审计的横向越权）。"""
    graph = {"nodes": [
        {"id": "s", "type": "start", "config": {"variables": [{"name": "input", "type": "text", "description": ""}]}},
        {"id": "e", "type": "end", "config": {}},
    ], "edges": [{"from": "s", "to": "e"}]}
    made = {}
    try:
        for key in ("a", "b"):
            wf = client.post("/api/v1/workflows", headers=auth_headers, json={
                "name": f"pytest-scope-wf-{key}-" + _uid(), "description": "", "graph": graph,
            })
            assert wf.status_code == 200, wf.text
            made[key] = wf.json()["id"]
            # 参数声明读线上版本（FR-075）：未发布 403「工作流未发布」，
            # 那样就分不清 403 是"未发布"还是"不在作用域"了，所以先发布
            publish_workflow(client, auth_headers, made[key])

        # 只授权给 A 的 Key
        created = client.post("/api/v1/api-keys", headers=auth_headers, json={
            "name": "pytest-scope-key-" + _uid(),
            "workflow_ids": [made["a"]],
        })
        assert created.status_code == 200, created.text
        raw_key = created.json()["key"]
        key_id = created.json()["id"]
        headers = {"Authorization": "Bearer " + raw_key}
        try:
            # A 在作用域内：能读
            ok = client.get(f"/api/v1/workflows/{made["a"]}/parameters", headers=headers)
            assert ok.status_code == 200, ok.text
            # B 不在作用域内：403（与 run / resume 同一口径）
            denied = client.get(f"/api/v1/workflows/{made["b"]}/parameters", headers=headers)
            assert denied.status_code == 403, denied.text
        finally:
            client.delete(f"/api/v1/api-keys/{key_id}", headers=auth_headers)
    finally:
        for wid in made.values():
            client.delete(f"/api/v1/workflows/{wid}", headers=auth_headers)


# ===== 会话活跃排序 =====

def test_sending_message_bumps_conversation_updated_at(client, auth_headers, embedding_model):
    """发消息要刷新会话的 updated_at，否则「最近活跃在前」退化成「创建顺序」（静默排序错）。

    这里直接查库断言时间变了 —— 只断言接口 200 测不出这个问题。
    """
    from app.config import settings
    from app.db.models import Conversation, Run
    from app.services import chat_turn
    from app.services.conversation_service import Caller

    model = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-sort-model-" + _uid(), "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {},
    }).json()
    conv_id = None
    try:
        db = SessionLocal()
        try:
            caller = Caller("ui", client.get("/api/v1/auth/me", headers=auth_headers).json()["id"])
            turn, replay = chat_turn.open_turn(
                db, caller, "model", model["id"], "第一条",
                missing_detail="模型不存在", run_type="chat", input_data={"message": "第一条"}, model_id=model["id"],
            )
            assert turn is not None and replay is None
            conv_id = turn.conversation_id
            db.expire_all()
            first = db.get(Conversation, conv_id).updated_at
        finally:
            db.close()

        db = SessionLocal()
        try:
            caller = Caller("ui", client.get("/api/v1/auth/me", headers=auth_headers).json()["id"])
            chat_turn.open_turn(
                db, caller, "model", model["id"], "第二条", conversation_id=conv_id,
                missing_detail="模型不存在", run_type="chat", input_data={"message": "第二条"}, model_id=model["id"],
            )
            db.expire_all()
            second = db.get(Conversation, conv_id).updated_at
        finally:
            db.close()

        assert second > first, f"发消息后 updated_at 未前进：{first} -> {second}"
    finally:
        if conv_id:
            db = SessionLocal()
            try:
                db.query(Run).filter(Run.conversation_id == conv_id).delete(synchronize_session=False)
                db.query(Conversation).filter(Conversation.id == conv_id).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()
        client.delete(f"/api/v1/models/{model["id"]}", headers=auth_headers)
