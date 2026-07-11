"""Image OCR extractor — PaddleOCR 3.x (skill smart-ocr). ใช้เฉพาะไฟล์รูปเดี่ยว.

หมายเหตุ: บาง CPU build ของ paddlepaddle ชน oneDNN bug
(NotImplementedError: ConvertPirAttribute2RuntimeAttribute) → ปิด mkldnn ทั้ง env และ param.
"""
from __future__ import annotations

import os

from .. import config
from .base import Document, Extractor

# ต้องตั้งก่อน import paddle (อ่านตอนโหลด runtime)
os.environ.setdefault("FLAGS_use_mkldnn", "0")

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif")


class ImageExtractor(Extractor):
    name = "image"
    _ocr = None  # cache instance (โหลด model ครั้งเดียว)

    def supports(self, mime_type: str, path: str) -> bool:
        return (mime_type or "").startswith("image/") or str(path).lower().endswith(IMAGE_EXTS)

    def _get_ocr(self):
        if ImageExtractor._ocr is None:
            from paddleocr import PaddleOCR

            ImageExtractor._ocr = PaddleOCR(lang=config.OCR_LANG, enable_mkldnn=False)
        return ImageExtractor._ocr

    def extract(self, path: str) -> Document:
        ocr = self._get_ocr()
        result = ocr.predict(str(path))  # 3.x API — คืน list ของ OCRResult (dict-like)

        lines: list[str] = []
        for page in result or []:
            texts = page.get("rec_texts") if hasattr(page, "get") else None
            if texts:
                lines.extend(t for t in texts if t and t.strip())

        text = "\n".join(lines)
        return Document(
            text=text,
            markdown=text,
            meta={"extractor": "paddleocr", "lang": config.OCR_LANG, "n_lines": len(lines)},
        )
