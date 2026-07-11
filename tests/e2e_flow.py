"""End-to-end flow test — รันกับ backend ใน .env (SQLite หรือ Postgres/Docker).

ครอบทั้ง flow: ingest → metadata(store) + vector(Chroma) + overview
             → RAG answer → per-doc summary → scoped Q&A → dedup → doc-level search
ถ้า backend เป็น Postgres จะ cross-check ว่า row อยู่ใน container จริงด้วย `docker exec psql`.

ใช้:  OLLAMA_HOST=http://127.0.0.1:11434 .venv/bin/python -m tests.e2e_flow
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from src import config, pipeline, rag, store, vectordb

SAMPLE_HTML = """<h1>ประกาศทดสอบระบบ E2E</h1>
<p>เอกสารนี้เป็นประกาศของฝ่ายไอทีเรื่องการทดสอบระบบจัดเก็บเอกสารอัตโนมัติ</p>
<p>ผู้รับผิดชอบ: ทีมวิศวกรรมข้อมูล</p>
<p>ระบบต้องรองรับการค้นหาด้วยความหมายและสรุปเอกสารเป็นภาษาไทย</p>
<p>รหัสอ้างอิงลับของเอกสารนี้คือ ALPHA-7788</p>
"""

_passed, _failed = 0, 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed, _failed
    _passed += ok
    _failed += (not ok)
    print(f"  [{'✅' if ok else '❌'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def pg_container_check(doc_id: int) -> None:
    """ยืนยันว่า row อยู่ใน Postgres container จริง (ไม่ใช่ SQLite)."""
    out = subprocess.run(
        ["docker", "exec", "ocr-file-chat-pg", "psql", "-U", "ocr", "-d", "ocr_file_chat",
         "-tAc", f"SELECT id||'|'||doc_type||'|'||status FROM documents WHERE id={doc_id};"],
        capture_output=True, text=True, timeout=30,
    )
    val = out.stdout.strip()
    check(f"row อยู่ใน Postgres container จริง (docker exec psql)", val.startswith(f"{doc_id}|"), val)


def main() -> None:
    where = config.DATABASE_URL.split("@")[-1]
    print(f"backend = {config.DB_BACKEND} | {where}\n" + "=" * 60)
    store.init_db()
    before = len(store.list_docs())

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "e2e-ประกาศทดสอบ.html"
        f.write_text(SAMPLE_HTML, encoding="utf-8")

        # 1) ingest
        r = pipeline.ingest_file(str(f), f.name, source_chat="e2e", source_user="tester")
        did = r.get("doc_id")
        check("ingest → indexed", r["status"] == "indexed", f"id={did} chunks={r.get('n_chunks')}")
        check("overview ถูกสร้าง", bool(r.get("summary")), (r.get("summary") or "")[:50])

        # 2) metadata store (PG/SQLite)
        row = store.get(did)
        check("อ่าน metadata กลับได้", row is not None and row["status"] == "indexed")
        if config.DB_BACKEND == "postgresql":
            pg_container_check(did)

        # 3) vector store — chunk + summary vector
        chunks = vectordb.get_document_chunks(did)
        check("Chroma มี chunk เนื้อหา", len(chunks) >= 1, f"{len(chunks)} chunks")

        # 4) RAG answer (retrieval precision — รหัสลับ)
        a = rag.answer("รหัสอ้างอิงลับของเอกสารทดสอบคืออะไร", doc_id=did)
        check("RAG ตอบถูก (เจอ ALPHA-7788)", "ALPHA-7788" in a["answer"].replace(" ", ""), a["answer"][:60])

        # 5) per-doc summary
        s = rag.summarize_document(did, row["extracted_path"], row["filename"])
        check("สรุปทั้งไฟล์ได้", len(s["answer"]) > 20)

        # 6) scoped Q&A
        sc = rag.answer("ใครเป็นผู้รับผิดชอบ", doc_id=did)
        check("scoped Q&A (ในไฟล์)", "วิศวกรรม" in sc["answer"] or "ไอที" in sc["answer"], sc["answer"][:50])

        # 7) dedup
        r2 = pipeline.ingest_file(str(f), f.name)
        check("dedup (re-ingest → duplicate)", r2["status"] == "duplicate")

        # 8) doc-level search (summary vector)
        hits = vectordb.search("ประกาศทดสอบระบบไอที", k=5)
        found = any(h["meta"]["doc_id"] == did for h in hits)
        check("doc-level search เจอเอกสาร", found)

        # 9) cleanup
        vectordb.delete_document(did)
        store.delete(did)
        check("cleanup กลับสู่สภาพเดิม", len(store.list_docs()) == before, f"{before} docs")

    print("=" * 60)
    print(f"ผลรวม: {_passed} ผ่าน / {_failed} ไม่ผ่าน — {'✅ FLOW OK' if _failed == 0 else '❌ มีปัญหา'}")
    raise SystemExit(1 if _failed else 0)


if __name__ == "__main__":
    main()
