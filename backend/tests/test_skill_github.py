"""从 GitHub 导入技能：地址解析、出站安全、抓取与落库。

分两层测：
- **纯解析与安全**（`parse_url` / `_assert_public_host`）不碰网络，直接断言；
- **抓取与落库**打桩 `skill_github.fetch_skill`，测的是路由的编排与回滚，
  不打真实 GitHub（否则测试会随网络、限流、仓库改动而飘）。

为什么要单独测安全：这是平台里唯一允许服务端主动访问「用户给的地址」的入口，
一个疏漏就是 SSRF（读云厂商元数据、探内网）。解析出来的每个形态都要有断言。
"""
from __future__ import annotations

import uuid

import pytest

from app.services import skill_github
from app.services.skill_github import RepoRef, SkillFetchError


# --------------------------------------------------------------------------- 地址解析

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/owner/repo", ("owner", "repo", None, "")),
    ("https://github.com/owner/repo/", ("owner", "repo", None, "")),
    ("github.com/owner/repo", ("owner", "repo", None, "")),                      # 容忍缺协议
    ("https://github.com/owner/repo/tree/main/skills/pdf", ("owner", "repo", "main", "skills/pdf")),
    ("https://github.com/owner/repo/blob/dev/a/SKILL.md", ("owner", "repo", "dev", "a/SKILL.md")),
    ("https://raw.githubusercontent.com/owner/repo/main/a/SKILL.md", ("owner", "repo", "main", "a/SKILL.md")),
    ("  https://github.com/owner/repo/tree/main/x  ", ("owner", "repo", "main", "x")),  # 两端空白
])
def test_parse_url_accepts_github_forms(url, expected):
    ref = skill_github.parse_url(url)
    assert (ref.owner, ref.repo, ref.ref, ref.path) == expected


@pytest.mark.parametrize("url,fragment", [
    ("", "请填写"),
    ("https://evil.example.com/o/r", "只支持从 GitHub 导入"),
    ("http://127.0.0.1:8080/x", "只支持从 GitHub 导入"),
    ("https://169.254.169.254/latest/meta-data", "只支持从 GitHub 导入"),
    ("git@github.com:owner/repo.git", "git 克隆地址"),
    ("https://github.com/onlyowner", "缺少仓库名"),
    ("https://github.com/o/r/some/random/path", "看不懂"),
])
def test_parse_url_rejects_bad_forms(url, fragment):
    """**非 GitHub 域名一律拒**：这是 SSRF 的第一道闸。

    特别钉住 169.254.169.254（云厂商元数据服务）与 127.0.0.1 ——
    如果哪天有人"顺手支持任意 URL"，这两条会立刻红。
    """
    with pytest.raises(SkillFetchError) as ei:
        skill_github.parse_url(url)
    assert fragment in str(ei.value)


def test_private_host_is_rejected_even_if_name_resolves():
    """域名白名单之外还有一层：解析结果落在内网段也拒（防 DNS 重绑定）。"""
    with pytest.raises(SkillFetchError) as ei:
        skill_github._assert_public_host("localhost")
    assert "内网" in str(ei.value) or "解析不了" in str(ei.value)


def test_allowed_hosts_does_not_include_lookalikes():
    """白名单是精确集合，不做后缀匹配：`evilgithub.com` 不能过。"""
    assert "github.com" in skill_github.ALLOWED_HOSTS
    assert "evilgithub.com" not in skill_github.ALLOWED_HOSTS
    assert "github.com.evil.com" not in skill_github.ALLOWED_HOSTS


# --------------------------------------------------------------------------- 预览接口

@pytest.fixture
def fake_fetch(monkeypatch):
    """打桩 fetch_skill：按调用方给的返回值返回，不打真实 GitHub。"""
    state: dict = {"result": None, "error": None, "calls": 0}

    def _fake(url: str):
        state["calls"] += 1
        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    monkeypatch.setattr(skill_github, "fetch_skill", _fake)
    # 路由里是 from app.services import skill_github 后调 skill_github.fetch_skill，
    # 所以打在模块属性上就能生效
    return state


SKILL_MD = """---
name: pdf-tools
description: 处理 PDF：提取文本、合并、拆分。用户提到 PDF 文件时使用。
license: Apache-2.0
---

# PDF 处理

用 pypdf 读文件。
"""


def _payload(files=None, skipped=None):
    return {
        "skill_md": SKILL_MD,
        "dir_path": "skills/pdf",
        "repo": "owner/repo",
        "ref": "main",
        "files": files or [],
        "skipped": skipped or [],
    }


def test_preview_returns_fields_and_file_list(client, auth_headers, fake_fetch):
    fake_fetch["result"] = _payload(files=[{"name": "helper.py", "content": b"print(1)"}])
    res = client.post("/api/v1/skills/import-github", headers=auth_headers,
                      json={"url": "https://github.com/owner/repo/tree/main/skills/pdf"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "pdf-tools"
    assert "PDF" in body["description"]
    assert body["repo"] == "owner/repo"
    # 文件清单只给名字与大小，不含内容（避免响应过大）
    assert body["files"] == [{"name": "helper.py", "size": 8}]
    assert "content" in body and "pypdf" in body["content"]


def test_preview_does_not_persist(client, auth_headers, fake_fetch):
    """预览不落库：这是"确认后才保存"的前提。"""
    fake_fetch["result"] = _payload()
    name = "pdf-tools"
    before = client.get("/api/v1/skills", headers=auth_headers, params={"q": name}).json()["total"]
    client.post("/api/v1/skills/import-github", headers=auth_headers,
                json={"url": "https://github.com/owner/repo/tree/main/skills/pdf"})
    after = client.get("/api/v1/skills", headers=auth_headers, params={"q": name}).json()["total"]
    assert after == before


def test_preview_surfaces_skipped_files(client, auth_headers, fake_fetch):
    """被跳过的文件要能看到原因 —— 否则导入完发现脚本少了一个，无从排查。"""
    fake_fetch["result"] = _payload(skipped=["logo.png", "big.zip（超过 512KB）"])
    body = client.post("/api/v1/skills/import-github", headers=auth_headers,
                       json={"url": "https://github.com/owner/repo/tree/main/x"}).json()
    assert "logo.png" in body["skipped"]
    assert any("512KB" in s for s in body["skipped"])


def test_preview_reports_fetch_error_as_400(client, auth_headers, fake_fetch):
    fake_fetch["error"] = SkillFetchError("仓库 owner/repo 不存在或不可见")
    res = client.post("/api/v1/skills/import-github", headers=auth_headers,
                      json={"url": "https://github.com/owner/repo"})
    assert res.status_code == 400
    assert "不存在" in res.json()["detail"]


def test_preview_reports_bad_skill_md_as_400(client, auth_headers, fake_fetch):
    """抓到文件但格式不对：提示要区分"没抓到"和"抓到了但格式不对"。"""
    fake_fetch["result"] = {**_payload(), "skill_md": "# 没有 frontmatter\n正文"}
    res = client.post("/api/v1/skills/import-github", headers=auth_headers,
                      json={"url": "https://github.com/owner/repo/tree/main/x"})
    assert res.status_code == 400
    assert "格式不对" in res.json()["detail"]


def test_caller_cannot_import(client, caller_headers, fake_fetch):
    fake_fetch["result"] = _payload()
    res = client.post("/api/v1/skills/import-github", headers=caller_headers,
                      json={"url": "https://github.com/owner/repo/tree/main/x"})
    assert res.status_code == 403


# --------------------------------------------------------------------------- 确认导入

def test_commit_creates_skill_and_writes_resources(client, auth_headers, fake_fetch, monkeypatch):
    """确认后落库，资源一并写入并登记到 resources。"""
    stored: list[str] = []

    def _store(skill_id, name, data, content_type="text/plain"):
        stored.append(name)
        return {"name": name, "type": "file", "object": f"skills/{skill_id}/{name}", "size": len(data)}

    monkeypatch.setattr("app.api.v1.skills.skill_resource.store_file", _store)
    fake_fetch["result"] = _payload(files=[{"name": "helper.py", "content": b"print(1)"}])

    unique = "pytest-gh-" + uuid.uuid4().hex[:8]
    res = client.post("/api/v1/skills/import-github/commit", headers=auth_headers, json={
        "url": "https://github.com/owner/repo/tree/main/skills/pdf",
        "name": unique, "display_name": "PDF 工具", "description": "处理 PDF",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == unique
    assert body["imported"]["files"] == ["helper.py"]
    assert stored == ["helper.py"]
    # 资源确实登记上了
    detail = client.get(f"/api/v1/skills/{body['id']}", headers=auth_headers).json()
    assert [r["name"] for r in detail["resources"]] == ["helper.py"]

    client.delete(f"/api/v1/skills/{body['id']}", headers=auth_headers)


def test_commit_uses_server_side_content_not_request_body(client, auth_headers, fake_fetch, monkeypatch):
    """正文以**服务端重新抓取**为准，不用客户端回传的 —— 否则前端能塞任意文本绕过校验。"""
    monkeypatch.setattr("app.api.v1.skills.skill_resource.store_file",
                        lambda *a, **kw: {"name": a[1], "type": "file", "object": "x", "size": 1})
    fake_fetch["result"] = _payload()

    unique = "pytest-gh-" + uuid.uuid4().hex[:8]
    res = client.post("/api/v1/skills/import-github/commit", headers=auth_headers, json={
        "url": "https://github.com/owner/repo/tree/main/skills/pdf",
        "name": unique, "display_name": "T", "description": "D",
        "content": "客户端伪造的正文，不该被采用",
    })
    assert res.status_code == 200, res.text
    detail = client.get(f"/api/v1/skills/{res.json()['id']}", headers=auth_headers).json()
    assert "pypdf" in detail["content"], "应采用服务端抓到的正文"
    assert "伪造" not in detail["content"]
    client.delete(f"/api/v1/skills/{res.json()['id']}", headers=auth_headers)


def test_commit_rolls_back_when_resource_write_fails(client, auth_headers, fake_fetch, monkeypatch):
    """资源写一半失败 → 整个技能撤掉，不留"技能建了但脚本少一个"的半成品。"""
    calls = {"n": 0}

    def _store(skill_id, name, data, content_type="text/plain"):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("MinIO 挂了")
        return {"name": name, "type": "file", "object": f"skills/{skill_id}/{name}", "size": len(data)}

    monkeypatch.setattr("app.api.v1.skills.skill_resource.store_file", _store)
    monkeypatch.setattr("app.api.v1.skills.skill_resource.drop_file", lambda obj: None)
    fake_fetch["result"] = _payload(files=[
        {"name": "a.py", "content": b"1"}, {"name": "b.py", "content": b"2"},
    ])

    unique = "pytest-gh-" + uuid.uuid4().hex[:8]
    res = client.post("/api/v1/skills/import-github/commit", headers=auth_headers, json={
        "url": "https://github.com/owner/repo/tree/main/x",
        "name": unique, "display_name": "T", "description": "D",
    })
    assert res.status_code == 500
    # 技能不该留下
    rows = client.get("/api/v1/skills", headers=auth_headers, params={"q": unique}).json()
    assert rows["total"] == 0, "失败后不应留下半成品技能"


def test_commit_rejects_too_many_resources(client, auth_headers, fake_fetch):
    fake_fetch["result"] = _payload(files=[{"name": f"f{i}.py", "content": b"1"} for i in range(25)])
    res = client.post("/api/v1/skills/import-github/commit", headers=auth_headers, json={
        "url": "https://github.com/owner/repo/tree/main/x",
        "name": "pytest-gh-many", "display_name": "T", "description": "D",
    })
    assert res.status_code == 400
    assert "最多支持" in res.json()["detail"]


def test_commit_rejects_duplicate_name(client, auth_headers, fake_fetch, monkeypatch):
    """重名 409：与手填同一个口径，导入不是绕过点。"""
    monkeypatch.setattr("app.api.v1.skills.skill_resource.store_file",
                        lambda *a, **kw: {"name": a[1], "type": "file", "object": "x", "size": 1})
    fake_fetch["result"] = _payload()
    unique = "pytest-gh-" + uuid.uuid4().hex[:8]

    first = client.post("/api/v1/skills/import-github/commit", headers=auth_headers, json={
        "url": "https://github.com/owner/repo/tree/main/x",
        "name": unique, "display_name": "T", "description": "D",
    })
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/skills/import-github/commit", headers=auth_headers, json={
        "url": "https://github.com/owner/repo/tree/main/x",
        "name": unique, "display_name": "T2", "description": "D2",
    })
    assert second.status_code == 409
    client.delete(f"/api/v1/skills/{first.json()['id']}", headers=auth_headers)
