"""分享体验链接（docs/15 3.6，PB-01，AC-026）：管理接口、访客令牌校验、访客口径、限额、归属与访问方式。
模型换成桩，检索的查询向量打桩，其余链路（建会话、运行记录、两道检索闸门、事件裁剪）走真实代码。
"""
import asyncio
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.core import rate_limiter
from app.core.security import create_guest_token
from app.db.models import AgentShare, AuditLog, Conversation, Document, DocumentChunk, Message, Run
from app.db.session import SessionLocal
from app.rag import retriever
from app.services import chat_service, share_service
from tests.fakes import FAKE_MODEL, AnswerModel

CONTENT = "智枢差旅标准：一线城市住宿每晚不超过六百元"
QUERY = "差旅标准"
LEAKS = ("system_prompt", "run_id", "usage", "kb_id", "chunk_id", "score", "arguments", "token_usage")


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _share_path(agent_id: int) -> str:
    return f"/api/v1/agents/{agent_id}/share"


def _pub(code: str, tail: str = "") -> str:
    return f"/api/v1/public/shares/{code}{tail}"


def _config(**over) -> dict:
    return {"is_enabled": True, "access_mode": "public", "expires_at": None, "rate_limit_per_minute": 20, "daily_message_limit": 1000,
            "visitor_daily_limit": 50, "allow_http_tools": False, "show_citations": True, **over}


def _events(resp) -> list[dict]:
    return [json.loads(p[6:]) for p in resp.text.split("\n\n") if p.startswith("data: ")]


@pytest.fixture
def made(client, auth_headers):
    """登记本用例建的对象，结束时按 Key → 智能体（分享随之级联删除）→ 知识库 → 模型 → 用户的顺序删掉。"""
    bag = {"keys": [], "agents": [], "kbs": [], "models": [], "users": []}
    yield bag
    for kind, path in (("keys", "/api/v1/api-keys"), ("agents", "/api/v1/agents"), ("kbs", "/api/v1/knowledge-bases"),
                       ("models", "/api/v1/models"), ("users", "/api/v1/users")):
        for oid in bag[kind]:
            client.delete(f"{path}/{oid}", headers=auth_headers)


@pytest.fixture
def stub(monkeypatch):
    """模型换成桩、查询向量打桩、重排走词法；记下每次构建对话上下文的入参（检索角色、HTTP 工具开关）。"""
    monkeypatch.setattr(chat_service, "build_llm", lambda model, params=None: AnswerModel(messages=iter(["访客你好"])))
    monkeypatch.setattr(retriever, "embed_query", lambda t: [0.1] * settings.EMBEDDING_DIM)
    monkeypatch.setattr(settings, "RERANK_PROVIDER", "")
    calls = []
    real = chat_service.build_chat_context

    def _spy(db, agent_id, message_text, conversation_id, role=None, **kwargs):
        calls.append({"role": role, **kwargs})
        return real(db, agent_id, message_text, conversation_id, role=role, **kwargs)

    monkeypatch.setattr(chat_service, "build_chat_context", _spy)
    return calls


def _model(client, auth_headers, made) -> dict:
    r = client.post("/api/v1/models", headers=auth_headers, json={"name": "pytest-share-model-" + _uid(), "provider": "openai",
                                                                  "api_base": "http://upstream.test/v1", "api_key": "sk-test", "model_name": "x", "default_params": {}})
    assert r.status_code == 200, r.text
    made["models"].append(r.json()["id"])
    return r.json()


def _agent(client, auth_headers, made, model_id: int, *, publish: bool = True, kb_ids: list | None = None, prompt: str = "你是助手") -> int:
    r = client.post("/api/v1/agents", headers=auth_headers, json={"name": "pytest-share-agent-" + _uid(), "description": "访客简介",
                                                                  "system_prompt": prompt, "model_id": model_id, "kb_ids": kb_ids or []})
    assert r.status_code == 200, r.text
    made["agents"].append(r.json()["id"])
    if publish:
        assert client.post(f"/api/v1/agents/{r.json()['id']}/publish", headers=auth_headers).status_code == 200
    return r.json()["id"]


def _share(client, headers, agent_id: int, **over) -> dict:
    r = client.put(_share_path(agent_id), headers=headers, json=_config(**over))
    assert r.status_code == 200, r.text
    return r.json()


def _user(client, auth_headers, made, role: str) -> tuple[int, dict]:
    username = "pytest-share-" + role + "-" + _uid()
    u = client.post("/api/v1/users", headers=auth_headers, json={"username": username, "password": "pytest-Passw0rd", "role": role})
    assert u.status_code == 200, u.text
    made["users"].append(u.json()["id"])
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "pytest-Passw0rd"}).json()["token"]
    return u.json()["id"], {"Authorization": "Bearer " + token}


def _guest(client, code: str, password: str | None = None, headers: dict | None = None) -> dict:
    r = client.post(_pub(code, "/sessions"), json={"password": password}, headers=headers or {})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["guest_token"]}


def _gchat(client, code: str, guest: dict, message: str = "你好", **body):
    return client.post(_pub(code, "/chat"), headers=guest, json={"message": message, **body})


def _done(client, code: str, guest: dict, message: str = "你好", **body) -> dict:
    r = _gchat(client, code, guest, message, **body)
    assert r.status_code == 200, r.text
    assert _events(r)[-1]["type"] == "done", r.text
    return _events(r)[-1]


def _kb_with_chunk(client, auth_headers, made, *, is_public: bool, visible_roles: list) -> tuple[int, str]:
    name = "pytest-share-kb-" + _uid()
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": name, "chunk_size": 200, "chunk_overlap": 0,
                                                                            "is_public": is_public, "visible_roles": visible_roles})
    assert r.status_code == 200, r.text
    kb_id = r.json()["id"]
    made["kbs"].append(kb_id)
    db = SessionLocal()
    try:
        doc = Document(kb_id=kb_id, name="pytest-share.txt", file_path="pytest/unused.txt", file_type="txt", status="ready")
        db.add(doc)
        db.commit()
        db.add(DocumentChunk(doc_id=doc.id, kb_id=kb_id, content=CONTENT, embedding=[0.1] * settings.EMBEDDING_DIM, meta={}, token_count=len(CONTENT)))
        db.commit()
    finally:
        db.close()
    return kb_id, name


def _share_row(agent_id: int) -> AgentShare:
    db = SessionLocal()
    try:
        return db.query(AgentShare).filter(AgentShare.agent_id == agent_id).one()
    finally:
        db.close()


def _share_runs(share_id: int) -> list[Run]:
    db = SessionLocal()
    try:
        return db.query(Run).filter(Run.share_id == share_id).order_by(Run.id).all()
    finally:
        db.close()


@pytest.fixture
def public_share(client, auth_headers, made, stub) -> dict:
    model = _model(client, auth_headers, made)
    marker = "PROMPT-MARK-" + _uid()
    agent_id = _agent(client, auth_headers, made, model["id"], prompt=f"你是助手。{marker}")
    share = _share(client, auth_headers, agent_id)
    return {"agent": agent_id, "code": share["code"], "model": model, "marker": marker, "calls": stub}


# ---------- 管理接口 ----------

def test_share_cannot_be_enabled_before_publish(client, auth_headers, made):
    agent_id = _agent(client, auth_headers, made, _model(client, auth_headers, made)["id"], publish=False)
    got = client.get(_share_path(agent_id), headers=auth_headers).json()
    assert (got["is_enabled"], got["code"], got["published"]) == (False, None, False)
    r = client.put(_share_path(agent_id), headers=auth_headers, json=_config())
    assert r.status_code == 400 and r.json()["detail"] == "智能体未发布，不能开启分享"
    assert client.put(_share_path(agent_id), headers=auth_headers, json=_config(is_enabled=False)).status_code == 200  # 先存配置不开启可以


def test_share_management_is_jwt_admin_or_developer_only(client, auth_headers, made, caller_headers, key_scope):
    agent_id = _agent(client, auth_headers, made, _model(client, auth_headers, made)["id"])
    assert client.get(_share_path(agent_id), headers=caller_headers).status_code == 403
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-share-key-" + _uid(), **key_scope}).json()
    made["keys"].append(key["id"])
    r = client.put(_share_path(agent_id), headers={"Authorization": "Bearer " + key["key"]}, json=_config())
    assert r.status_code == 403 and r.json()["detail"] == "API Key 不能访问管理接口"


@pytest.mark.parametrize("over", [{"rate_limit_per_minute": 0}, {"visitor_daily_limit": 1001}, {"access_mode": "anyone"},
                                  {"expires_at": "2030-01-01T00:00:00"}, {"password": "密" * 25}])
def test_share_config_out_of_range_is_rejected(client, auth_headers, over):
    """范围、枚举、不带时区的有效期、超过 bcrypt 72 字节的密码（25 个汉字 = 75 字节）都在 schema 层 422，不进服务层。"""
    r = client.put(_share_path(999999991), headers=auth_headers, json=_config(**over))
    assert r.status_code == 422, r.text


def test_share_update_is_idempotent_and_audited(client, auth_headers, public_share):
    """同一请求重放不写库、不记审计；改了才记，detail 只有字段名不含密码。"""
    agent_id = public_share["agent"]
    row = _share_row(agent_id)

    def audits() -> list:
        db = SessionLocal()
        try:
            return [(a.action, a.detail) for a in db.query(AuditLog).filter(AuditLog.resource == "agent_share", AuditLog.resource_id == row.id).order_by(AuditLog.id)]
        finally:
            db.close()

    assert [a[0] for a in audits()] == ["share_enable"]
    _share(client, auth_headers, agent_id)
    assert len(audits()) == 1
    _share(client, auth_headers, agent_id, password="pw-1234", show_citations=False)
    assert audits()[-1] == ("share_update", {"agent_id": agent_id, "changed": ["show_citations", "password"]})
    _share(client, auth_headers, agent_id, is_enabled=False)
    assert audits()[-1][0] == "share_disable"


# ---------- 访客对话与会话（AC-026 ① ③ ⑦） ----------

def test_public_visitor_chats_and_resumes_but_other_visitor_cannot(client, public_share):
    code = public_share["code"]
    alice = _guest(client, code)
    cid = _done(client, code, alice)["conversation_id"]
    _done(client, code, alice, "再问一句", conversation_id=cid)
    listed = client.get(_pub(code, "/conversations"), headers=alice).json()
    assert [(c["id"], c["message_count"]) for c in listed["items"]] == [(cid, 4)]
    assert set(listed["items"][0]) == {"id", "title", "message_count", "created_at", "updated_at"}
    assert client.get(_pub(code, "/conversations"), headers=alice, params={"q": "没有这个标题"}).json()["items"] == []

    bob = _guest(client, code)
    assert client.get(_pub(code, "/conversations"), headers=bob).json()["items"] == []
    assert _gchat(client, code, bob, conversation_id=cid).status_code == 404
    assert client.get(_pub(code, f"/conversations/{cid}/messages"), headers=bob).status_code == 404
    assert client.delete(_pub(code, f"/conversations/{cid}"), headers=bob).status_code == 404
    assert client.delete(_pub(code, f"/conversations/{cid}"), headers=alice).status_code == 200
    assert client.get(_pub(code, "/conversations"), headers=alice).json()["items"] == []


def test_guest_responses_never_expose_internals(client, auth_headers, made, stub):
    """资料、SSE、会话列表、消息列表的响应全文里都没有系统提示词、模型名、run_id、用量、kb_id / chunk_id / score。"""
    model = _model(client, auth_headers, made)
    kb_id, _ = _kb_with_chunk(client, auth_headers, made, is_public=True, visible_roles=[])
    marker = "PROMPT-MARK-" + _uid()
    agent_id = _agent(client, auth_headers, made, model["id"], kb_ids=[kb_id], prompt=f"你是助手。{marker}")
    code = _share(client, auth_headers, agent_id)["code"]
    guest = _guest(client, code)
    info = client.get(_pub(code))
    assert set(info.json()) == {"agent_name", "description", "opening_statement", "starter_questions", "access_mode", "password_required", "show_citations"}
    chat = _gchat(client, code, guest, QUERY)
    cites = [c for e in _events(chat) if e["type"] == "citations" for c in e["citations"]]
    assert cites and all(set(c) == {"doc_name", "content"} for c in cites)
    cid = _events(chat)[-1]["conversation_id"]
    listed = client.get(_pub(code, "/conversations"), headers=guest)
    messages = client.get(_pub(code, f"/conversations/{cid}/messages"), headers=guest)
    assert messages.json()[1]["citations"] == [{"doc_name": "pytest-share.txt", "content": CONTENT}]
    for resp in (info, chat, listed, messages):
        for word in (*LEAKS, marker, model["name"]):
            assert word not in resp.text, (word, resp.request.url)


def test_guest_events_keep_only_names_and_map_unsafe_errors():
    """工具只留名称、tool_result 不带内容、done 不带 run_id 与用量；带模型名的熔断文案换成通用文案，白名单内的原样下发。"""
    async def collect(events, show_citations=True):
        async def gen():
            for e in events:
                yield e
        return [e async for e in share_service.guest_events(gen(), show_citations)]

    raw = [{"type": "citations", "citations": [{"kb_id": 1, "chunk_id": 2, "doc_name": "a.txt", "content": "片段", "score": 0.9}]},
           {"type": "tool_call", "id": "c1", "name": "查天气", "arguments": {"city": "上海"}},
           {"type": "tool_result", "tool_call_id": "c1", "content": "内部返回原文"},
           {"type": "done", "message_id": 5, "run_id": 9, "conversation_id": 3, "usage": {"total_tokens": 10}, "replayed": True},
           {"type": "error", "message": "模型「GPT-内部」暂时不可用，请稍后重试"},
           {"type": "error", "message": "今日额度已用完，请明天再试"}]
    out = asyncio.run(collect(raw))
    assert out[:4] == [{"type": "citations", "citations": [{"doc_name": "a.txt", "content": "片段"}]},
                       {"type": "tool_call", "id": "c1", "name": "查天气"}, {"type": "tool_result", "tool_call_id": "c1"},
                       {"type": "done", "message_id": 5, "conversation_id": 3}]
    assert out[4]["message"].startswith("服务暂时不可用，请稍后重试（trace:") and "GPT" not in out[4]["message"]
    assert out[5]["message"] == "今日额度已用完，请明天再试"
    assert asyncio.run(collect(raw[:1], show_citations=False)) == [{"type": "citations", "citations": []}]


def test_public_visitor_retrieves_only_public_kbs_and_has_no_http_tools(client, auth_headers, made, stub):
    """匿名访客按 role=None 检索：绑定的仅 admin 可见库引用不到、公开库照常；预检列出这个库；默认不装配 HTTP 工具。"""
    model = _model(client, auth_headers, made)
    hidden, hidden_name = _kb_with_chunk(client, auth_headers, made, is_public=False, visible_roles=["admin"])
    public, _ = _kb_with_chunk(client, auth_headers, made, is_public=True, visible_roles=[])
    agent_id = _agent(client, auth_headers, made, model["id"], kb_ids=[hidden, public])
    share = _share(client, auth_headers, agent_id)
    assert any(hidden_name in w for w in share["warnings"])
    cid = _done(client, share["code"], _guest(client, share["code"]), QUERY)["conversation_id"]
    db = SessionLocal()
    try:
        answer = db.query(Message).filter(Message.conversation_id == cid, Message.role == "assistant").one()
        assert [c["kb_id"] for c in answer.citations] == [public]  # 落库的引用带 kb_id，访客接口不下发
    finally:
        db.close()
    assert (stub[-1]["role"], stub[-1]["allow_http_tools"], stub[-1].get("kb_scope")) == (None, False, None)


def test_guest_answers_follow_live_version(client, auth_headers, public_share):
    """改提示词只保存不发布，访客仍按线上版本；发布后下一轮才用新的（原 AC-020① 的分享部分）。"""
    agent_id, code = public_share["agent"], public_share["code"]
    guest = _guest(client, code)
    detail = client.get(f"/api/v1/agents/{agent_id}", headers=auth_headers).json()
    body = {k: detail[k] for k in ("name", "description", "model_id", "kb_ids", "tool_ids")}
    r = client.put(f"/api/v1/agents/{agent_id}", headers=auth_headers, json={**body, "system_prompt": "草稿提示词", "expected_updated_at": detail["updated_at"]})
    assert r.status_code == 200, r.text
    _done(client, code, guest)
    assert public_share["calls"][-1]["agent_version"] == 1
    assert client.post(f"/api/v1/agents/{agent_id}/publish", headers=auth_headers).status_code == 200
    _done(client, code, guest)
    assert public_share["calls"][-1]["agent_version"] == 2


# ---------- 访客令牌（AC-026 ② ③ ⑥） ----------

def test_guest_token_is_rejected_by_platform_api(client, public_share):
    guest = _guest(client, public_share["code"])
    for path in ("/api/v1/auth/me", "/api/v1/conversations"):
        r = client.get(path, headers=guest)
        assert r.status_code == 401 and r.json()["detail"] == "Token 无效或已过期", path


def test_public_token_near_expiry_is_renewed_in_header(client, public_share):
    """公开模式令牌剩余不足 7 天时，响应头 X-Share-Token 带新令牌（同一访客 id，能看到原来的会话）；还早的不换发。"""
    code = public_share["code"]
    row = _share_row(public_share["agent"])
    old = create_guest_token({"sid": row.id, "vid": "v_pytest" + _uid(), "ver": row.token_version}, datetime.now(timezone.utc) + timedelta(days=3))
    guest = {"Authorization": "Bearer " + old}
    cid = _done(client, code, guest)["conversation_id"]
    r = client.get(_pub(code, "/conversations"), headers=guest)
    renewed = r.headers.get("x-share-token")
    assert renewed and renewed != old
    assert [c["id"] for c in client.get(_pub(code, "/conversations"), headers={"Authorization": "Bearer " + renewed}).json()["items"]] == [cid]
    assert "x-share-token" not in client.get(_pub(code, "/conversations"), headers=_guest(client, code)).headers


def test_token_of_one_share_cannot_call_another(client, auth_headers, made, public_share):
    other = _agent(client, auth_headers, made, public_share["model"]["id"])
    locked = _share(client, auth_headers, other, password="pw-locked")["code"]
    guest_of_open = _guest(client, public_share["code"])
    r = _gchat(client, locked, guest_of_open)
    assert r.status_code == 401 and r.json()["detail"] == share_service.CREDENTIAL_INVALID
    assert _share_runs(_share_row(other).id) == []


def test_password_change_revokes_open_visitors(client, auth_headers, public_share):
    agent_id, code = public_share["agent"], public_share["code"]
    _share(client, auth_headers, agent_id, password="pw-first")
    assert client.get(_pub(code)).json()["password_required"] is True
    r = client.post(_pub(code, "/sessions"), json={})
    assert r.status_code == 401 and r.json()["detail"] == "访问密码错误"
    guest = _guest(client, code, "pw-first")
    _share(client, auth_headers, agent_id, password="pw-first")  # 重放同一密码不算修改，不踢人
    _done(client, code, guest)
    _share(client, auth_headers, agent_id, password="pw-second")
    r = _gchat(client, code, guest)
    assert r.status_code == 401 and r.json()["detail"] == share_service.CREDENTIAL_INVALID
    _share(client, auth_headers, agent_id)  # 不带 password 字段 = 不改
    assert client.get(_pub(code)).json()["password_required"] is True
    _done(client, code, _guest(client, code, "pw-second"))


def test_disabled_reset_and_expired_links_are_closed(client, auth_headers, public_share):
    agent_id, code = public_share["agent"], public_share["code"]
    guest = _guest(client, code)
    _share(client, auth_headers, agent_id, is_enabled=False)
    r = client.get(_pub(code))
    assert r.status_code == 404 and r.json()["detail"] == "链接不存在或已关闭"
    _share(client, auth_headers, agent_id)
    new_code = client.post(_share_path(agent_id) + "/reset", headers=auth_headers).json()["code"]
    assert new_code != code and client.get(_pub(code)).status_code == 404
    assert _gchat(client, new_code, guest).status_code == 401  # 重置后已打开的访客也要重新进入
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _share(client, auth_headers, agent_id, expires_at=past)
    r = client.get(_pub(new_code))
    assert r.status_code == 403 and r.json()["detail"] == "链接已过期"


def test_login_mode_uses_visitor_identity_and_current_role(client, auth_headers, made, public_share, key_scope):
    """"仅登录"：没带平台 JWT 或带 API Key 401；会话记在访客本人名下；检索角色取库里的当前值（降级下一轮即生效）；
    停用后访客令牌立即 401。"""
    agent_id, code, calls = public_share["agent"], public_share["code"], public_share["calls"]
    _share(client, auth_headers, agent_id, access_mode="login")
    r = client.post(_pub(code, "/sessions"), json={})
    assert r.status_code == 401 and r.json()["detail"] == "需要登录后访问"
    key = client.post("/api/v1/api-keys", headers=auth_headers, json={"name": "pytest-share-key-" + _uid(), **key_scope}).json()
    made["keys"].append(key["id"])
    r = client.post(_pub(code, "/sessions"), json={}, headers={"Authorization": "Bearer " + key["key"]})
    assert r.status_code == 401 and r.json()["detail"] == "分享访问不接受 API Key"

    dev_id, dev_headers = _user(client, auth_headers, made, "developer")
    guest = _guest(client, code, headers=dev_headers)
    cid = _done(client, code, guest)["conversation_id"]
    assert calls[-1]["role"] == "developer"
    db = SessionLocal()
    try:
        conv = db.get(Conversation, cid)
        assert (conv.user_id, conv.channel, conv.end_user, conv.share_id) == (dev_id, "share", None, _share_row(agent_id).id)
    finally:
        db.close()
    assert client.put(f"/api/v1/users/{dev_id}", headers=auth_headers, json={"role": "caller"}).status_code == 200
    _done(client, code, guest, conversation_id=cid)
    assert calls[-1]["role"] == "caller"
    assert client.put(f"/api/v1/users/{dev_id}", headers=auth_headers, json={"is_active": False}).status_code == 200
    r = client.get(_pub(code, "/conversations"), headers=guest)
    assert r.status_code == 401 and r.json()["detail"] == share_service.CREDENTIAL_INVALID


# ---------- 归属、限额、幂等（AC-026 ④ ⑤ ⑧） ----------

def test_guest_runs_belong_to_creator_but_stay_out_of_creator_ui(client, auth_headers, made, stub):
    """公开访客的会话与运行记在分享创建者名下（source=share、share_id 正确），创建者自己的会话列表看不到；
    创建者名下有分享时不能删（409，分享与访客会话都还在）。"""
    dev_id, dev_headers = _user(client, auth_headers, made, "developer")
    agent_id = _agent(client, auth_headers, made, _model(client, auth_headers, made)["id"])
    code = _share(client, dev_headers, agent_id)["code"]
    cid = _done(client, code, _guest(client, code))["conversation_id"]
    share_id = _share_row(agent_id).id
    assert [(r.source, r.user_id, r.conversation_id) for r in _share_runs(share_id)] == [("share", dev_id, cid)]
    mine = client.get("/api/v1/conversations", headers=dev_headers, params={"page_size": 100}).json()["items"]
    assert cid not in {c["id"] for c in mine}
    r = client.delete(f"/api/v1/users/{dev_id}", headers=auth_headers)
    assert r.status_code == 409 and "分享链接" in r.json()["detail"]
    assert client.get(_pub(code)).status_code == 200


def test_daily_limits_return_429_without_new_runs(client, auth_headers, public_share):
    agent_id, code = public_share["agent"], public_share["code"]
    share_id = _share_row(agent_id).id
    _share(client, auth_headers, agent_id, visitor_daily_limit=1)
    alice = _guest(client, code)
    _done(client, code, alice)
    r = _gchat(client, code, alice)
    assert r.status_code == 429 and r.json()["detail"] == "你今天的提问次数已用完，请明天再试"
    _share(client, auth_headers, agent_id, daily_message_limit=1)
    r = _gchat(client, code, _guest(client, code))  # 换个访客绕得开每人每日量，绕不开链接每日总量
    assert r.status_code == 429 and r.json()["detail"] == "今日额度已用完，请明天再试"
    assert len(_share_runs(share_id)) == 1


def test_ip_limit_applies_across_visitor_tokens(client_from, public_share, monkeypatch):
    """同一 IP 换着访客令牌对话，超过 RATE_LIMIT_IP_PER_MINUTE 后 429 且不建运行记录（防绕开每位访客的分钟限额）。"""
    code = public_share["code"]
    share_id = _share_row(public_share["agent"]).id
    visitor = client_from(f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_IP_PER_MINUTE", 2)
    now = 1_800_000_000.0 + random.randint(0, 10**6) * 60  # 固定在一个随机窗口里：计数键 TTL 65 秒，重跑不撞上次的计数
    monkeypatch.setattr(rate_limiter, "_clock", lambda: now)
    guests = [_guest(visitor, code) for _ in range(3)]
    for g in guests[:2]:
        _done(visitor, code, g)
    r = _gchat(visitor, code, guests[2])
    assert r.status_code == 429 and "请求过于频繁" in r.json()["detail"]
    assert len(_share_runs(share_id)) == 2


def test_same_client_message_id_replays_without_new_messages(client, public_share):
    code = public_share["code"]
    guest = _guest(client, code)
    cid = _done(client, code, guest)["conversation_id"]
    first = _done(client, code, guest, "第二问", conversation_id=cid, client_message_id="m-1")
    db = SessionLocal()
    try:
        before = (db.query(Message).filter(Message.conversation_id == cid).count(), db.query(Run).filter(Run.conversation_id == cid).count())
    finally:
        db.close()
    again = _done(client, code, guest, "第二问", conversation_id=cid, client_message_id="m-1")
    assert again == {"type": "done", "message_id": first["message_id"], "conversation_id": cid}
    db = SessionLocal()
    try:
        after = (db.query(Message).filter(Message.conversation_id == cid).count(), db.query(Run).filter(Run.conversation_id == cid).count())
    finally:
        db.close()
    assert after == before == (4, 2)


def test_fake_model_name_never_reaches_guest(client, public_share, monkeypatch):
    """模型调用失败（熔断类 BizError，文案带模型名）时，访客收到的是通用文案。"""
    from app.core.exceptions import BizError

    def _boom(*args, **kwargs):
        raise BizError(503, f"模型「{FAKE_MODEL.name}」暂时不可用，请稍后重试")

    monkeypatch.setattr(chat_service, "build_chat_context", _boom)
    code = public_share["code"]
    events = _events(_gchat(client, code, _guest(client, code)))
    assert events[-1]["type"] == "error" and events[-1]["message"].startswith("服务暂时不可用")
    assert FAKE_MODEL.name not in json.dumps(events, ensure_ascii=False)
