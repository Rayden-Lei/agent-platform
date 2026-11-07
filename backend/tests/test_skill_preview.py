"""技能「模型视角预览」测试（docs/17 §4）。

预览解决的问题：技能最容易写错的两处（description 决定模型会不会想到用它、always_on 决定
正文是否每轮占上下文）在编辑框里完全看不出来，以往只能绑到智能体上跑一轮才知道。

预览是**纯本地拼装**，不调模型。因此这里的断言可以精确到"哪段文字会进提示词"，
而不是"效果看起来还行"。
"""
from __future__ import annotations

import uuid

import pytest

from app.services import skill_service


@pytest.fixture
def make_skill(client, auth_headers):
    """建一个技能并返回详情，用完删掉。"""
    created: list[int] = []

    def _make(**kw):
        body = {
            "name": "pytest-preview-" + uuid.uuid4().hex[:8],
            "display_name": "预览测试技能",
            "description": "用于测试预览功能：当用户需要验证技能装配效果时使用。",
            "content": "# 步骤\n1. 第一步",
            "always_on": False,
            "is_enabled": True,
            **kw,
        }
        res = client.post("/api/v1/skills", headers=auth_headers, json=body)
        assert res.status_code == 200, res.text
        sid = res.json()["id"]
        created.append(sid)
        return sid

    yield _make
    for sid in created:
        client.delete(f"/api/v1/skills/{sid}", headers=auth_headers)


def test_on_demand_skill_shows_catalog_line_only(client, auth_headers, make_skill):
    """按需技能：只有 name + description 那一行进提示词，正文不在。

    这是渐进式披露的核心承诺：绑十个技能不该把上下文占满。
    """
    sid = make_skill(name="pytest-preview-ondemand", description="当需要查询天气时使用")
    res = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["in_catalog"] is True
    assert body["catalog_line"] == "- pytest-preview-ondemand：当需要查询天气时使用"
    # 正文不能出现在目录行里
    assert "第一步" not in body["catalog_line"]
    # 常驻正文为空（不是常驻）
    assert body["always_on_body"] == ""
    # 但模型真加载时能拿到全文
    assert "第一步" in body["load_skill_result"]


def test_always_on_skill_body_is_injected(client, auth_headers, make_skill):
    """常驻技能：正文整段每轮都进系统提示，且不再出现在目录里（避免同一技能两条途径）。"""
    sid = make_skill(name="pytest-preview-always", always_on=True)
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()

    assert body["always_on"] is True
    assert body["in_catalog"] is False
    assert body["catalog_line"] == ""
    assert "第一步" in body["always_on_body"]
    assert "pytest-preview-always" in body["always_on_body"]


def test_token_estimates_are_positive_and_ordered(client, auth_headers, make_skill):
    """token 估算：三个数都在，且常驻正文的估算不为 0（否则"多重"这个提示就是假的）。"""
    sid = make_skill(name="pytest-preview-tokens", always_on=True,
                     content="这是一段比较长的正文，" * 20)
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()
    tokens = body["tokens"]
    assert tokens["load_skill_result"] > 0
    assert tokens["always_on_body"] > 0
    # 每轮开销 = 常驻正文的估算
    assert body["per_turn_overhead"] == tokens["always_on_body"]


def test_on_demand_per_turn_overhead_is_catalog_only(client, auth_headers, make_skill):
    """按需技能每轮只付目录那一行的开销，远小于加载全文。"""
    sid = make_skill(name="pytest-preview-cheap", content="很长的正文，" * 100)
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()
    assert body["per_turn_overhead"] == body["tokens"]["catalog"]
    assert body["per_turn_overhead"] < body["tokens"]["load_skill_result"]


def test_short_description_gets_advice(client, auth_headers, make_skill):
    """描述太短要提示 —— 描述是模型判断"要不要用"的唯一依据。"""
    sid = make_skill(name="pytest-preview-short", description="天气")
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()
    assert any("描述偏短" in tip for tip in body["advice"])


def test_description_without_trigger_gets_advice(client, auth_headers, make_skill):
    """纯名词堆叠（没有"当/如果/需要"这类触发场景）也要提示。"""
    sid = make_skill(name="pytest-preview-notrigger",
                     description="PDF 文本提取 表单填写 文件合并 图片处理 批量转换 格式检查")
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()
    assert any("触发场景" in tip for tip in body["advice"])


def test_always_on_gets_overhead_advice(client, auth_headers, make_skill):
    """常驻要说清代价：每轮都占上下文。"""
    sid = make_skill(name="pytest-preview-overhead", always_on=True)
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()
    assert any("每轮" in tip for tip in body["advice"])


def test_disabled_skill_says_it_wont_appear(client, auth_headers, make_skill):
    """停用的技能要在预览里说清"装配时不会出现"，否则使用者会以为它还能用。"""
    sid = make_skill(name="pytest-preview-off", is_enabled=False)
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()
    assert any("停用" in tip for tip in body["advice"])


def test_large_content_gets_split_advice(client, auth_headers, make_skill):
    """正文很大时提示拆技能 —— 加载后要一次吃掉这么多上下文。"""
    sid = make_skill(name="pytest-preview-big", content="内容" * 4000)   # 约 24KB
    body = client.get(f"/api/v1/skills/{sid}/preview", headers=auth_headers).json()
    assert any("拆成多个技能" in tip for tip in body["advice"])


def test_preview_of_missing_skill_is_404(client, auth_headers):
    assert client.get("/api/v1/skills/99999999/preview", headers=auth_headers).status_code == 404


def test_caller_cannot_preview(client, caller_headers):
    """预览与技能管理同权限：caller 403。"""
    assert client.get("/api/v1/skills/1/preview", headers=caller_headers).status_code == 403


def test_estimate_tokens_handles_mixed_and_empty():
    """估算函数本身：空串为 0，中文比同长度英文贵（一个汉字约 1~2 token）。"""
    assert skill_service.estimate_tokens("") == 0
    zh = skill_service.estimate_tokens("中" * 100)
    en = skill_service.estimate_tokens("a" * 100)
    assert zh > en
    assert 40 < zh < 120   # 100 汉字 → 60~70 token 量级
    assert 15 < en < 40    # 100 英文字符 → 25 token 量级
