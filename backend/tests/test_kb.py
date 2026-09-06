def test_kb_crud(client, auth_headers):
    k = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={
        "name": "pytest-kb", "description": "", "embedding_model": "embedding-3", "chunk_size": 200, "chunk_overlap": 20,
    })
    assert k.status_code == 200, k.text
    kid = k.json()["id"]

    l = client.get("/api/v1/knowledge-bases", headers=auth_headers)
    assert l.status_code == 200
    assert any(x["id"] == kid for x in l.json()["items"])

    d = client.delete(f"/api/v1/knowledge-bases/{kid}", headers=auth_headers)
    assert d.status_code == 200


def test_upload_does_not_block_event_loop(monkeypatch, client, auth_headers):
    """上传大文件期间事件循环必须保持可用。

    2026-09-06 的真实故障：上传路由是 async def 却在里面直接做阻塞的 MinIO 上传，
    一次上传重试到 436 秒，期间整个后端不处理任何请求，页面看着像服务挂了。

    判据是**并发协程被唤醒的时刻**：让一个协程睡 0.3 秒后记时间。
    循环没被占住时它准点醒（约 0.3 秒）；阻塞 IO 跑在循环上时，它要等阻塞结束才醒（实测 2.4 秒）。
    不能用"谁先返回"当判据 —— 阻塞版里健康检查醒来后反而先于上传返回，那样测不出问题（试过）。
    """
    import asyncio
    import time

    import httpx

    from app.api.v1 import kb as kb_router
    from app.main import app
    from app.services import kb_service

    kb_id = client.post("/api/v1/knowledge-bases", headers=auth_headers,
                        json={"name": "pytest-upload-block-kb", "chunk_size": 200, "chunk_overlap": 0}).json()["id"]
    monkeypatch.setattr(kb_service, "upload_file", lambda name, data, ctype: time.sleep(1.5))  # 阻塞 IO 替身
    monkeypatch.setattr(kb_router, "process_document", lambda doc_id, resume=False: None)  # 不真的入库

    async def _scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            started = time.perf_counter()

            async def _upload():
                return await ac.post(f"/api/v1/knowledge-bases/{kb_id}/documents", headers=auth_headers,
                                     files={"file": ("pytest-slow.txt", b"x" * 1024, "text/plain")}, timeout=30)

            async def _health():
                await asyncio.sleep(0.3)  # 上传此时已进入阻塞段
                woke = time.perf_counter() - started
                return await ac.get("/health", timeout=10), woke

            uploaded, (health, woke) = await asyncio.gather(_upload(), _health())
            return uploaded, health, woke

    try:
        uploaded, health, woke = asyncio.run(_scenario())
        assert uploaded.status_code == 200, uploaded.text
        assert health.status_code == 200
        assert woke < 1.0, f"并发协程被饿了 {woke:.2f} 秒才唤醒：阻塞 IO 跑在了事件循环上"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
