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
    folder_id: Optional[int] = None,
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
        status="processing", folder_id=folder_id,
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

        # document-level overview + auto-category (ต้องมี Ollama; ถ้าล่มข้ามได้ ไม่ให้ ingest ล้ม)
        overview, category = "", ""
        try:
            overview = rag.describe_document(full_text, filename)
            if overview:
                store.set_summary(doc_id, overview)
                vectordb.index_summary(doc_id, filename, overview)
            category = rag.classify_document(full_text, filename, overview=overview)
            if category:
                store.set_category(doc_id, category)
        except Exception as e:  # noqa: BLE001
            log.warning("overview/category ล้มเหลว (ข้าม): %s", e)

        store.update_status(doc_id, "indexed", n_chunks=n, extracted_path=str(ext_path))
        store.log_action("ingest", doc_id, source_user, f"{filename} · {category}")
        return {
            "status": "indexed", "doc_id": doc_id, "filename": filename,
            "n_chunks": n, "doc_type": doc_type, "summary": overview, "category": category,
        }
    except Exception as e:  # noqa: BLE001 — ต้องกันทุก error ไม่ให้ bot ล่ม
        store.update_status(doc_id, "failed")
        return {"status": "error", "filename": filename, "error": str(e)}


def update_file(doc_id: int, path: str, filename: str, actor: Optional[str] = None) -> dict:
    """แทนที่เนื้อหาของเอกสาร doc_id ด้วยไฟล์ใหม่ (คง id/folder/เจ้าของเดิม).

    คืน status ∈ {'notfound','too_large','unsupported','unchanged','conflict','updated','error'}
    (permission ต้องเช็คที่ชั้นบอทก่อนเรียก)
    """
    row = store.get(doc_id)
    if not row:
        return {"status": "notfound", "doc_id": doc_id}

    data = Path(path).read_bytes()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > config.MAX_FILE_MB:
        return {"status": "too_large", "size_mb": round(size_mb, 1), "max_mb": config.MAX_FILE_MB}

    sha = store.sha256_bytes(data)
    if sha == row["sha256"]:
        return {"status": "unchanged", "doc_id": doc_id}
    other = store.get_by_hash(sha)
    if other and other["id"] != doc_id:
        return {"status": "conflict", "other_id": other["id"]}

    doc_type = router.classify(path)
    if doc_type == "unsupported":
        return {"status": "unsupported", "filename": filename}

    config.ensure_dirs()
    ext = Path(filename).suffix.lower()
    raw_path = config.RAW_DIR / f"{sha}{ext}"
    raw_path.write_bytes(data)
    mime = router.detect_mime(str(raw_path))

    store.update_status(doc_id, "processing")
    try:
        document = router.extract(str(raw_path))
        if config.SANITIZE:
            from .textutil import sanitize_pii
            document.text = sanitize_pii(document.text)
            document.markdown = sanitize_pii(document.markdown)

        full_text = document.text or document.markdown or ""
        ext_path = config.EXTRACTED_DIR / f"{sha}.md"
        ext_path.write_text(document.markdown or full_text, encoding="utf-8")

        vectordb.delete_document(doc_id)  # ลบ vector เก่า
        n = vectordb.index_document(doc_id, filename, full_text)
        store.replace_document(
            doc_id, sha256=sha, filename=filename, mime_type=mime,
            doc_type=doc_type, bytes=len(data), extracted_path=str(ext_path),
        )
        store.update_status(doc_id, "indexed", n_chunks=n)

        overview, category = "", ""
        try:
            overview = rag.describe_document(full_text, filename)
            if overview:
                store.set_summary(doc_id, overview)
                vectordb.index_summary(doc_id, filename, overview)
            category = rag.classify_document(full_text, filename, overview=overview)
            if category:
                store.set_category(doc_id, category)
        except Exception as e:  # noqa: BLE001
            log.warning("overview/category ตอน update ล้มเหลว: %s", e)

        store.log_action("update", doc_id, actor, f"{filename} · {category}")
        return {"status": "updated", "doc_id": doc_id, "filename": filename,
                "n_chunks": n, "doc_type": doc_type, "summary": overview, "category": category}
    except Exception as e:  # noqa: BLE001
        store.update_status(doc_id, "failed")
        return {"status": "error", "filename": filename, "error": str(e)}


def delete_document(doc_id: int, actor: Optional[str] = None) -> bool:
    """ลบเอกสารออกจากทั้ง vector + metadata. คืน False ถ้าไม่พบ."""
    row = store.get(doc_id)
    if not row:
        return False
    try:
        vectordb.delete_document(doc_id)
    except Exception:  # noqa: BLE001
        pass
    store.delete(doc_id)
    store.log_action("delete", doc_id, actor, row["filename"])
    return True
