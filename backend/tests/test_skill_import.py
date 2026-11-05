"""SKILL.md 解析（docs/17 §4.5）：Agent Skills 开放标准的兼容性。

导入分两步：POST /skills/parse 只解析、不落库，把字段回给前端填进编辑弹窗；
使用者确认后走正常的 POST /skills 保存。这样导入与手填共用同一条校验路径，
不存在"导入能绕过 name 格式、正文上限"的第二套入口。
"""
import pytest


def _parse(client, auth_headers, text: str):
    return client.post("/api/v1/skills/parse", headers=auth_headers, json={"text": text})


MINIMAL = """---
name: pdf-processing
description: 提取 PDF 文本、填表、合并文件。处理 PDF 或用户提到表单时使用。
---

# PDF 处理

## 步骤
1. 打开文件
"""


def test_parse_minimal(client, auth_headers):
    """规范里的最小例子：只有 name 与 description，正文是 frontmatter 之后的 Markdown。"""
    r = _parse(client, auth_headers, MINIMAL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "pdf-processing"
    assert body["content"] == "# PDF 处理\n\n## 步骤\n1. 打开文件"
    assert body["always_on"] is False, "导入的技能默认不常驻，否则长手册会把上下文占满"


def test_parse_keeps_optional_fields(client, auth_headers):
    """license / compatibility / allowed-tools / metadata 原样保留，不丢作者写的信息。"""
    r = _parse(client, auth_headers, """---
name: with-meta
description: 带全部可选字段的技能
license: Apache-2.0
compatibility: 需要 Python 3.12+
allowed-tools: Bash(git:*) Read
metadata:
  author: example-org
  version: "1.0"
---

正文
""")
    assert r.status_code == 200, r.text
    meta = r.json()["meta"]
    assert meta["license"] == "Apache-2.0"
    assert meta["compatibility"] == "需要 Python 3.12+"
    assert meta["allowed-tools"] == "Bash(git:*) Read"
    assert meta["metadata"] == {"author": "example-org", "version": "1.0"}


def test_parse_rejects_missing_frontmatter(client, auth_headers):
    r = _parse(client, auth_headers, "# 直接是正文，没有 frontmatter")
    assert r.status_code == 400, r.text
    assert "frontmatter" in r.json()["detail"]


def test_parse_rejects_missing_description(client, auth_headers):
    """空 description 等于技能永远不会被加载，规范里也是必填。"""
    r = _parse(client, auth_headers, "---\nname: no-desc\n---\n正文")
    assert r.status_code == 400, r.text
    assert "description" in r.json()["detail"]


def test_parse_rejects_empty_body(client, auth_headers):
    r = _parse(client, auth_headers, "---\nname: empty-body\ndescription: 有描述但没正文\n---\n\n")
    assert r.status_code == 400, r.text
    assert "正文" in r.json()["detail"]


def test_parse_rejects_unsupported_yaml(client, auth_headers):
    """多行折叠、列表、锚点这些结构不猜也不静默丢：明确报错让使用者改成标量。"""
    r = _parse(client, auth_headers, "---\nname: x\ndescription: y\ntags:\n  - a\n  - b\n---\n正文")
    assert r.status_code == 400, r.text
    assert "不支持" in r.json()["detail"]


def test_parse_does_not_write(client, auth_headers):
    """解析不落库：使用者没确认前不该在技能列表里冒出一条。"""
    before = client.get("/api/v1/skills", headers=auth_headers, params={"q": "pdf-processing"}).json()["total"]
    assert _parse(client, auth_headers, MINIMAL).status_code == 200
    after = client.get("/api/v1/skills", headers=auth_headers, params={"q": "pdf-processing"}).json()["total"]
    assert after == before


def test_parse_output_saves_through_normal_path(client, auth_headers):
    """解析结果走正常 POST /skills 能存下来，且 name 格式校验照样生效（导入没有旁路）。"""
    parsed = _parse(client, auth_headers, MINIMAL).json()
    created = client.post("/api/v1/skills", headers=auth_headers, json={
        "name": parsed["name"], "display_name": parsed["display_name"], "description": parsed["description"],
        "content": parsed["content"], "always_on": parsed["always_on"], "is_enabled": True})
    assert created.status_code == 200, created.text
    try:
        assert created.json()["name"] == "pdf-processing"
    finally:
        client.delete(f"/api/v1/skills/{created.json()['id']}", headers=auth_headers)


def test_parse_rejects_illegal_name_after_edit(client, auth_headers):
    """导入的 name 不合法时，保存那一步照样 422 —— 校验只有一处。"""
    parsed = _parse(client, auth_headers, MINIMAL).json()
    r = client.post("/api/v1/skills", headers=auth_headers, json={
        "name": "PDF-Processing", "display_name": parsed["display_name"], "description": parsed["description"],
        "content": parsed["content"]})
    assert r.status_code == 422, r.text


def test_parse_caller_forbidden(client, caller_headers):
    assert _parse(client, caller_headers, MINIMAL).status_code == 403
