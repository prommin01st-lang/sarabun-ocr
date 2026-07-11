"""Metadata store — SQLAlchemy Core (รองรับทั้ง SQLite และ PostgreSQL ผ่าน DATABASE_URL).

API เดิมทั้งหมดคงรูป: getter คืน RowMapping (ใช้ r['key'] / 'x' in r.keys() ได้เหมือน sqlite3.Row).
"""
from __future__ import annotations

import hashlib
import time
from typing import Optional

from sqlalchemy import (
    Column, Float, Integer, MetaData, String, Table, Text,
    create_engine, delete as sa_delete, insert, inspect as sa_inspect,
    select, text, update,
)
from sqlalchemy.engine import Engine

from . import config

metadata = MetaData()

documents = Table(
    "documents", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sha256", String(64), unique=True, nullable=False, index=True),
    Column("filename", String),
    Column("mime_type", String),
    Column("doc_type", String),
    Column("source_chat", String),
    Column("source_user", String),
    Column("bytes", Integer),
    Column("status", String, default="new"),
    Column("n_chunks", Integer, default=0),
    Column("created_at", Float),
    Column("extracted_path", String),
    Column("summary", Text),
    Column("folder_id", Integer),   # nullable = root/ยังไม่จัดหมวด
    Column("category", String),     # auto จาก LLM ตอน ingest
)

folders = Table(
    "folders", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("parent_id", Integer),   # เผื่อ hierarchy อนาคต (ตอนนี้ใช้ flat)
    Column("created_at", Float),
)

_engine: Optional[Engine] = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        config.ensure_dirs()  # เผื่อ sqlite ต้องมีโฟลเดอร์ data
        _engine = create_engine(config.DATABASE_URL, future=True)
    return _engine


def init_db() -> None:
    eng = _get_engine()
    metadata.create_all(eng)  # สร้างตาราง documents/folders ที่ยังไม่มี
    # migration: เพิ่ม folder_id ให้ตาราง documents เดิมที่ยังไม่มี
    cols = {c["name"] for c in sa_inspect(eng).get_columns("documents")}
    with eng.begin() as c:
        if "folder_id" not in cols:
            c.execute(text("ALTER TABLE documents ADD COLUMN folder_id INTEGER"))
        if "category" not in cols:
            c.execute(text("ALTER TABLE documents ADD COLUMN category VARCHAR"))


# ── hashing ─────────────────────────────────────────────────
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ── CRUD ────────────────────────────────────────────────────
def get_by_hash(sha256: str):
    with _get_engine().connect() as c:
        return c.execute(
            select(documents).where(documents.c.sha256 == sha256)
        ).mappings().first()


def get(doc_id: int):
    with _get_engine().connect() as c:
        return c.execute(
            select(documents).where(documents.c.id == doc_id)
        ).mappings().first()


def add(
    *,
    sha256: str,
    filename: str,
    mime_type: str = "",
    doc_type: str = "",
    source_chat: Optional[str] = None,
    source_user: Optional[str] = None,
    bytes: int = 0,
    status: str = "processing",
    extracted_path: Optional[str] = None,
    folder_id: Optional[int] = None,
) -> int:
    """เพิ่มเอกสารใหม่ คืน id. ถ้า sha256 มีแล้ว คืน id เดิม (ไม่เขียนซ้ำ)."""
    existing = get_by_hash(sha256)
    if existing:
        return int(existing["id"])
    with _get_engine().begin() as c:
        result = c.execute(
            insert(documents).values(
                sha256=sha256, filename=filename, mime_type=mime_type,
                doc_type=doc_type, source_chat=source_chat, source_user=source_user,
                bytes=bytes, status=status, n_chunks=0,
                created_at=time.time(), extracted_path=extracted_path,
                folder_id=folder_id,
            )
        )
        return int(result.inserted_primary_key[0])


def update_status(
    doc_id: int,
    status: str,
    n_chunks: Optional[int] = None,
    extracted_path: Optional[str] = None,
) -> None:
    values: dict = {"status": status}
    if n_chunks is not None:
        values["n_chunks"] = n_chunks
    if extracted_path is not None:
        values["extracted_path"] = extracted_path
    with _get_engine().begin() as c:
        c.execute(update(documents).where(documents.c.id == doc_id).values(**values))


def set_summary(doc_id: int, summary: str) -> None:
    with _get_engine().begin() as c:
        c.execute(update(documents).where(documents.c.id == doc_id).values(summary=summary))


def set_category(doc_id: int, category: str) -> None:
    with _get_engine().begin() as c:
        c.execute(update(documents).where(documents.c.id == doc_id).values(category=category))


def delete(doc_id: int) -> None:
    with _get_engine().begin() as c:
        c.execute(sa_delete(documents).where(documents.c.id == doc_id))


def list_docs(limit: int = 50) -> list:
    with _get_engine().connect() as c:
        return list(c.execute(
            select(documents).order_by(documents.c.created_at.desc()).limit(limit)
        ).mappings().all())


# ── Folders ─────────────────────────────────────────────────
def get_folder_by_name(name: str):
    with _get_engine().connect() as c:
        return c.execute(select(folders).where(folders.c.name == name)).mappings().first()


def get_folder(folder_id: int):
    with _get_engine().connect() as c:
        return c.execute(select(folders).where(folders.c.id == folder_id)).mappings().first()


def create_folder(name: str, parent_id: Optional[int] = None) -> int:
    """สร้างโฟลเดอร์ (idempotent ตามชื่อ) คืน id."""
    existing = get_folder_by_name(name)
    if existing:
        return int(existing["id"])
    with _get_engine().begin() as c:
        r = c.execute(insert(folders).values(
            name=name, parent_id=parent_id, created_at=time.time()))
        return int(r.inserted_primary_key[0])


def list_folders() -> list:
    with _get_engine().connect() as c:
        return list(c.execute(select(folders).order_by(folders.c.name)).mappings().all())


def move_document(doc_id: int, folder_id: Optional[int]) -> None:
    with _get_engine().begin() as c:
        c.execute(update(documents).where(documents.c.id == doc_id).values(folder_id=folder_id))
