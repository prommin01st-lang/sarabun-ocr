"""Office / rich-text extractor — markitdown (docx/xlsx/pptx/csv/html/rtf/epub → markdown).

ไฟล์ไบนารีเก่า (.doc/.xls/.ppt) markitdown แปลงไม่ได้ → ใช้ LibreOffice (soffice)
แปลงเป็นฟอร์แมต XML สมัยใหม่ก่อน แล้วค่อยส่ง markitdown.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import Document, Extractor

OFFICE_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/x-ole-storage",  # libmagic บางเวอร์ชันคืนค่านี้ให้ .doc เก่า
    "text/csv",
    "text/html",
    "application/rtf",
    "application/epub+zip",
    "application/vnd.oasis.opendocument.text",
}
OFFICE_EXTS = (
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".csv", ".html", ".htm", ".rtf", ".epub", ".odt",
)
# ไบนารีเก่า → นามสกุลเป้าหมายที่ soffice แปลงให้
LEGACY_CONVERT = {".doc": "docx", ".xls": "xlsx", ".ppt": "pptx"}


class OfficeExtractor(Extractor):
    name = "office"

    def supports(self, mime_type: str, path: str) -> bool:
        return mime_type in OFFICE_MIMES or str(path).lower().endswith(OFFICE_EXTS)

    def extract(self, path: str) -> Document:
        from markitdown import MarkItDown

        src = str(path)
        tmpdir = None
        suffix = Path(path).suffix.lower()
        if suffix in LEGACY_CONVERT:
            src, tmpdir = self._soffice_convert(path, LEGACY_CONVERT[suffix])

        try:
            result = MarkItDown().convert(src)
            markdown = (result.text_content or "").strip()
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

        return Document(
            text=markdown,
            markdown=markdown,
            meta={"extractor": "markitdown+soffice" if suffix in LEGACY_CONVERT else "markitdown"},
        )

    @staticmethod
    def _soffice_convert(path: str, target_ext: str) -> tuple[str, str]:
        """แปลงไฟล์เก่าด้วย LibreOffice headless. คืน (path ใหม่, tmpdir ให้ลบทีหลัง)."""
        tmp = tempfile.mkdtemp(prefix="ocrfc_soffice_")
        try:
            subprocess.run(
                [
                    "soffice",
                    # แยก user profile ต่อครั้ง → กัน lock ชนกันเวลาแปลงพร้อมกัน
                    f"-env:UserInstallation=file://{tmp}/profile",
                    "--headless", "--convert-to", target_ext, "--outdir", tmp, str(path),
                ],
                check=True, capture_output=True, timeout=180,
            )
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        outs = list(Path(tmp).glob(f"*.{target_ext}"))
        if not outs:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"soffice แปลง {path} → {target_ext} ไม่สำเร็จ")
        return str(outs[0]), tmp
