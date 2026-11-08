"""文档解析器（app/rag/parser.py）的直测。

扫描时发现这个模块**六个解析函数全部零引用** —— 只在 test_pipeline_table 里被间接经过一次。
它是文档处理的核心：解析出来的分片质量直接决定检索质量，而各类型的规则完全不同
（PDF 按页、Word 保留标题、表格保留列名与行号）。写错了不会报错，只会检索不到。

本文件全部用临时文件造样本，不碰对象存储、不碰数据库。
"""
from __future__ import annotations

import csv
import subprocess

import pytest

from app.rag import parser


# --------------------------------------------------------------------------- 分派

def test_parse_document_dispatches_by_extension(tmp_path):
    """.md 与 .markdown、.jpg 与 .jpeg 都要认；扩展名大小写与前置点号不影响。"""
    f = tmp_path / "a.md"
    f.write_text("# 标题\n正文", encoding="utf-8")
    assert parser.parse_document(str(f), "md")[0]["meta"]["type"] == "markdown"
    assert parser.parse_document(str(f), ".MD")[0]["meta"]["type"] == "markdown"
    assert parser.parse_document(str(f), "markdown")[0]["meta"]["type"] == "markdown"


def test_parse_document_rejects_unknown_type(tmp_path):
    """不认识的后缀要明确报错，不能静默返回空 —— 静默返回空会让文档"处理成功但没有切片"。"""
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    with pytest.raises(ValueError) as ei:
        parser.parse_document(str(f), "bin")
    assert "不支持" in str(ei.value)


# --------------------------------------------------------------------------- 纯文本 / Markdown

def test_parse_text_returns_single_chunk(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("第一行\n第二行", encoding="utf-8")
    chunks = parser.parse_text(str(f))
    assert len(chunks) == 1
    assert chunks[0]["content"] == "第一行\n第二行"
    assert chunks[0]["meta"] == {"type": "text"}


def test_parse_text_keeps_chinese_intact(tmp_path):
    """中文不能被编码问题糟蹋 —— 整条 RAG 链路都假设入库的是正确 UTF-8。"""
    f = tmp_path / "cn.txt"
    f.write_text("知识库检索增强生成", encoding="utf-8")
    assert parser.parse_text(str(f))[0]["content"] == "知识库检索增强生成"


def test_parse_markdown_single_chunk(tmp_path):
    """Markdown 整篇一个片段（按标题切分是分片阶段的事，不在这里）。"""
    f = tmp_path / "a.md"
    f.write_text("# 一级\n\n## 二级\n内容", encoding="utf-8")
    chunks = parser.parse_markdown(str(f))
    assert len(chunks) == 1
    assert chunks[0]["meta"]["type"] == "markdown"
    assert "二级" in chunks[0]["content"]


# --------------------------------------------------------------------------- PDF

def test_parse_pdf_records_page_numbers(tmp_path):
    """PDF 按页返回，page 从 1 起 —— 引用出处要能定位到页。"""
    pypdf = pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "a.pdf"
    with open(path, "wb") as fh:
        writer.write(fh)

    chunks = parser.parse_pdf(str(path))
    # 空白页没有文本 → 全部跳过，返回一个占位片段（避免"0 片段"被当成解析失败）
    assert len(chunks) == 1
    assert chunks[0]["content"] == ""
    assert chunks[0]["meta"]["type"] == "pdf"


def test_parse_pdf_never_returns_empty_list(tmp_path):
    """即使一页文本都提不出来也要返回占位片段：空列表会让上层把文档标成"解析失败"，
    而实际是"解析成功但没内容"，两者含义不同。"""
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    path = tmp_path / "blank.pdf"
    with open(path, "wb") as fh:
        writer.write(fh)
    assert parser.parse_pdf(str(path)) != []


# --------------------------------------------------------------------------- Word

def test_parse_docx_carries_nearest_heading(tmp_path):
    """Word 的每个段落要带上最近的标题 —— 分片时靠它保留上下文。

    没有 heading 的话，把一篇长文档切成十片后，每片都不知道自己属于哪一节。
    """
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("第一章 总则", style="Heading 1")
    d.add_paragraph("正文第一段")
    d.add_paragraph("正文第二段")
    d.add_paragraph("第二章 细则", style="Heading 1")
    d.add_paragraph("正文第三段")
    path = tmp_path / "a.docx"
    d.save(str(path))

    chunks = parser.parse_docx(str(path))
    assert len(chunks) == 5
    # 标题段落自己也算片段，heading 指向自己
    assert chunks[0]["meta"]["heading"] == "第一章 总则"
    # 正文段落继承最近的标题
    assert chunks[1]["meta"]["heading"] == "第一章 总则"
    assert chunks[2]["meta"]["heading"] == "第一章 总则"
    assert chunks[3]["meta"]["heading"] == "第二章 细则"
    assert chunks[4]["meta"]["heading"] == "第二章 细则"
    assert all(c["meta"]["type"] == "docx" for c in chunks)


def test_parse_docx_skips_blank_paragraphs(tmp_path):
    """空段落不产生片段：它们会变成空切片污染检索结果。"""
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("有内容")
    d.add_paragraph("   ")
    d.add_paragraph("")
    d.add_paragraph("还有内容")
    path = tmp_path / "b.docx"
    d.save(str(path))
    chunks = parser.parse_docx(str(path))
    assert [c["content"] for c in chunks] == ["有内容", "还有内容"]


def test_parse_docx_empty_document_returns_placeholder(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    path = tmp_path / "c.docx"
    d.save(str(path))
    chunks = parser.parse_docx(str(path))
    assert len(chunks) == 1
    assert chunks[0]["content"] == ""


# --------------------------------------------------------------------------- 表格

def test_parse_csv_keeps_column_names_and_row_numbers(tmp_path):
    """表格每行拼成「列名: 值」，并记录行号（从 2 起，1 是表头）。

    带列名是为了让切片自解释："张三 | 30" 离开表头就是两个孤立的词；
    "姓名: 张三 | 年龄: 30" 才能被检索到、也才能被模型读懂。
    """
    f = tmp_path / "t.csv"
    f.write_text("姓名,年龄,城市\n张三,30,北京\n李四,25,上海\n", encoding="utf-8")
    chunks = parser.parse_table(str(f), "csv")
    assert len(chunks) == 2
    assert chunks[0]["content"] == "姓名: 张三 | 年龄: 30 | 城市: 北京"
    assert chunks[0]["meta"] == {"type": "table", "row": 2}
    assert chunks[1]["meta"]["row"] == 3


def test_parse_csv_skips_rows_without_values(tmp_path):
    """整行都空的不产生片段。"""
    f = tmp_path / "e.csv"
    f.write_text("a,b\n,\n1,2\n", encoding="utf-8")
    chunks = parser.parse_table(str(f), "csv")
    assert len(chunks) == 1
    assert chunks[0]["meta"]["row"] == 3


def test_parse_csv_handles_bom(tmp_path):
    """带 BOM 的 CSV（Excel 导出常见）：utf-8-sig 读取，首列名不能带上 BOM 字符。"""
    f = tmp_path / "bom.csv"
    f.write_bytes("\ufeff姓名,年龄\n张三,30\n".encode("utf-8"))
    chunks = parser.parse_table(str(f), "csv")
    assert chunks[0]["content"].startswith("姓名:"), chunks[0]["content"]


def test_parse_csv_header_only_returns_placeholder(tmp_path):
    """只有表头没有数据行：返回占位片段，不是空列表。"""
    f = tmp_path / "h.csv"
    f.write_text("a,b\n", encoding="utf-8")
    chunks = parser.parse_table(str(f), "csv")
    assert len(chunks) == 1
    assert chunks[0]["content"] == ""


def test_parse_xlsx_keeps_column_names(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["产品", "价格"])
    ws.append(["鼠标", 99])
    ws.append(["键盘", 199])
    path = tmp_path / "t.xlsx"
    wb.save(str(path))

    chunks = parser.parse_table(str(path), "xlsx")
    assert len(chunks) == 2
    assert chunks[0]["content"] == "产品: 鼠标 | 价格: 99"
    assert chunks[0]["meta"]["row"] == 2


def test_parse_xlsx_row_with_fewer_cells_than_header(tmp_path):
    """行比表头短时只拼有值的列，不能因为越界抛 IndexError。"""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["a", "b", "c"])
    ws.append(["1"])
    path = tmp_path / "short.xlsx"
    wb.save(str(path))
    chunks = parser.parse_table(str(path), "xlsx")
    assert chunks[0]["content"] == "a: 1"


# --------------------------------------------------------------------------- 图片 OCR

def test_parse_image_returns_empty_when_tesseract_missing(tmp_path, monkeypatch):
    """tesseract 没装时不能让文档处理失败：返回空文本，由流水线标记"无有效切片"。"""

    def boom(*a, **kw):
        raise FileNotFoundError("tesseract")

    monkeypatch.setattr(subprocess, "run", boom)
    f = tmp_path / "a.png"
    f.write_bytes(b"not a real png")
    chunks = parser.parse_image(str(f))
    assert len(chunks) == 1
    assert chunks[0]["content"] == ""
    assert chunks[0]["meta"]["type"] == "image"


def test_parse_image_returns_empty_on_nonzero_exit(tmp_path, monkeypatch):
    """tesseract 装了但识别失败（语言包缺失 / 图片损坏）：同样返回空文本，不抛。"""

    class R:
        returncode = 1
        stdout = ""
        stderr = "Failed to load language chi_sim"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: R())
    f = tmp_path / "b.png"
    f.write_bytes(b"x")
    chunks = parser.parse_image(str(f))
    assert chunks[0]["content"] == ""


def test_parse_image_reads_stdout_on_success(tmp_path, monkeypatch):
    """识别成功时取 stdout 并去首尾空白。"""

    class R:
        returncode = 0
        stdout = "  识别出来的文字  \n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: R())
    f = tmp_path / "c.png"
    f.write_bytes(b"x")
    chunks = parser.parse_image(str(f))
    assert chunks[0]["content"] == "识别出来的文字"
