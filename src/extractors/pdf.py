"""PDF extractor — opendataloader-pdf (local mode, OCR สแกนในตัว, ต้องมี Java 11+)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .base import Document, Extractor


class PdfExtractor(Extractor):
    name = "pdf"

    def supports(self, mime_type: str, path: str) -> bool:
        return mime_type == "application/pdf" or str(path).lower().endswith(".pdf")

    def extract(self, path: str) -> Document:
        import opendataloader_pdf

        with tempfile.TemporaryDirectory() as tmp:
            # เขียน markdown ออกไฟล์ใน tmp แล้วอ่านกลับ (quiet ปิด log รบกวน)
            opendataloader_pdf.convert(
                input_path=str(path),
                output_dir=tmp,
                format="markdown",
                quiet=True,
                image_output="off",
            )
            md_files = sorted(Path(tmp).rglob("*.md"))
            markdown = "\n\n".join(f.read_text(encoding="utf-8") for f in md_files)

        return Document(
            text=markdown,
            markdown=markdown,
            meta={"extractor": "opendataloader-pdf"},
        )
