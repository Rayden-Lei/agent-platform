import csv
import logging
import subprocess

logger = logging.getLogger(__name__)


def parse_document(file_path: str, file_type: str) -> list:
    """按文件类型解析，返回 [{content, meta}] 片段列表。"""
    ext = (file_type or "").lower().lstrip(".")
    if ext in ("txt",):
        return parse_text(file_path)
    if ext in ("md", "markdown"):
        return parse_markdown(file_path)
    if ext == "pdf":
        return parse_pdf(file_path)
    if ext == "docx":
        return parse_docx(file_path)
    if ext in ("csv", "xlsx", "xls"):
        return parse_table(file_path, ext)
    if ext in ("png", "jpg", "jpeg", "webp", "bmp"):
        return parse_image(file_path)
    raise ValueError(f"不支持的文件类型: {file_type}")


def parse_text(file_path: str) -> list:
    """纯文本：整篇作为一个片段返回，meta 标记 type=text。"""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
    return [{"content": text, "meta": {"type": "text"}}]


def parse_markdown(file_path: str) -> list:
    """Markdown：整篇作为一个片段返回（分片阶段再按标题切分），meta 标记 type=markdown。"""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
    return [{"content": text, "meta": {"type": "markdown"}}]


def parse_pdf(file_path: str) -> list:
    """PDF：按页提取文本，每页一个片段并记录 page（1 起）；空白页跳过。"""
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    result = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            result.append({"content": text, "meta": {"type": "pdf", "page": i + 1}})
    return result or [{"content": "", "meta": {"type": "pdf"}}]


def parse_docx(file_path: str) -> list:
    """Word(docx)：按段落切片段，记录所在 heading（最近的标题文本）与 style，供分片保留上下文。"""
    import docx

    d = docx.Document(file_path)
    result = []
    current_heading = ""
    for p in d.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name if p.style else "") or ""
        if style.startswith("Heading") or style == "Title":
            current_heading = text
        result.append({"content": text, "meta": {"type": "docx", "heading": current_heading, "style": style}})
    return result or [{"content": "", "meta": {"type": "docx"}}]


def parse_table(file_path: str, ext: str) -> list:
    """表格(csv/xlsx/xls)：首行作列名，每行拼成 "列名: 值 | ..." 片段并记录行号 row（从 2 起）。

    csv 用 utf-8-sig 读取以兼容带 BOM 的文件；xlsx 用 read_only 模式降低内存占用。
    """
    if ext == "csv":
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
    else:
        import openpyxl

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active
        rows = [[("" if c.value is None else str(c.value)) for c in row] for row in ws.iter_rows()]

    if not rows:
        return [{"content": "", "meta": {"type": "table"}}]

    header = rows[0]
    result = []
    for idx, row in enumerate(rows[1:], start=2):
        parts = []
        for i in range(min(len(header), len(row))):
            val = (row[i] or "").strip()
            if val:
                parts.append(f"{header[i]}: {val}")
        if parts:
            result.append({"content": " | ".join(parts), "meta": {"type": "table", "row": idx}})
    return result or [{"content": "", "meta": {"type": "table"}}]


def parse_image(file_path: str) -> list:
    """图片：调用 tesseract OCR（chi_sim+eng）识别文字。

    tesseract 未安装、执行异常或识别失败都不会让文档处理失败：
    返回空文本片段，由流水线标记文档为"无有效切片"并记 WARN 日志。
    """
    try:
        r = subprocess.run(
            ["tesseract", file_path, "stdout", "-l", "chi_sim+eng", "--psm", "6"],
            capture_output=True, text=True, timeout=120,
        )
        text = (r.stdout or "").strip()
        if r.returncode != 0:
            # tesseract 装了但识别失败（语言包缺失、图片损坏）：返回空文本，文档会被标记为无切片
            logger.warning("OCR 识别失败 file=%s returncode=%s stderr=%s", file_path, r.returncode, (r.stderr or "")[:200])
    except FileNotFoundError:
        logger.warning("未安装 tesseract，图片 %s 无法 OCR，按空文本处理", file_path)
        text = ""
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("OCR 执行异常 file=%s error=%s", file_path, e)
        text = ""
    return [{"content": text, "meta": {"type": "image"}}]
