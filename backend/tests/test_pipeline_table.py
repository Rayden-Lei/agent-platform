"""入库管道（2026-09-06，为导入 11 万行药品说明书表格而改）：表格超长行按字段切分并带行标识；向量化与写库逐批提交。

不连 MinIO、不调向量模型：下载 / 解析 / 向量化都打桩，只用开发库里的知识库与文档行。
"""
import math

import pytest

from app.config import settings
from app.db.models import Document, DocumentChunk, KnowledgeBase
from app.db.session import SessionLocal
from app.rag import pipeline
from app.rag.embeddings import EmbeddingResult
from app.services import settings_service

ROW_META = {"type": "table", "row": 2}


def _row(fields: dict) -> dict:
    return {"content": " | ".join(f"{k}: {v}" for k, v in fields.items()), "meta": ROW_META}


def test_short_row_stays_one_chunk():
    seg = _row({"标题": "阿司匹林片", "规格": "100mg"})
    assert pipeline.split_table_row(seg, 500, 50) == [{"content": seg["content"], "meta": ROW_META}]


def test_long_row_splits_on_field_boundaries_with_key_prefix():
    seg = _row({"标题": "紫杉醇注射液", "适应症": "卵巢癌" * 60, "用法用量": "静脉滴注" * 50, "禁忌": "过敏者禁用" * 40, "贮藏": "遮光"})
    pieces = pipeline.split_table_row(seg, 400, 20)
    assert len(pieces) >= 3
    for n, p in enumerate(pieces, start=1):
        assert p["content"].startswith("标题: 紫杉醇注射液")  # 每片都带行标识，单独可读
        assert p["meta"] == {**ROW_META, "part": n}
        assert len(p["content"]) <= 400 + 40  # 允许分片器少量溢出
    # 字段不被从中间切断：每片里的字段名都完整
    assert all(" | 适应症: " in p["content"] or "适应症" not in p["content"] for p in pieces)
    joined = "".join(p["content"] for p in pieces)
    assert "用法用量: " in joined and "禁忌: " in joined and "贮藏: 遮光" in joined


def test_single_oversized_field_is_split_with_continuation_label():
    seg = _row({"标题": "某注射液", "注意事项": "本品应在医师指导下使用。" * 80})
    pieces = pipeline.split_table_row(seg, 300, 30)
    assert len(pieces) >= 3
    assert pieces[0]["content"].startswith("标题: 某注射液 | 注意事项: ")
    assert all(p["content"].startswith("标题: 某注射液 | 注意事项(续): ") for p in pieces[1:])
    assert all(len(p["content"]) <= 300 + 30 for p in pieces)


def test_table_chunking_uses_row_splitter(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "split_table_row", lambda seg, cs, co: (seen.append(seg) or [{"content": seg["content"], "meta": seg["meta"]}]))
    segs = [_row({"a": "1"}), _row({"a": "2"})]
    assert len(pipeline.chunk_segments(segs, "xlsx", 500, 50)) == 2 and len(seen) == 2


@pytest.fixture
def ingest_opts(monkeypatch):
    """固定住本次入库用的参数，绕开 system_settings 表。

    开发库是共享的：使用者可能在页面上调过并发或批大小，用例不能受它影响，更不能去改它
    （2026-09-06 教训）。参数从库到管道的链路由 test_ingest_settings_from_page_take_effect 单独验证。
    默认给串行（并发 1、无缓冲），断言批次顺序与"第几批失败"的用例需要这个确定性。
    """
    def _set(batch_size=100, embed_concurrency=1, write_buffer=0, embedding_request_size=20):
        opts = settings_service.IngestOptions(
            batch_size=batch_size, embed_concurrency=embed_concurrency,
            write_buffer=write_buffer, embedding_request_size=embedding_request_size)
        monkeypatch.setattr(settings_service, "ingest_options", lambda db: opts)
        return opts

    return _set


@pytest.fixture
def kb_doc(client, auth_headers):
    """一条待处理的文档行（不真的上传文件）。"""
    kb_id = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-pipeline-kb", "chunk_size": 200, "chunk_overlap": 10}).json()["id"]
    db = SessionLocal()
    try:
        doc = Document(kb_id=kb_id, name="pytest.xlsx", file_type="xlsx", file_path="pytest/none", status="uploading")
        db.add(doc)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()
    try:
        yield kb_id, doc_id
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)


def test_ingestion_commits_in_batches_and_tracks_progress(monkeypatch, kb_doc, ingest_opts):
    kb_id, doc_id = kb_doc
    total = 250
    ingest_opts(batch_size=100)
    monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": f"标题: 药品{i} | 规格: {i}mg", "meta": {"type": "table", "row": i + 2}} for i in range(total)])
    batches: list = []

    def _embed(texts, request_size=None):
        batches.append(len(texts))
        return EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)

    monkeypatch.setattr(pipeline, "embed_texts_detailed", _embed)
    pipeline.process_document(doc_id)
    assert batches == [100, 100, 50]  # 逐批向量化，不是一次全量
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        assert doc.status == "ready" and doc.chunk_count == total and doc.error is None
        # 进度字段：计划总数、起止时间都落库，列表页据此显示进度与耗时
        assert doc.chunk_total == total and doc.processing_started_at is not None and doc.finished_at is not None
        assert doc.finished_at >= doc.processing_started_at
        rows = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).order_by(DocumentChunk.id).all()
        assert len(rows) == total
        assert [r.meta["index"] for r in rows] == list(range(total))  # 全局序号跨批连续
        assert rows[0].meta["embedding_mode"] == "model" and rows[0].meta["row"] == 2
    finally:
        db.close()


def test_ingestion_failure_mid_way_keeps_committed_batches_and_marks_failed(monkeypatch, kb_doc, ingest_opts):
    kb_id, doc_id = kb_doc
    ingest_opts(batch_size=10)
    monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": f"标题: 药品{i}", "meta": {"type": "table", "row": i + 2}} for i in range(35)])
    calls = {"n": 0}

    def _embed(texts, request_size=None):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("向量服务断了")
        return EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)

    monkeypatch.setattr(pipeline, "embed_texts_detailed", _embed)
    pipeline.process_document(doc_id)
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        assert doc.status == "failed" and "向量服务断了" in doc.error
        assert db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).count() == 20  # 前两批已提交
        assert doc.chunk_count == 20 and doc.chunk_total == 35 and doc.finished_at is not None
    finally:
        db.close()
    assert math.ceil(35 / 10) == 4 and calls["n"] == 3


def test_documents_are_processed_one_at_a_time(monkeypatch, client, auth_headers):
    """两篇同时进入后台：INGEST_CONCURRENCY=1 时第二篇要等第一篇向量化结束才开始。"""
    import threading
    import time as _time

    monkeypatch.setattr(settings, "INGEST_CONCURRENCY", 1)
    monkeypatch.setattr(pipeline, "_ingest_slots", None)
    kb_id = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-queue-kb", "chunk_size": 200, "chunk_overlap": 0}).json()["id"]
    db = SessionLocal()
    try:
        docs = [Document(kb_id=kb_id, name=f"q{i}.txt", file_type="txt", file_path="pytest/none", status="uploading") for i in range(2)]
        db.add_all(docs)
        db.commit()
        ids = [d.id for d in docs]
    finally:
        db.close()
    windows: dict = {}

    def _embed(texts, request_size=None):
        start = _time.perf_counter()
        _time.sleep(0.4)
        windows[threading.get_ident()] = (start, _time.perf_counter())
        return EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)

    monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": "一段文本", "meta": {}}])
    monkeypatch.setattr(pipeline, "embed_texts_detailed", _embed)
    try:
        threads = [threading.Thread(target=pipeline.process_document, args=(i,)) for i in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        (a0, a1), (b0, b1) = sorted(windows.values())
        assert b0 >= a1  # 第二篇的向量化在第一篇结束之后才开始
        db = SessionLocal()
        try:
            assert {db.get(Document, i).status for i in ids} == {"ready"}
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)


def test_queued_document_keeps_heartbeat_while_waiting(monkeypatch, client, auth_headers):
    """排在别的文档后面等待时也要刷心跳：排队时间超过 INGEST_STALL_SECONDS 不能被判成"中断"，
    否则用户点"继续处理"会给同一篇再排一个任务，前一个做完后后一个把切片清掉重做。"""
    import threading
    import time as _time
    from datetime import datetime, timedelta, timezone

    from app.services.kb_service import is_stalled

    monkeypatch.setattr(settings, "INGEST_CONCURRENCY", 1)
    monkeypatch.setattr(settings, "INGEST_STALL_SECONDS", 2)  # 阈值 2 秒：排队 3 秒就"过期"
    monkeypatch.setattr(pipeline, "_ingest_slots", None)
    monkeypatch.setattr(pipeline, "QUEUE_HEARTBEAT_SECONDS", 0.2)
    kb_id = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-queue-heartbeat-kb", "chunk_size": 200, "chunk_overlap": 0}).json()["id"]
    db = SessionLocal()
    try:
        docs = [Document(kb_id=kb_id, name=f"hb{i}.txt", file_type="txt", file_path="pytest/none", status="uploading") for i in range(2)]
        db.add_all(docs)
        db.commit()
        first_id, queued_id = [d.id for d in docs]
    finally:
        db.close()

    def _slow_embed(texts, request_size=None):
        _time.sleep(4.0)  # 第一篇占住闸门 4 秒，第二篇在这期间一直排队
        return EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)

    monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": "一段文本", "meta": {}}])
    monkeypatch.setattr(pipeline, "embed_texts_detailed", _slow_embed)
    try:
        first = threading.Thread(target=pipeline.process_document, args=(first_id,))
        first.start()
        for _ in range(50):  # 等第一篇真正占住闸门（状态离开 uploading）再放第二篇进队
            db = SessionLocal()
            try:
                if db.get(Document, first_id).status != "uploading":
                    break
            finally:
                db.close()
            _time.sleep(0.1)
        queued = threading.Thread(target=pipeline.process_document, args=(queued_id,))
        queued.start()
        _time.sleep(3.0)  # 已超过阈值，仍在排队
        db = SessionLocal()
        try:
            doc = db.get(Document, queued_id)
            assert doc.status == "uploading"  # 还没轮到它
            assert doc.heartbeat_at is not None and datetime.now(timezone.utc) - doc.heartbeat_at < timedelta(seconds=2)
            assert is_stalled(doc) is False
        finally:
            db.close()
        first.join(30)
        queued.join(30)
        db = SessionLocal()
        try:
            assert {db.get(Document, i).status for i in (first_id, queued_id)} == {"ready"}
        finally:
            db.close()
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)


def test_resume_continues_from_committed_batches_without_duplicates(monkeypatch, kb_doc, ingest_opts):
    """向量化中途失败 → 续处理只补剩下的批，切片不重复、序号连续，resume_offset 记起点。"""
    kb_id, doc_id = kb_doc
    total = 35
    ingest_opts(batch_size=10)
    monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": f"标题: 药品{i}", "meta": {"type": "table", "row": i + 2}} for i in range(total)])
    calls = {"n": 0}

    def _embed_then_fail(texts, request_size=None):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("向量服务断了")
        return EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)

    monkeypatch.setattr(pipeline, "embed_texts_detailed", _embed_then_fail)
    pipeline.process_document(doc_id)
    sizes: list = []
    monkeypatch.setattr(pipeline, "embed_texts_detailed", lambda texts, request_size=None: (sizes.append(len(texts)) or EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)))
    pipeline.process_document(doc_id, resume=True)
    assert sizes == [10, 5]  # 只补 20 之后的 15 片
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        assert doc.status == "ready" and doc.chunk_count == total and doc.chunk_total == total and doc.resume_offset == 20
        assert doc.heartbeat_at is not None and doc.processing_node == pipeline.NODE_NAME
        rows = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).order_by(DocumentChunk.id).all()
        assert [r.meta["index"] for r in rows] == list(range(total))
    finally:
        db.close()


def test_resume_restarts_when_chunk_total_changed(monkeypatch, kb_doc, ingest_opts):
    """切片参数改了导致总数不一致：续处理清掉旧切片从 0 开始，不会拼出错位的切片。"""
    kb_id, doc_id = kb_doc
    ingest_opts(batch_size=10)
    monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": f"标题: 药品{i}", "meta": {}} for i in range(30)])
    calls = {"n": 0}

    def _embed_then_fail(texts, request_size=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("断")
        return EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)

    monkeypatch.setattr(pipeline, "embed_texts_detailed", _embed_then_fail)
    pipeline.process_document(doc_id)  # 落了 10 片，chunk_total=30
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": f"标题: 药品{i}", "meta": {}} for i in range(25)])  # 总数变了
    sizes: list = []
    monkeypatch.setattr(pipeline, "embed_texts_detailed", lambda texts, request_size=None: (sizes.append(len(texts)) or EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)))
    pipeline.process_document(doc_id, resume=True)
    assert sizes == [10, 10, 5]  # 从头重做
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        assert doc.status == "ready" and doc.chunk_count == 25 and doc.resume_offset == 0
        assert db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).count() == 25
    finally:
        db.close()


def test_resume_api_rejects_live_processing_and_accepts_failed_or_stalled(client, auth_headers, kb_doc, monkeypatch):
    from datetime import datetime, timedelta, timezone

    kb_id, doc_id = kb_doc
    monkeypatch.setattr(pipeline, "process_document", lambda doc_id, resume=False: None)  # 路由只排队，不真处理
    monkeypatch.setattr("app.api.v1.kb.process_document", lambda doc_id, resume=False: None)
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        doc.status, doc.heartbeat_at, doc.chunk_total, doc.chunk_count = "chunking", datetime.now(timezone.utc), 100, 30
        db.commit()
    finally:
        db.close()
    r = client.post(f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/resume", headers=auth_headers)
    assert r.status_code == 400 and "正在处理" in r.json()["detail"]  # 心跳新鲜：正在处理，不能续
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        doc.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        db.commit()
    finally:
        db.close()
    r = client.post(f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/resume", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "uploading" and r.json()["chunk_count"] == 30  # 无心跳：视为中断，可续
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        doc.status = "failed"
        db.commit()
    finally:
        db.close()
    assert client.post(f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/resume", headers=auth_headers).status_code == 200
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        doc.status = "ready"
        db.commit()
    finally:
        db.close()
    assert client.post(f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/resume", headers=auth_headers).status_code == 400  # 已完成的走重新解析


def test_startup_resume_skips_other_nodes_and_live_documents(client, auth_headers):
    """启动自动续处理只挑"确实断了"的：别的节点的、已完成的、以及**心跳还在跳的**都不能碰。

    最后一条是 2026-09-06 的事故回归用例：同一台机器上跑 pytest 时，进程启动把用户正在导入的文档抢过去，
    按测试桩重新解析后总数对不上，删掉了 1.9 万片真实切片。"""
    from datetime import datetime, timedelta, timezone

    kb_id = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-resume-kb", "chunk_size": 200, "chunk_overlap": 0}).json()["id"]
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        mine = Document(kb_id=kb_id, name="mine.txt", file_type="txt", file_path="pytest/none", status="chunking",
                        processing_node=pipeline.NODE_NAME, heartbeat_at=now - timedelta(seconds=settings.INGEST_STALL_SECONDS + 60))
        live = Document(kb_id=kb_id, name="live.txt", file_type="txt", file_path="pytest/none", status="chunking",
                        processing_node=pipeline.NODE_NAME, heartbeat_at=now)  # 另一个进程正在写
        other = Document(kb_id=kb_id, name="other.txt", file_type="txt", file_path="pytest/none", status="chunking", processing_node="another-host")
        done = Document(kb_id=kb_id, name="done.txt", file_type="txt", file_path="pytest/none", status="ready", processing_node=pipeline.NODE_NAME)
        db.add_all([mine, live, other, done])
        db.commit()
        mine_id, live_id, other_id, done_id = mine.id, live.id, other.id, done.id
    finally:
        db.close()
    scheduled: list = []
    try:
        ids = pipeline.resume_stalled_documents(scheduled.append)
        assert mine_id in ids and scheduled.count(mine_id) == 1  # 心跳早就停了：确实中断，续
        assert live_id not in ids and live_id not in scheduled  # 心跳新鲜：有活着的进程在写，不许抢
        assert other_id not in ids and done_id not in ids  # 别的节点的、已完成的都不碰
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)


def _parallel_embed_stub(sleep_seconds: float = 0.15):
    """向量化打桩：记录每次调用的并发峰值与批大小，返回 (stub, 统计字典)。"""
    import threading
    import time as _time

    state = {"running": 0, "peak": 0, "sizes": [], "lock": threading.Lock()}

    def _embed(texts, request_size=None):
        with state["lock"]:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
            state["sizes"].append((len(texts), request_size))
        try:
            _time.sleep(sleep_seconds)
            return EmbeddingResult([[0.0] * 1024 for _ in texts], "model", "pytest-embed", 1024)
        finally:
            with state["lock"]:
                state["running"] -= 1

    return _embed, state


def test_embedding_requests_run_in_parallel_and_writes_stay_ordered(monkeypatch, kb_doc, ingest_opts):
    """并发向量化：多个请求同时在飞，但写库仍按批次顺序提交 —— 续处理靠"已入库片数"当起点，乱序会算错缺口。"""
    kb_id, doc_id = kb_doc
    total = 80
    ingest_opts(batch_size=10, embed_concurrency=4, write_buffer=4, embedding_request_size=25)
    monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
    monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": f"标题: 药品{i}", "meta": {"type": "table", "row": i + 2}} for i in range(total)])
    stub, state = _parallel_embed_stub()
    monkeypatch.setattr(pipeline, "embed_texts_detailed", stub)

    pipeline.process_document(doc_id)

    assert state["peak"] >= 2, "并发参数没生效，仍是一次只发一个请求"
    assert state["peak"] <= 4, "在飞的向量化请求数超过了配置的并发数"
    assert {size for size, _ in state["sizes"]} == {10}  # 每批 10 片
    assert {req for _, req in state["sizes"]} == {25}  # 每次请求条数按配置透传给向量化
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        assert doc.status == "ready" and doc.chunk_count == total
        rows = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).order_by(DocumentChunk.id).all()
        # 按写入顺序（id 递增）读出来，切片序号必须是 0..total-1：说明并发向量化后仍是顺序提交
        assert [r.meta["index"] for r in rows] == list(range(total))
    finally:
        db.close()


def test_ingest_settings_from_page_take_effect(monkeypatch, client, auth_headers, kb_doc):
    """页面改的参数存进 system_settings，下一篇文档处理时立刻按新值跑（不用重启后端）。

    这条用例走真实的库读取路径，所以不能用 ingest_opts 打桩。改完必须**还原成运行前的样子**：
    使用者可能正按自己调的参数导入，既不能留下测试值，也不能一律清空（2026-09-06 抹掉过使用者刚设的值）。
    """
    from app.db.models import SystemSetting

    kb_id, doc_id = kb_doc
    monkeypatch.setattr(settings, "INGEST_EMBED_CONCURRENCY", 8)  # .env 默认值，应当被库里的 1 覆盖
    keys = ("ingest_embed_concurrency", "ingest_write_buffer", "ingest_batch_size")
    db = SessionLocal()
    try:
        before = {r.key: r.value for r in db.query(SystemSetting).filter(SystemSetting.key.in_(keys)).all()}
    finally:
        db.close()
    r = client.put("/api/v1/system/settings", headers=auth_headers,
                   json={"values": {"ingest_embed_concurrency": 1, "ingest_write_buffer": 0, "ingest_batch_size": 10}})
    assert r.status_code == 200, r.text
    try:
        monkeypatch.setattr(pipeline, "download_file", lambda remote, local: open(local, "w").close())
        monkeypatch.setattr(pipeline, "parse_document", lambda path, ft: [{"content": f"标题: 药品{i}", "meta": {}} for i in range(40)])
        stub, state = _parallel_embed_stub(sleep_seconds=0.05)
        monkeypatch.setattr(pipeline, "embed_texts_detailed", stub)
        pipeline.process_document(doc_id)
        assert state["peak"] == 1  # 库里的并发 1 生效，而不是 .env 的 8
        assert {size for size, _ in state["sizes"]} == {10}  # 批大小同样来自库
    finally:
        # None = 删掉该行；原来就有值的写回原值
        client.put("/api/v1/system/settings", headers=auth_headers,
                   json={"values": {k: before.get(k) for k in keys}})
