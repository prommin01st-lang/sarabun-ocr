"""ย้าย metadata จาก SQLite → PostgreSQL โดย **รักษา id เดิม** (สำคัญ: doc_id ผูกกับ Chroma).

ใช้:
  .venv/bin/python scripts/migrate_sqlite_to_pg.py \
      "sqlite:////abs/path/data/metadata.db" \
      "postgresql+psycopg://ocr:ocr_local_pw@localhost:5434/ocr_file_chat"
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())  # ให้ import src ได้เมื่อรันเป็นไฟล์

from sqlalchemy import create_engine, insert, select, text  # noqa: E402

from src.store import documents, metadata  # noqa: E402


def main(src_url: str, dst_url: str) -> None:
    src = create_engine(src_url, future=True)
    dst = create_engine(dst_url, future=True)
    metadata.create_all(dst)

    with src.connect() as s:
        rows = [dict(r) for r in s.execute(select(documents)).mappings().all()]
    print(f"อ่านจาก source: {len(rows)} rows")

    with dst.begin() as d:
        d.execute(documents.delete())  # เคลียร์ target ก่อน (idempotent)
        for r in rows:
            d.execute(insert(documents).values(**r))  # includes explicit id
        if dst_url.startswith("postgres"):
            # reset sequence ให้ต่อจาก max(id) เดิม
            d.execute(text(
                "SELECT setval(pg_get_serial_sequence('documents','id'), "
                "(SELECT COALESCE(MAX(id), 1) FROM documents))"
            ))

    with dst.connect() as d:
        n = d.execute(select(documents)).mappings().all()
    print(f"เขียนลง target: {len(n)} rows · ids = {sorted(r['id'] for r in n)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: migrate_sqlite_to_pg.py <src_url> <dst_url>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
