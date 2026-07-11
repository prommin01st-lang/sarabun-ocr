"""Ingest pipeline — ผูก router + store + vectordb เป็นขั้นตอนเดียว.

ลำดับ (ตาม ADR-007): metadata(processing) → extract → vector upsert → metadata(indexed)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from . import config, rag, router, store, vectordb

log = logging.getLogger("ocr-file-chat.pipeline")


def ingest_file(
    path: str,
    filename: str,
    source_chat: Optional[str] = None,
    source_user: Optional[str] = None,
) -> dict:
    """รับ path ไฟล์ในเครื่อง → เก็บเข้า SSoT.

    คืน dict: status ∈ {'duplicate','unsupported','indexed','error'}
    """
    data = Path(path).read_bytes()

    # R1: กันไฟล์ใหญ่เกิน (OOM/zip-bomb) ก่อนแตะ extractor
    size_mb = len(data) / (1024 * 1024)
    if size_mb > config.MAX_FILE_MB:
        return {"status": "too_large", "filename": filename,
                "size_mb": round(size_mb, 1), "max_mb": config.MAX_FILE_MB}

    sha = store.sha256_bytes(data)

    # dedup — เฉพาะที่ index สำเร็จแล้วเท่านั้นถือว่าซ้ำ
    existing = store.get_by_hash(sha)
    if existing and existing["status"] == "indexed":
        return {
            "status": "duplicate",
            "doc_id": existing["id"],
            "filename": existing["filename"],
            "n_chunks": existing["n_chunks"],
        }
    if existing:  # processing/failed ค้างอยู่ → ล้างแล้วลองใหม่ (กัน record ค้าง block retry)
        try:
            vectordb.delete_document(existing["id"])
        except Exception:  # noqa: BLE001
            pass
        store.delete(existing["id"])

    # classify
    doc_type = router.classify(path)
    if doc_type == "unsupported":
        return {"status": "unsupported", "filename": filename}

    # เก็บไฟล์ต้นฉบับ: ชื่อ = hash + นามสกุลเดิม
    # (opendataloader/markitdown เลือก parser จากนามสกุล — ห้ามตัดทิ้ง)
    config.ensure_dirs()
    ext = Path(filename).suffix.lower()
    raw_path = config.RAW_DIR / f"{sha}{ext}"
    raw_path.write_bytes(data)
    mime = router.detect_mime(str(raw_path))

    doc_id = store.add(
        sha256=sha, filename=filename, mime_type=mime, doc_type=doc_type,
        source_chat=source_chat, source_user=source_user, bytes=len(data),
        status="processing",
    )

    try:
        document = router.extract(str(raw_path))

        # R2: ปกปิด PII (email/เบอร์/เลขบัตร) ถ้าเปิด SANITIZE — ครอบทุกชนิดไฟล์
        if config.SANITIZE:
            from .textutil import sanitize_pii
            document.text = sanitize_pii(document.text)
            document.markdown = sanitize_pii(document.markdown)

        ext_path = config.EXTRACTED_DIR / f"{sha}.md"
        ext_path.write_text(document.markdown or document.text or "", encoding="utf-8")

        full_text = document.text or document.markdown or ""
        n = vectordb.index_document(doc_id, filename, full_text)

        # document-level overview (ต้องมี Ollama; ถ้าล่มข้ามได้ ไม่ให้ ingest ล้ม)
        overview = ""
        try:
            overview = rag.describe_document(full_text, filename)
            if overview:
                store.set_summary(doc_id, overview)
                vectordb.index_summary(doc_id, filename, overview)
        except Exception as e:  # noqa: BLE001
            log.warning("describe_document ล้มเหลว (ข้าม overview): %s", e)

        store.update_status(doc_id, "indexed", n_chunks=n, extracted_path=str(ext_path))
        return {
            "status": "indexed", "doc_id": doc_id, "filename": filename,
            "n_chunks": n, "doc_type": doc_type, "summary": overview,
        }
    except Exception as e:  # noqa: BLE001 — ต้องกันทุก error ไม่ให้ bot ล่ม
        store.update_status(doc_id, "failed")
        return {"status": "error", "filename": filename, "error": str(e)}
