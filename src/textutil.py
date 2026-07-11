"""ทำความสะอาดข้อความก่อน embed/สรุป — ตัด noise ที่กวนโมเดล."""
from __future__ import annotations

import re

_DATA_URI_IMG = re.compile(r"!\[[^\]]*\]\(\s*data:[^)]*\)")           # ![](data:image/...;base64,...)
_DATA_URI = re.compile(r"data:[a-zA-Z0-9/+.\-]+;base64,[A-Za-z0-9+/=\s]{40,}")
_PUA = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]")       # private-use chars จาก PDF บางตัว
_MULTINL = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = _DATA_URI_IMG.sub("", text)
    text = _DATA_URI.sub("", text)
    text = _PUA.sub("", text)
    text = _MULTINL.sub("\n\n", text)
    return text.strip()


# ── PII masking (heuristic — กันข้อมูลอ่อนไหว, ไม่การันตี 100%) ──
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CREDIT = re.compile(r"(?<!\d)(?:\d[ -]?){15,16}\d(?!\d)")
_THAI_ID = re.compile(r"(?<!\d)\d(?:[ -]?\d){12}(?!\d)")          # เลขบัตรประชาชน 13 หลัก
_PHONE = re.compile(r"(?<!\d)(?:\+?66|0)\d[\d -]{7,}\d(?!\d)")     # เบอร์โทรไทย


def sanitize_pii(text: str) -> str:
    """แทน email/เลขบัตร/บัตรเครดิต/เบอร์โทร ด้วย placeholder (ลำดับสำคัญ: ยาว→สั้น)."""
    if not text:
        return ""
    text = _EMAIL.sub("[EMAIL]", text)
    text = _CREDIT.sub("[CARD]", text)
    text = _THAI_ID.sub("[ID]", text)
    text = _PHONE.sub("[PHONE]", text)
    return text
