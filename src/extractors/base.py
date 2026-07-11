"""Extractor interface + Document container."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Document:
    """ผลลัพธ์การสกัด — ใช้ร่วมกันทุก extractor."""

    text: str                                   # เนื้อหาสำหรับ embed/ค้นหา
    markdown: str                               # รูปแบบ markdown (เก็บไว้อ่าน/citation)
    meta: dict[str, Any] = field(default_factory=dict)


class Extractor:
    """Base class — subclass แล้ว implement supports() + extract()."""

    name: str = "base"

    def supports(self, mime_type: str, path: str) -> bool:
        raise NotImplementedError

    def extract(self, path: str) -> Document:
        raise NotImplementedError
