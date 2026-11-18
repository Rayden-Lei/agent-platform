"""对话日志审阅（docs/15 PB-09 / OP-06）：管理面看全部会话。

守四件事：
① 只有 admin / developer 能进（caller 与 API Key 403）；
② 通道（ui / api / share）、类型、对象、发起人、标题、时间区间都能筛，列表项看得出是谁的、走哪条通道、属于哪个对象；
③ 看**他人**会话写审计 view / conversation（看自己的不写），据此能追到谁看过谁的会话；
④ 工具结果默认截到 200 字、带 full_tool_results 取库里那份，与 /conversations/{id}/messages 同一口径。

**造数全部直接插库、一次 commit**（不经 HTTP 逐个建）：开发库是共享的，别的测试会话启动时
会按 pytest- 前缀整表回收（tests/cleanup.purge_all_history）。经 HTTP 建模型 / 智能体 / 工作流
每个要几百毫秒到一秒，被清掉的窗口会拉到十几秒，用例随机报外键不存在；一次 commit 只有毫秒级窗口。
这也让本文件不依赖对话链路：要验的是审阅接口的口径，落库链路由 test_chat_runner / test_shares 覆盖。
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Agent, AgentShare, ApiKey, AuditLog, Conversation, Message, ModelConfig, User, Workflow
from app.db.session import SessionLocal
from app.services.api_key_service import hash_key

LOGS = "/api/v1/conversation-logs"
PREVIEW = 200  # core.limits.TOOL_RESULT_PREVIEW_CHARS
LONG_RESULT = "R" * 1200  # > PREVIEW 且 < STORE(8000)，截断与完整两档都能看出差别
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
# 隔离用的标题前缀：开发库是共享的，列表是全局的，不加这一条会把别人真实的会话也算进来。
# 本用例造的会话标题都以它开头，传了自己的 q 就覆盖它。
_PREFIX = "pytest-convlog-"


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def seed(client, auth_headers):
    """一个事务里造齐：第二个用户（他人）、模型 / 智能体 / 工作流、API Key、分享链接、三条会话与一轮消息。

    ui    / agent    / 归属他人
    api   / model    / 归属 admin，带 api_key_id 与终端用户
    share / workflow / 归属 admin，带 share_id 与访客 id
    三条会话的 created_at / updated_at 依次 +0h / +1h / +2h，供排序与时间区间断言。
    """
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers).json()["id"]
    db = SessionLocal()
    made: dict = {}
    try:
        owner = User(username=_PREFIX + "user-" + _uid(), password_hash="x", role="caller", is_active=True)
        db.add(owner)
        db.flush()
        model = ModelConfig(name=_PREFIX + "model-" + _uid(), provider="openai", api_base="http://upstream.test/v1",
                            api_key_enc="x", model_name="x", default_params={}, created_by=admin_id)
        db.add(model)
        db.flush()
        workflow = Workflow(name=_PREFIX + "workflow-" + _uid(), description="", graph={}, created_by=admin_id)
        db.add(workflow)
        db.flush()
        agent = Agent(name=_PREFIX + "agent-" + _uid(), description="", system_prompt="你是助手",
                      model_id=model.id, created_by=admin_id)
        db.add(agent)
        db.flush()
        plain = "ak_pytest_convlog_" + _uid()
        key = ApiKey(user_id=owner.id, name=_PREFIX + "key-" + _uid(), key_prefix=plain[:12] + "...",
                     key_hash=hash_key(plain), quota=1000, allowed_ips=[], rate_limit_per_minute=0,
                     agent_ids=[agent.id], workflow_ids=[], kb_ids=[])
        db.add(key)
        db.flush()
        share = AgentShare(agent_id=agent.id, code=_PREFIX + _uid(), is_enabled=True, access_mode="public",
                           created_by=owner.id)
        db.add(share)
        db.flush()

        convs = [
            Conversation(user_id=owner.id, kind="agent", agent_id=agent.id, channel="ui",
                         title=_PREFIX + "ui-" + _uid(), created_at=BASE_TIME, updated_at=BASE_TIME),
            Conversation(user_id=admin_id, kind="model", model_id=model.id, channel="api",
                         api_key_id=key.id, end_user="alice",
                         title=_PREFIX + "api-" + _uid(), created_at=BASE_TIME + timedelta(hours=1),
                         updated_at=BASE_TIME + timedelta(hours=1)),
            Conversation(user_id=admin_id, kind="workflow", workflow_id=workflow.id, channel="share",
                         share_id=share.id, end_user="visitor-1",
                         title=_PREFIX + "share-" + _uid(), created_at=BASE_TIME + timedelta(hours=2),
                         updated_at=BASE_TIME + timedelta(hours=2)),
        ]
        for row in convs:
            db.add(row)
        db.flush()
        # 一轮对话：先用户提问、再带长工具结果的助手回答（接口按消息 id 升序返回，即对话顺序）
        db.add(Message(conversation_id=convs[2].id, role="user", content="帮我查一下"))
        db.flush()
        db.add(Message(conversation_id=convs[2].id, role="assistant", content="工具查过了",
                       tool_calls=[{"name": "lookup", "arguments": {"q": "x"}, "result": LONG_RESULT}]))
        db.commit()
        made = {"owner_id": owner.id, "owner_username": owner.username, "admin_id": admin_id,
                "model_id": model.id, "agent_id": agent.id, "workflow_id": workflow.id,
                "api_key_id": key.id, "key_plain": plain, "share_id": share.id,
                "conversations": {"ui": convs[0].id, "api": convs[1].id, "share": convs[2].id}}
    finally:
        db.close()

    try:
        yield made
    finally:
        # 一次 commit 删干净：会话 → Key（conversations.api_key_id 是 SET NULL，先删会话更省事）
        # → 智能体（级联分享与版本）→ 工作流 → 模型 → 用户。消息走 ON DELETE CASCADE。
        db = SessionLocal()
        try:
            db.query(Conversation).filter(Conversation.id.in_(list(made["conversations"].values()))).delete(synchronize_session=False)
            db.query(ApiKey).filter(ApiKey.id == made["api_key_id"]).delete(synchronize_session=False)
            db.query(Agent).filter(Agent.id == made["agent_id"]).delete(synchronize_session=False)
            db.query(Workflow).filter(Workflow.id == made["workflow_id"]).delete(synchronize_session=False)
            db.query(ModelConfig).filter(ModelConfig.id == made["model_id"]).delete(synchronize_session=False)
            db.query(User).filter(User.id == made["owner_id"]).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


@pytest.fixture
def owner(seed):
    return {"id": seed["owner_id"], "username": seed["owner_username"]}


@pytest.fixture
def objects(seed):
    return seed


@pytest.fixture
def conversations(seed):
    return {**seed["conversations"], "admin_id": seed["admin_id"]}


def _ids(client, headers, **params) -> set:
    r = client.get(LOGS, headers=headers, params={"page_size": 100, "q": _PREFIX, **params})
    assert r.status_code == 200, r.text
    return {c["id"] for c in r.json()["items"]}


# ---------- 权限 ----------

def test_caller_and_api_key_are_forbidden(client, caller_headers, conversations, objects):
    """对话内容对调用者与 API Key 一律 403：这是管理面，能看到别人的会话原文。"""
    assert client.get(LOGS, headers=caller_headers).status_code == 403
    assert client.get(f"{LOGS}/{conversations['ui']}/messages", headers=caller_headers).status_code == 403
    key_headers = {"Authorization": "Bearer " + objects["key_plain"]}
    r = client.get(LOGS, headers=key_headers)
    assert r.status_code == 403 and r.json()["detail"] == "API Key 不能访问管理接口"
    assert client.get(f"{LOGS}/{conversations['ui']}/messages", headers=key_headers).status_code == 403


def test_anonymous_is_401(client):
    assert client.get(LOGS).status_code == 401


# ---------- 列表：看得出是谁的、走哪条通道、属于哪个对象 ----------

def test_list_shows_channel_owner_and_target(client, auth_headers, conversations, objects, owner):
    r = client.get(LOGS, headers=auth_headers, params={"page_size": 100, "q": _PREFIX})
    assert r.status_code == 200, r.text
    by_id = {c["id"]: c for c in r.json()["items"]}
    ui, api, share = by_id[conversations["ui"]], by_id[conversations["api"]], by_id[conversations["share"]]

    # 归属：ui 是 owner 的；api / share 是 admin 的（Key 与公开分享的会话记在归属人名下）
    assert (ui["channel"], ui["user_id"], ui["username"]) == ("ui", owner["id"], owner["username"])
    assert ui["kind"] == "agent" and ui["target_id"] == objects["agent_id"]
    assert ui["target_name"].startswith(_PREFIX + "agent-")
    assert (api["channel"], api["kind"]) == ("api", "model")
    assert api["api_key_id"] == objects["api_key_id"] and api["api_key_name"].startswith(_PREFIX + "key-")
    assert api["end_user"] == "alice" and api["target_id"] == objects["model_id"]
    assert api["target_name"].startswith(_PREFIX + "model-")
    assert (share["channel"], share["kind"], share["share_id"]) == ("share", "workflow", objects["share_id"])
    assert share["end_user"] == "visitor-1" and share["target_id"] == objects["workflow_id"]
    assert share["target_name"].startswith(_PREFIX + "workflow-")
    # 消息数与时间都在
    assert share["message_count"] == 2 and ui["message_count"] == 0
    assert ui["created_at"].startswith("2026-01-01")


def test_list_is_sorted_by_updated_at_desc(client, auth_headers, conversations):
    r = client.get(LOGS, headers=auth_headers, params={"page_size": 100, "q": _PREFIX})
    ids = [c["id"] for c in r.json()["items"]]
    # 三条会话的 updated_at 依次是 +0h / +1h / +2h，倒序即 share → api → ui
    assert ids.index(conversations["share"]) < ids.index(conversations["api"]) < ids.index(conversations["ui"])


# ---------- 筛选 ----------

@pytest.mark.parametrize("channel,expected", [("ui", "ui"), ("api", "api"), ("share", "share")])
def test_filter_by_channel(client, auth_headers, conversations, channel, expected):
    assert _ids(client, auth_headers, channel=channel) == {conversations[expected]}


@pytest.mark.parametrize("kind,expected", [("agent", "ui"), ("model", "api"), ("workflow", "share")])
def test_filter_by_kind(client, auth_headers, conversations, kind, expected):
    assert _ids(client, auth_headers, kind=kind) == {conversations[expected]}


def test_filter_by_target_requires_kind(client, auth_headers, conversations, objects):
    """只给 target_id 不知道比哪一列，400 而不是静默按某一列过滤（与 /conversations 同口径）。"""
    r = client.get(LOGS, headers=auth_headers, params={"target_id": objects["agent_id"]})
    assert r.status_code == 400 and "kind" in r.json()["detail"]
    assert _ids(client, auth_headers, kind="agent", target_id=objects["agent_id"]) == {conversations["ui"]}


def test_filter_by_user_id(client, auth_headers, conversations, owner):
    """发起人：owner 只有 ui 那条；admin 有 api 与 share 两条。"""
    assert _ids(client, auth_headers, user_id=owner["id"]) == {conversations["ui"]}
    assert _ids(client, auth_headers, user_id=conversations["admin_id"]) == {conversations["api"], conversations["share"]}


def test_filter_by_end_user(client, auth_headers, conversations):
    assert _ids(client, auth_headers, end_user="alice") == {conversations["api"]}
    assert _ids(client, auth_headers, end_user="visitor-1") == {conversations["share"]}
    assert _ids(client, auth_headers, end_user="nobody") == set()


def test_filter_by_title_keyword(client, auth_headers, conversations):
    assert _ids(client, auth_headers, q=_PREFIX + "ui-") == {conversations["ui"]}
    assert _ids(client, auth_headers, q="没有这个标题") == set()


def test_filter_by_created_time_is_left_closed_right_open(client, auth_headers, conversations):
    """时间区间左闭右开：下界含、上界不含。三条会话分别在 +0h / +1h / +2h。"""
    at = lambda h: (BASE_TIME + timedelta(hours=h)).isoformat()  # noqa: E731
    assert _ids(client, auth_headers, created_from=at(1), created_to=at(2)) == {conversations["api"]}
    assert _ids(client, auth_headers, created_from=at(1)) == {conversations["api"], conversations["share"]}
    assert _ids(client, auth_headers, created_to=at(1)) == {conversations["ui"]}


@pytest.mark.parametrize("params", [{"created_from": "2026-01-01T00:00:00"}, {"created_to": "2026-01-02T00:00:00"},
                                    {"created_from": "2026-01-02T00:00:00+08:00", "created_to": "2026-01-01T00:00:00+08:00"}])
def test_bad_time_range_is_400(client, auth_headers, params):
    """不带时区 / from >= to 一律 400（core.pagination.time_range 的统一口径）。"""
    assert client.get(LOGS, headers=auth_headers, params=params).status_code == 400


def test_bad_enum_and_page_are_422(client, auth_headers):
    assert client.get(LOGS, headers=auth_headers, params={"channel": "email"}).status_code == 422
    assert client.get(LOGS, headers=auth_headers, params={"kind": "chat"}).status_code == 422
    assert client.get(LOGS, headers=auth_headers, params={"page": 0}).status_code == 422


# ---------- 消息：工具结果两档 + 审计 ----------

def test_tool_results_truncated_by_default_and_full_on_demand(client, auth_headers, conversations):
    """默认与实时事件同长（200 字）并标出截断前长度；带 full_tool_results 取库里那份。"""
    short = client.get(f"{LOGS}/{conversations['share']}/messages", headers=auth_headers)
    assert short.status_code == 200, short.text
    rows = short.json()
    assert [m["role"] for m in rows] == ["user", "assistant"]
    call = rows[1]["tool_calls"][0]
    assert (call["name"], call["arguments"]) == ("lookup", {"q": "x"})
    assert len(call["result"]) == PREVIEW and call["result_truncated"] is True
    assert call["result_chars"] == len(LONG_RESULT)

    full = client.get(f"{LOGS}/{conversations['share']}/messages", headers=auth_headers, params={"full_tool_results": True})
    assert full.status_code == 200, full.text
    call = full.json()[1]["tool_calls"][0]
    assert call["result"] == LONG_RESULT and "result_truncated" not in call


def test_viewing_someone_elses_conversation_is_audited(client, auth_headers, conversations, owner):
    """看他人会话写审计 view / conversation，detail 记归属人与通道；看自己的不写。"""
    def audits() -> list:
        db = SessionLocal()
        try:
            return (db.query(AuditLog).filter(AuditLog.action == "view", AuditLog.resource == "conversation")
                    .order_by(AuditLog.id).all())
        finally:
            db.close()

    before = len(audits())
    assert client.get(f"{LOGS}/{conversations['ui']}/messages", headers=auth_headers).status_code == 200
    after = audits()
    assert len(after) == before + 1
    log = after[-1]
    assert log.resource_id == conversations["ui"]
    assert log.user_id == conversations["admin_id"]
    assert log.detail["owner_user_id"] == owner["id"] and log.detail["owner_username"] == owner["username"]
    assert log.detail["channel"] == "ui" and log.detail["full_tool_results"] is False

    # 看自己的会话（api / share 都记在 admin 名下）不写审计
    assert client.get(f"{LOGS}/{conversations['api']}/messages", headers=auth_headers).status_code == 200
    assert len(audits()) == before + 1

    # 带 full_tool_results 的查看同样留痕，detail 记下来
    assert client.get(f"{LOGS}/{conversations['ui']}/messages", headers=auth_headers,
                      params={"full_tool_results": True}).status_code == 200
    assert audits()[-1].detail["full_tool_results"] is True


def test_list_does_not_audit_every_row(client, auth_headers, conversations):
    """列表本身不写审计：逐条记会把审计页刷满，要追的是"谁看了谁的会话内容"。"""
    def count() -> int:
        db = SessionLocal()
        try:
            return db.query(AuditLog).filter(AuditLog.action == "view", AuditLog.resource == "conversation").count()
        finally:
            db.close()

    before = count()
    assert client.get(LOGS, headers=auth_headers, params={"page_size": 100, "q": _PREFIX}).status_code == 200
    assert count() == before


def test_missing_conversation_is_404(client, auth_headers):
    assert client.get(f"{LOGS}/99999999/messages", headers=auth_headers).status_code == 404
