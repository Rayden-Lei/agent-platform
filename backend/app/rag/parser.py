def parse_text(file_path: str, file_type: str) -> str:
    ext = (file_type or "").lower().lstrip(".")
    if ext in ("txt", "md", "markdown"):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if ext == "docx":
        import docx

        d = docx.Document(file_path)
        return "\n".join(p.text for p in d.paragraphs)
    raise ValueError(f"不支持的文件类型: {file_type}")
