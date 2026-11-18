"""缺失的路由测试补齐（2026-11-18 审计）：这些接口此前**没有任何测试引用**。

逐个 grep 确认过：GET /skills/stats、POST /skills/batch、POST /agents/batch、
POST /embedding-models/batch、POST /embedding-models/{id}/test、GET /stats/runs/summary
在 tests/ 里 0 命中。其中 agents/batch 覆盖发布 / 下线 / 删除三种动作，
"批量失败清单"的语义（逐条独立、失败的带 detail 继续）没有任何用例守护。

写这组用例的理由不是覆盖率好看：批量接口是"一次操作改多条数据"的入口，
失败语义写错（比如某条失败就整体回滚，或者失败不说明原因）在界面上看不出来，
只有用测试把"成功清单 / 失败清单 / 失败原因"三者钉住。
"""
from __future__ import annotations

import uuid

from app.config import settings


def _uid() -> str:
    return uuid.uuid4().hex[:6]


# --------------------------------------------------------------------------- GET /skills/stats

def test_skill_stats_counts_and_caller_forbidden(client, auth_headers, caller_headers):
    """技能统计返回计数结构；caller 无权访问（技能是构建期资产，与技能列表同一口径）。"""
    r = client.get("/api/v1/skills/stats", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict) and body, "统计结构不应为空"
    # 不写死具体数字（共享库里别人也在建技能），只断言口径：所有计数都是非负整数
    for key, value in body.items():
        assert isinstance(value, int) and value >= 0, f"{key} 应为非负整数，实际 {value!r}"

    denied = client.get("/api/v1/skills/stats", headers=caller_headers)
    assert denied.status_code == 403, denied.text


# --------------------------------------------------------------------------- POST /skills/batch

def _create_skill(client, headers, name: str | None = None) -> dict:
    payload = {
        "name": name or ("pytest-batch-skill-" + _uid()),
        "display_name": "批量测试技能",
        "description": "当需要验证批量删除时使用",
        "content": "# 正文",
        "always_on": False,
    }
    r = client.post("/api/v1/skills", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_skill_batch_delete_returns_succeeded_and_failed_lists(client, auth_headers):
    """批量删除逐条独立：存在的进 succeeded，不存在的进 failed 且带原因，不影响其它条。"""
    a = _create_skill(client, auth_headers)
    b = _create_skill(client, auth_headers)
    missing = 99999999
    r = client.post("/api/v1/skills/batch", headers=auth_headers, json={"ids": [a["id"], missing, b["id"]], "action": "delete"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["succeeded"]) == {a["id"], b["id"]}
    assert [item["id"] for item in body["failed"]] == [missing]
    assert body["failed"][0]["detail"], "失败项必须带可展示的原因"

    # 真删掉了：再查是 404
    assert client.get(f"/api/v1/skills/{a['id']}", headers=auth_headers).status_code == 404


def test_skill_batch_duplicate_ids_are_deduped(client, auth_headers):
    """重复 id 只执行一次：否则第二次会以"不存在"进失败清单，看起来像接口坏了。"""
    s = _create_skill(client, auth_headers)
    r = client.post("/api/v1/skills/batch", headers=auth_headers, json={"ids": [s["id"], s["id"]], "action": "delete"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["succeeded"] == [s["id"]]
    assert body["failed"] == []


def test_skill_batch_rejects_empty_and_oversized_id_lists(client, auth_headers):
    """ids 为空或超过上限是 422（schema 层拦），不是 200 空操作。"""
    empty = client.post("/api/v1/skills/batch", headers=auth_headers, json={"ids": [], "action": "delete"})
    assert empty.status_code == 422, empty.text
    too_many = client.post("/api/v1/skills/batch", headers=auth_headers, json={"ids": list(range(1, 102)), "action": "delete"})
    assert too_many.status_code == 422, too_many.text


def test_skill_batch_rejects_unknown_action(client, auth_headers):
    """action 是 Literal，非法值 422（批量删除接口不能顺便接受 enable）。"""
    r = client.post("/api/v1/skills/batch", headers=auth_headers, json={"ids": [1], "action": "enable"})
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- POST /agents/batch

def test_agent_batch_publish_offline_and_failure_list(client, auth_headers):
    """智能体批量：publish 与 offline 都能逐条生效；不存在的 id 进失败清单且不影响其它条。"""
    # 模型直接建（不依赖别的测试文件的 fixture：本文件要能单独跑）
    m = client.post("/api/v1/models", headers=auth_headers, json={
        "name": "pytest-batch-agent-model", "provider": "openai", "api_base": "https://example.com/v1",
        "api_key": "sk-test", "model_name": "m", "default_params": {}})
    assert m.status_code == 200, m.text
    model_id = m.json()["id"]
    created = []
    for _ in range(2):
        r = client.post("/api/v1/agents", headers=auth_headers, json={
            "name": "pytest-batch-agent-" + _uid(), "description": "", "system_prompt": "你是助手",
            "model_id": model_id})
        assert r.status_code == 200, r.text
        created.append(r.json()["id"])
    missing = 99999998
    try:
        published = client.post("/api/v1/agents/batch", headers=auth_headers,
                                json={"ids": created + [missing], "action": "publish"})
        assert published.status_code == 200, published.text
        body = published.json()
        assert set(body["succeeded"]) == set(created)
        assert [item["id"] for item in body["failed"]] == [missing]
        assert body["failed"][0]["detail"]

        # 发布之后列表里能看到 published_at（与单条发布同一口径）
        rows = {row["id"]: row for row in client.get("/api/v1/agents", headers=auth_headers,
                                                    params={"q": "pytest-batch-agent"}).json()["items"]}
        for agent_id in created:
            assert rows[agent_id]["published_at"], f"智能体 {agent_id} 应已发布"

        offline = client.post("/api/v1/agents/batch", headers=auth_headers, json={"ids": created, "action": "offline"})
        assert offline.status_code == 200, offline.text
        assert set(offline.json()["succeeded"]) == set(created)
    finally:
        for agent_id in created:
            client.delete(f"/api/v1/agents/{agent_id}", headers=auth_headers)
        client.delete(f"/api/v1/models/{model_id}", headers=auth_headers)


def test_agent_batch_caller_forbidden(client, caller_headers):
    """批量操作是管理动作：caller 403，且不会部分执行。"""
    r = client.post("/api/v1/agents/batch", headers=caller_headers, json={"ids": [1], "action": "publish"})
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- POST /embedding-models/batch

def _create_embedding_model(client, headers, name: str | None = None) -> dict:
    r = client.post("/api/v1/embedding-models", headers=headers, json={
        "name": name or ("pytest-batch-embed-" + _uid()), "provider": "openai",
        "api_base": "https://pytest.invalid/v1", "api_key": "pytest-key",
        "model_name": "pytest-embed-model", "dim": settings.EMBEDDING_DIM,
        "request_size": 20, "is_enabled": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_embedding_batch_toggle_and_delete(client, auth_headers):
    """向量模型批量：停用与删除逐条生效；不存在的 id 进失败清单。"""
    a = _create_embedding_model(client, auth_headers)
    b = _create_embedding_model(client, auth_headers)
    missing = 99999997
    try:
        disabled = client.post("/api/v1/embedding-models/batch", headers=auth_headers,
                               json={"ids": [a["id"], b["id"], missing], "action": "disable"})
        assert disabled.status_code == 200, disabled.text
        body = disabled.json()
        assert set(body["succeeded"]) == {a["id"], b["id"]}
        assert [item["id"] for item in body["failed"]] == [missing]
        assert client.get(f"/api/v1/embedding-models/{a['id']}", headers=auth_headers).json()["is_enabled"] is False

        removed = client.post("/api/v1/embedding-models/batch", headers=auth_headers,
                              json={"ids": [a["id"], b["id"]], "action": "delete"})
        assert removed.status_code == 200, removed.text
        assert set(removed.json()["succeeded"]) == {a["id"], b["id"]}
    finally:
        for model_id in (a["id"], b["id"]):
            client.delete(f"/api/v1/embedding-models/{model_id}", headers=auth_headers)


def test_embedding_batch_caller_forbidden(client, caller_headers):
    """向量模型是 admin 资产：caller 与 developer 都无权批量操作（接口本身限 admin）。"""
    r = client.post("/api/v1/embedding-models/batch", headers=caller_headers, json={"ids": [1], "action": "delete"})
    assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- POST /embedding-models/{id}/test

def test_embedding_test_reports_failure_without_5xx(client, auth_headers):
    """连通测试打的是不可达地址：返回 ok=false 与原因，**不能抛 5xx**（否则页面会以为平台挂了）。"""
    m = _create_embedding_model(client, auth_headers)
    try:
        r = client.post(f"/api/v1/embedding-models/{m['id']}/test", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert body.get("error"), "失败必须给出原因"
    finally:
        client.delete(f"/api/v1/embedding-models/{m['id']}", headers=auth_headers)


def test_embedding_test_missing_model_404(client, auth_headers):
    r = client.post("/api/v1/embedding-models/99999996/test", headers=auth_headers)
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- GET /stats/runs/summary

def test_runs_period_summary_shape_and_window(client, auth_headers):
    """时间窗汇总：结构固定、days 回显、days 非法被拒。

    只断言结构与口径，不断言具体数值：共享库里有真实运行记录，写死数字必然随别人使用而失败。
    """
    r = client.get("/api/v1/stats/runs/summary", headers=auth_headers, params={"days": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 7
    for key in ("total", "success", "failed", "success_rate", "avg_latency_ms", "prompt_tokens", "completion_tokens", "cost"):
        assert key in body, f"汇总缺少字段 {key}"

    # 过滤条件与运行记录列表同口径：带上 run_type 也不报错
    filtered = client.get("/api/v1/stats/runs/summary", headers=auth_headers, params={"days": 7, "run_type": "workflow"})
    assert filtered.status_code == 200, filtered.text

    # days 超出上限**按上限截断**而不是报错：契约就是"超过上限按上限算"（stats.py 的 _days），
    # 回显的 days 会被截到 STATS_MAX_DAYS，调用方据此知道实际统计了多久
    too_long = client.get("/api/v1/stats/runs/summary", headers=auth_headers, params={"days": settings.STATS_MAX_DAYS + 1})
    assert too_long.status_code == 200, too_long.text
    assert too_long.json()["days"] == settings.STATS_MAX_DAYS

    # 下界仍然被 schema 拦：days=0 是非法输入，不是"统计 0 天"
    assert client.get("/api/v1/stats/runs/summary", headers=auth_headers, params={"days": 0}).status_code == 422
