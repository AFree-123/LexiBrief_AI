from pathlib import Path
def extract_text(path):
    ext=Path(path).suffix.lower()
    if ext==".pdf":
        import fitz
        with fitz.open(path) as pdf: return "\n\n".join(p.get_text("text") for p in pdf)
    if ext==".docx":
        from docx import Document
        d=Document(path); return "\n".join(p.text for p in d.paragraphs)
    if ext==".txt": return Path(path).read_text(encoding="utf-8",errors="replace")
    raise ValueError("Unsupported file format.")
