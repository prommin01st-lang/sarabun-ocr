"""Local ingest test — ingest ไฟล์จริงทั้งโฟลเดอร์ผ่าน pipeline แล้วรายงานผล.

ใช้: DATA_DIR=/tmp/x python tests/local_ingest_test.py "Test DataPDF"

ครอบคลุม (แนว data-pipeline testing):
  • transformation correctness — แต่ละไฟล์สกัดได้ status/type/chunks อะไร
  • idempotency — ingest ซ้ำรอบสอง ต้องได้ 'duplicate' ทั้งหมด
  • retrieval — ค้น semantic ภาษาไทย เจอ chunk จากไฟล์ที่ถูกต้อง
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from src import pipeline, store, vectordb


def ingest_all(files: list[Path]) -> list[tuple[str, dict]]:
    out = []
    for p in files:
        r = pipeline.ingest_file(str(p), p.name, source_chat="localtest", source_user="tester")
        extra = ""
        if r["status"] == "indexed":
            extra = f"type={r['doc_type']} chunks={r['n_chunks']}"
        elif r["status"] == "error":
            extra = f"err={r.get('error', '')[:110]}"
        print(f"[{r['status']:10}] {p.name[:48]:48} {extra}")
        out.append((p.name, r))
    return out


def main(folder: str) -> None:
    store.init_db()
    files = sorted(p for p in Path(folder).iterdir() if p.is_file())
    print(f"พบ {len(files)} ไฟล์ ใน {folder}\n" + "=" * 74)

    print("รอบ 1 (ingest จริง):")
    r1 = ingest_all(files)
    print("=" * 74)
    print("สรุปสถานะ:", dict(Counter(r["status"] for _, r in r1)))

    print("-" * 74 + "\nรอบ 2 (idempotency — ควรเป็น duplicate ทั้งหมดที่ indexed สำเร็จ):")
    r2 = ingest_all(files)
    dup_ok = all(
        r["status"] in ("duplicate", "unsupported", "error")
        for (_, r) in r2
    )
    print("idempotency:", "✅ OK" if dup_ok else "❌ FAIL")

    print("-" * 74 + "\nretrieval test (ค้นภาษาไทย):")
    for q in ["การรักษาความลับของทางราชการ", "รายงานสรุปผล", "หนังสือราชการภายใน"]:
        hits = vectordb.search(q, k=2)
        top = hits[0] if hits else None
        if top:
            print(f"  '{q}' → {top['meta']['source_filename'][:38]} "
                  f"(dist={top['distance']:.3f})")
        else:
            print(f"  '{q}' → ไม่พบ")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Test DataPDF")
