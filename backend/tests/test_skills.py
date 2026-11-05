"""技能（docs/17 §4）：CRUD、装配（目录 / 常驻正文）与 load_skill 白名单。

负向用例优先：load_skill 越权、正文超限、重名、格式非法、停用不装配。
技能正文不进快照 —— 改技能立刻对线上生效，这条单独断言（发布语义与提示词模板相反）。
"""
import uuid

import pytest

from app.db.models import Agent, AuditLog, Skill
from app.db.session import SessionLocal
from app.runtime.agent_config import normalize_snapshot, run_config_from_snapshot, snapshot_of
from app.services import agent_service, chat_service, skill_service
from app.tools.langchain_tools import build_tools


def _uid() -> str:
    return uuid.uuid4().hex[:6]


def _new_model(client, auth_headers) -> dict:
    r = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-skill-model-" + _uid(), "provider": "openai", "api_base": "http://upstream.test/v1",
        "api_key": "sk-test", "model_name": "x", "default_params": {},
    })
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def model(client, auth_headers):
    m = _new_model(client, auth_headers)
    yield m
    client.delete(f"/api/v1/models/{m['id']}", headers=auth_headers)


@pytest.fixture
def make_skill(client, auth_headers):
    created: list[int] = []

    def _make(**changes) -> dict:
        body = {"name": "pytest-skill-" + _uid(), "display_name": "测试技能", "description": "测试用的一句话",
                "content": "步骤一：做事。", "always_on": False, "is_enabled": True}
        body.update(changes)
        r = client.post("/api/v1/skills", headers=auth_headers, json=body)
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
        return r.json()

    yield _make
    for sid in created:
        client.delete(f"/api/v1/skills/{sid}", headers=auth_headers)


@pytest.fixture
def make_agent(client, auth_headers, model):
    created: list[int] = []

    def _make(**changes) -> dict:
        body = {"name": "pytest-skill-agent-" + _uid(), "description": "", "system_prompt": "你是助手", "model_id": model["id"]}
        body.update(changes)
        r = client.post("/api/v1/agents", headers=auth_headers, json=body)
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
        return r.json()

    yield _make
    for aid in created:
        client.delete(f"/api/v1/agents/{aid}", headers=auth_headers)


# ---------- CRUD 与校验 ----------

def test_create_and_get_skill(client, auth_headers, make_skill):
    """新建后能取到正文；列表不含正文（正文是可能几千字的资产，列表页不需要）。"""
    s = make_skill(name="expense-form", display_name="报销单填写", content="# 报销流程\n1. 打开系统")
    detail = client.get(f"/api/v1/skills/{s['id']}", headers=auth_headers).json()
    assert detail["content"] == "# 报销流程\n1. 打开系统"
    assert detail["version"] == 1
    row = client.get("/api/v1/skills", headers=auth_headers, params={"q": "expense-form"}).json()["items"][0]
    assert "content" not in row


def test_duplicate_name_409(client, auth_headers, make_skill):
    """name 是模型调 load_skill 时唯一能传的标识，重名会让它取错手册。"""
    make_skill(name="dup-skill")
    r = client.post("/api/v1/skills", headers=auth_headers, json={
        "name": "dup-skill", "display_name": "另一个", "description": "x", "content": "y"})
    assert r.status_code == 409, r.text


@pytest.mark.parametrize("bad", ["Bad_Name", "UPPER", "-lead", "trail-", "double--hyphen", "带中文", "with space"])
def test_name_pattern_rejected(client, auth_headers, bad):
    """与 Agent Skills 开放标准一致：小写字母数字与连字符。带大写或空格会让模型频繁传错名字。"""
    r = client.post("/api/v1/skills", headers=auth_headers, json={
        "name": bad, "display_name": "x", "description": "y", "content": "z"})
    assert r.status_code == 422, r.text


def test_content_too_large_400(client, auth_headers):
    """正文按 UTF-8 字节算上限 64KB：中文一个字 3 字节，按字符数限制会让中文技能超出一倍。"""
    r = client.post("/api/v1/skills", headers=auth_headers, json={
        "name": "too-big-" + _uid(), "display_name": "x", "description": "y", "content": "中" * 30000})
    assert r.status_code == 400, r.text
    assert "64KB" in r.json()["detail"]


def test_empty_description_422(client, auth_headers):
    """空描述等于技能永远不会被加载（模型靠 description 决定要不要调），必须拦住。"""
    r = client.post("/api/v1/skills", headers=auth_headers, json={
        "name": "no-desc-" + _uid(), "display_name": "x", "description": "", "content": "z"})
    assert r.status_code == 422, r.text


def test_version_bumps_only_on_model_facing_fields(client, auth_headers, make_skill):
    """name / description / content 变化才 +1；只改显示名或开关不升版本（与提示词模板同口径）。"""
    s = make_skill()
    base = {"name": s["name"], "display_name": s["display_name"], "description": s["description"],
            "content": s["content"], "always_on": False}
    same = client.put(f"/api/v1/skills/{s['id']}", headers=auth_headers, json={**base, "display_name": "换个显示名"}).json()
    assert same["version"] == 1
    changed = client.put(f"/api/v1/skills/{s['id']}", headers=auth_headers, json={**base, "content": "新正文"}).json()
    assert changed["version"] == 2


def test_delete_bound_skill_409(client, auth_headers, make_skill, make_agent):
    """skill_ids 是 JSONB 无外键，删了不会级联清理，会留下悬空 ID，所以显式拦。"""
    s = make_skill()
    make_agent(skill_ids=[s["id"]])
    r = client.delete(f"/api/v1/skills/{s['id']}", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "绑定" in r.json()["detail"]


def test_write_audit_recorded(client, auth_headers, make_skill):
    """技能正文可能含内部规则，谁改的要能追溯。"""
    s = make_skill()
    db = SessionLocal()
    try:
        rows = db.query(AuditLog).filter(AuditLog.resource == "skill", AuditLog.resource_id == s["id"]).all()
        assert [r.action for r in rows] == ["create"]
    finally:
        db.close()


def test_caller_forbidden(client, caller_headers):
    """技能是管理能力，caller 不可见。"""
    assert client.get("/api/v1/skills", headers=caller_headers).status_code == 403


# ---------- 装配 ----------

def test_catalog_only_for_on_demand_and_body_for_always_on(client, auth_headers, make_skill, model):
    """常驻技能正文进系统提示且不再进目录（列了会让模型多调一次 load_skill）；按需技能只进目录。"""
    always = make_skill(name="always-rule", always_on=True, content="回答必须以【结论】开头。")
    on_demand = make_skill(name="expense-form", always_on=False, content="步骤一：打开系统。")
    snap = {"name": "t", "description": "", "system_prompt": "你是助手", "model_id": model["id"], "params": {},
            "kb_ids": [], "tool_ids": [], "skill_ids": [always["id"], on_demand["id"]], "workflow_id": None,
            "prompt_template_id": None, "prompt_template_version": None, "prompt_variables": {}}
    db = SessionLocal()
    try:
        ctx = chat_service._context_from_config(db, run_config_from_snapshot(1, snap), "你好", None)
        prompt = ctx.system_prompt
        assert "回答必须以【结论】开头。" in prompt, "常驻技能的正文要进系统提示"
        assert "- expense-form：测试用的一句话" in prompt, "按需技能要进目录"
        assert "步骤一：打开系统。" not in prompt, "按需技能的正文不能进系统提示"
        assert "- always-rule：" not in prompt, "常驻技能不该再进目录"
        assert "load_skill" in [t.name for t in ctx.tools]
    finally:
        db.close()


def test_disabled_skill_not_assembled(client, auth_headers, make_skill, model):
    """停用的技能不装配、不进目录，绑定关系保留（重新启用即恢复）。"""
    s = make_skill(is_enabled=False)
    snap = {"name": "t", "description": "", "system_prompt": "你是助手", "model_id": model["id"], "params": {},
            "kb_ids": [], "tool_ids": [], "skill_ids": [s["id"]], "workflow_id": None,
            "prompt_template_id": None, "prompt_template_version": None, "prompt_variables": {}}
    db = SessionLocal()
    try:
        ctx = chat_service._context_from_config(db, run_config_from_snapshot(1, snap), "你好", None)
        assert "【可用技能】" not in ctx.system_prompt
        assert "load_skill" not in [t.name for t in ctx.tools], "没有可用技能时不该暴露 load_skill"
    finally:
        db.close()


def test_no_skills_no_load_skill_tool():
    """没绑技能时不暴露 load_skill：一个永远返回「技能不存在」的工具只会诱导模型乱试。"""
    assert "load_skill" not in [t.name for t in build_tools([])]


# ---------- load_skill 白名单 ----------

def _load_skill_tool(skills):
    tools = build_tools([], skills=skills)
    return next(t for t in tools if t.name == "load_skill")


def test_load_skill_returns_body_for_bound(client, auth_headers, make_skill):
    s = make_skill(content="正文内容 A")
    db = SessionLocal()
    try:
        skill = db.get(Skill, s["id"])
        assert _load_skill_tool([skill]).invoke({"name": s["name"]}) == "正文内容 A"
    finally:
        db.close()


def test_load_skill_rejects_unbound(client, auth_headers, make_skill):
    """越权负向：传一个存在但没绑定的技能名，必须拿不到正文。"""
    bound = make_skill(name="bound-one-" + _uid())
    other = make_skill(name="other-one-" + _uid(), content="机密正文")
    db = SessionLocal()
    try:
        tool = _load_skill_tool([db.get(Skill, bound["id"])])
        assert tool.invoke({"name": other["name"]}) == f"技能不存在：{other['name']}"
        assert tool.invoke({"name": "根本没这个"}) == "技能不存在：根本没这个"
    finally:
        db.close()


def test_load_skill_whitelist_ignores_disabled(client, auth_headers, make_skill):
    """白名单只看装配时给的列表：停用的技能不会被装配进来，也就调不到。"""
    s = make_skill(is_enabled=False)
    db = SessionLocal()
    try:
        assert skill_service.enabled_skills(db, [s["id"]]) == []
    finally:
        db.close()


# ---------- 快照与发布语义 ----------

def test_snapshot_carries_skill_ids_but_not_content(client, auth_headers, make_skill, make_agent):
    """快照只存 ID：技能正文改了立刻对所有线上智能体生效，与提示词模板相反。"""
    s = make_skill(content="旧正文")
    agent = make_agent(skill_ids=[s["id"]])
    db = SessionLocal()
    try:
        snap = snapshot_of(db.get(Agent, agent["id"]))
        assert snap["skill_ids"] == [s["id"]]
        assert "旧正文" not in str(snap), "快照里不能有技能正文"
        assert "skill_ids" in normalize_snapshot(snap)
    finally:
        db.close()


def test_publish_then_edit_skill_takes_effect_immediately(client, auth_headers, make_skill, make_agent, model):
    """发布后改技能正文，线上装配立刻用新版（技能不进快照，没有"要重新发布"这一步）。"""
    s = make_skill(content="旧流程")
    agent = make_agent(skill_ids=[s["id"]])
    assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).json()["publish_result"] == "published"
    base = {"name": s["name"], "display_name": s["display_name"], "description": s["description"], "always_on": True}
    assert client.put(f"/api/v1/skills/{s['id']}", headers=auth_headers, json={**base, "content": "新流程"}).status_code == 200
    db = SessionLocal()
    try:
        cfg = agent_service.get_agent(db, agent["id"])  # 草稿行
        ctx = chat_service._context_from_config(db, run_config_from_snapshot(agent["id"], snapshot_of(cfg)), "你好", None)
        assert "新流程" in ctx.system_prompt
        assert "旧流程" not in ctx.system_prompt
    finally:
        db.close()


def test_restore_version_restores_skill_ids(client, auth_headers, make_skill, make_agent):
    """恢复到草稿时 skill_ids 一并还原（它在 SNAPSHOT_FIELDS 里）。"""
    s1 = make_skill()
    agent = make_agent(skill_ids=[s1["id"]])
    assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=auth_headers).json()["publish_result"] == "published"
    detail = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()
    version_id = client.get(f"/api/v1/agents/{agent['id']}/versions", headers=auth_headers).json()["items"][0]["id"]
    # 草稿解绑
    body = {k: detail[k] for k in ("name", "description", "system_prompt", "model_id", "params", "kb_ids", "tool_ids")}
    body.update({"skill_ids": [], "expected_updated_at": detail["updated_at"]})
    assert client.put(f"/api/v1/agents/{agent['id']}", headers=auth_headers, json=body).status_code == 200
    restored = client.post(f"/api/v1/agents/{agent['id']}/versions/{version_id}/restore", headers=auth_headers).json()
    assert restored["skill_ids"] == [s1["id"]]


def test_missing_skill_id_reported_in_detail(client, auth_headers, make_agent):
    """skill_ids 无外键，技能被删后会残留 ID；详情页要显式列出来，不能静默。

    接口层不允许存不存在的技能（保存时 400），所以这里直接改库造出悬空 ID ——
    模拟"绑定时技能还在、后来被人删了"这条真实路径（删除被绑定的技能会 409，
    但绕过接口直接写库、或将来放开删除限制，都会走到这里）。
    """
    agent = make_agent()
    db = SessionLocal()
    try:
        db.get(Agent, agent["id"]).skill_ids = [999999]
        db.commit()
    finally:
        db.close()
    detail = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_headers).json()
    assert detail["missing_skill_ids"] == [999999]


def test_create_agent_rejects_unknown_skill(client, auth_headers, model):
    """保存时校验技能存在（与工具、知识库同一口径），不存在的 ID 400 并列出。"""
    r = client.post("/api/v1/agents", headers=auth_headers, json={
        "name": "pytest-bad-skill-" + _uid(), "description": "", "system_prompt": "x",
        "model_id": model["id"], "skill_ids": [888888]})
    assert r.status_code == 400, r.text
    assert "888888" in r.json()["detail"]
