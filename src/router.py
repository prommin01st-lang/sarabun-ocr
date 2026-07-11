"""File router — ตรวจชนิดไฟล์ (magic bytes) แล้วเลือก extractor.

CLI ทดสอบ:  python -m src.router <path>
"""
from __future__ import annotations

import sys

from .extractors.base import Document
from .extractors.image import ImageExtractor
from .extractors.office import OfficeExtractor
from .extractors.pdf import PdfExtractor

# ลำดับสำคัญ: PDF ก่อน (opendataloader คุม OCR สแกนเอง), office, แล้วรูปเดี่ยว
EXTRACTORS = [PdfExtractor(), OfficeExtractor(), ImageExtractor()]


class UnsupportedFileError(Exception):
    pass


def detect_mime(path: str) -> str:
    try:
        import magic

        return magic.from_file(str(path), mime=True) or ""
    except Exception:
        return ""


def classify(path: str) -> str:
    """คืนชื่อชนิด: 'pdf' | 'office' | 'image' | 'unsupported'."""
    mime = detect_mime(path)
    for ex in EXTRACTORS:
        if ex.supports(mime, path):
            return ex.name
    return "unsupported"


def extract(path: str) -> Document:
    mime = detect_mime(path)
    for ex in EXTRACTORS:
        if ex.supports(mime, path):
            doc = ex.extract(path)
            doc.meta.setdefault("mime_type", mime)
            doc.meta.setdefault("doc_type", ex.name)
            return doc
    raise UnsupportedFileError(f"ไม่มี extractor รองรับ: {path} (mime={mime})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m src.router <path>", file=sys.stderr)
        sys.exit(1)
    p = sys.argv[1]
    print(f"[classify] {classify(p)}  (mime={detect_mime(p)})", file=sys.stderr)
    document = extract(p)
    print(f"[meta] {document.meta}", file=sys.stderr)
    print("─" * 60, file=sys.stderr)
    print(document.markdown)
