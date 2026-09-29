"""上传与入参收口（docs/15 KB-03，AC-031）：文件名清洗、处理时的本地路径不出临时目录、扩展名白名单、大小上限、入参约束。

对象存储一律打桩（upload_file / download_file），后台处理用空函数替掉，不向量化、不碰 MinIO。
"""
import os
import tempfile
import uuid

import pytest

from app.api.v1 import kb as kb_route
from app.config import settings
from app.db.models import Document
from app.db.session import SessionLocal
from app.rag import pipeline
from app.services import kb_service


def _uid() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture
def kb(client, auth_headers):
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-upload-" + _uid(), "chunk_size": 200, "chunk_overlap": 20})
    assert r.status_code == 200, r.text
    yield r.json()
    client.delete(f"/api/v1/knowledge-bases/{r.json()['id']}", headers=auth_headers)


@pytest.fixture
def stored(monkeypatch) -> list:
    """对象存储与后台处理打桩：记下上传了哪些对象，后台处理不跑。"""
    uploads: list = []
    monkeypatch.setattr(kb_service, "upload_file", lambda name, data, ctype: uploads.append((name, len(data))))
    monkeypatch.setattr(kb_route, "process_document", lambda doc_id: None)
    return uploads


def _upload(client, auth_headers, kb_id: int, filename: str, data: bytes = b"hello"):
    return client.post(f"/api/v1/knowledge-bases/{kb_id}/documents", headers=auth_headers, files={"file": (filename, data, "application/octet-stream")})


def _doc_names(kb_id: int) -> list[str]:
    db = SessionLocal()
    try:
        return [d.name for d in db.query(Document).filter(Document.kb_id == kb_id)]
    finally:
        db.close()


@pytest.mark.parametrize("filename,expected", [
    ("/tmp/pytest-evil-{uid}.txt", "pytest-evil-{uid}.txt"),
    ("..\\..\\dir\\pytest-evil-{uid}.txt", "pytest-evil-{uid}.txt"),
])
def test_uploaded_filename_keeps_only_the_last_segment(client, auth_headers, kb, stored, filename, expected):
    uid = _uid()
    r = _upload(client, auth_headers, kb["id"], filename.format(uid=uid))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == expected.format(uid=uid) and _doc_names(kb["id"]) == [expected.format(uid=uid)]
    assert stored[0][0].endswith("_" + expected.format(uid=uid))  # 对象名也用清洗后的名字


def test_filename_cleaning_strips_control_chars_and_keeps_extension_when_cut():
    """控制字符走不到 HTTP 这层（客户端会转义），直接测清洗函数。"""
    assert kb_service.safe_filename("pytest-\x00ctrl\x1f.md") == "pytest-ctrl.md"
    name = kb_service.safe_filename("字" * 300 + ".xlsx")
    assert len(name) == kb_service.FILENAME_MAX_CHARS and name.endswith(".xlsx")
    assert kb_service.safe_filename("  /  ") == "unnamed"


def _legacy_doc(kb_id: int, name: str, file_type: str) -> int:
    """模拟 2026-09-29 前入库、名字与类型都没清洗过的存量文档（直接写库）。"""
    db = SessionLocal()
    try:
        doc = Document(kb_id=kb_id, name=name, file_path="pytest-none", file_type=file_type, status="uploading")
        db.add(doc)
        db.commit()
        return doc.id
    finally:
        db.close()


def _status_and_error(doc_id: int) -> tuple:
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        return doc.status, doc.error or ""
    finally:
        db.close()


def _record_download(monkeypatch) -> list:
    """下载桩：像真实下载一样把文件写到给定路径，然后抛错让处理就此停下（不做向量化）。"""
    written: list = []

    def _download(remote, local):
        written.append(local)
        with open(local, "w") as f:
            f.write("x")
        raise RuntimeError("桩：下载完就停")

    monkeypatch.setattr(pipeline, "download_file", _download)
    return written


def test_legacy_absolute_name_is_processed_inside_the_temp_dir(kb, monkeypatch):
    outside = f"/tmp/pytest-legacy-{_uid()}.txt"
    written = _record_download(monkeypatch)
    doc_id = _legacy_doc(kb["id"], outside, "txt")
    pipeline.process_document(doc_id)
    assert not os.path.exists(outside)  # 修复前 join(tmp, "/tmp/…") 丢掉 tmp，文件就写在这里
    assert len(written) == 1 and os.path.basename(written[0]) == "source.txt"
    assert os.path.dirname(os.path.realpath(written[0])) != os.path.realpath(tempfile.gettempdir())  # 在 mkdtemp 建的子目录里


def test_legacy_type_that_escapes_the_temp_dir_fails_without_writing(kb, monkeypatch):
    written = _record_download(monkeypatch)
    doc_id = _legacy_doc(kb["id"], "pytest-legacy.txt", "x/../../../../y")  # file_type 列最长 16
    pipeline.process_document(doc_id)
    status, error = _status_and_error(doc_id)
    assert written == [] and status == "failed" and "文件类型不合法" in error


@pytest.mark.parametrize("filename,detail", [
    ("pytest-bad.exe", "不支持的文件类型（.exe）"),
    ("pytest-old.xls", "请另存为 .xlsx"),
    ("pytest-noext", "没有扩展名"),
])
def test_unsupported_types_are_rejected_before_storing(client, auth_headers, kb, stored, filename, detail):
    r = _upload(client, auth_headers, kb["id"], filename)
    assert r.status_code == 400 and detail in r.json()["detail"]
    assert stored == [] and _doc_names(kb["id"]) == []


def test_size_limit_is_413_before_storing(client, auth_headers, kb, stored, monkeypatch):
    monkeypatch.setattr(settings, "KB_UPLOAD_MAX_MB", 1)
    assert _upload(client, auth_headers, kb["id"], "pytest-edge.txt", b"x" * 1024 * 1024).status_code == 200  # 正好 1MB 放行
    r = _upload(client, auth_headers, kb["id"], "pytest-big.txt", b"x" * (1024 * 1024 + 1))
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    assert len(stored) == 1 and _doc_names(kb["id"]) == ["pytest-edge.txt"]


def test_empty_file_is_400(client, auth_headers, kb, stored):
    r = _upload(client, auth_headers, kb["id"], "pytest-empty.txt", b"")
    assert r.status_code == 400 and r.json()["detail"] == "文件是空的" and stored == []


def test_upload_policy_matches_the_server_rules(client, auth_headers):
    policy = client.get("/api/v1/knowledge-bases/upload-policy", headers=auth_headers).json()
    assert policy == {"extensions": list(kb_service.UPLOAD_EXTENSIONS), "max_mb": settings.KB_UPLOAD_MAX_MB}
    assert "xls" not in policy["extensions"]


@pytest.mark.parametrize("body", [
    {"chunk_size": 500, "chunk_overlap": 600},
    {"chunk_size": 500, "chunk_overlap": 500},
    {"chunk_size": 20},
    {"visible_roles": ["boss"]},
    {"name": ""},
    {"name": "字" * 129},
])
def test_kb_fields_out_of_range_are_422(client, auth_headers, body):
    r = client.post("/api/v1/knowledge-bases", headers=auth_headers, json={"name": "pytest-kb-422-" + _uid(), **body})
    if r.status_code == 200:  # 修复前会落库：先删掉再让断言失败，不在共享库留数据
        client.delete(f"/api/v1/knowledge-bases/{r.json()['id']}", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.parametrize("body", [{"query": "x", "top_k": 500}, {"query": "x", "top_k": 0}, {"query": ""}, {"query": "字" * 1001}])
def test_search_params_out_of_range_are_422(client, auth_headers, kb, body):
    assert client.post(f"/api/v1/knowledge-bases/{kb['id']}/search", headers=auth_headers, json=body).status_code == 422
