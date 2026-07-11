# Sarabun (สารบรรณ)

> คลังเอกสารอัจฉริยะที่คุยด้วยได้ — ส่งเอกสารทาง Telegram แล้วค้น/สรุปได้ทันที
> ทำงาน **local ทั้งหมด ไม่มีค่า API** เน้น **ภาษาไทย**

---

## ภาพรวม (พอสังเขป)

Sarabun รับไฟล์เอกสาร (PDF / Word / Excel / PowerPoint / รูปสแกน) ทาง **Telegram** →
แยกชนิด + สกัดเนื้อหา (รวม OCR) → เก็บเป็น **Single Source of Truth** (metadata + vector) →
ผู้ใช้ **ถามหรือสั่งสรุป** ทางแชท ระบบตอบจากเอกสารจริงพร้อมอ้างอิงไฟล์ต้นทาง

---

## Flow (2 เฟส)

```
เฟส 1 — INGEST (ตอนส่งไฟล์)
  Telegram ─file─▶ [allowlist] ─▶ hash + dedup ─▶ router แยกชนิด
     ─▶ extractor (opendataloader / markitdown / PaddleOCR) ─▶ clean + sanitize
     ─▶ chunk + embed ─▶ ChromaDB (vector)
     ─▶ overview (LLM) ─▶ เก็บ Postgres + summary-vector
     ─▶ metadata ─▶ Postgres (SQLAlchemy)          [status: indexed]

เฟส 2 — QUERY (ตอนถาม/สรุป)
  Telegram ─ข้อความ─▶ embed คำถาม ─▶ ChromaDB หา top-k (cosine)
     [/doc = scope เฉพาะไฟล์] ─▶ ประกอบ context ─▶ Ollama (qwen2.5:3b)
     ─▶ ตอบ + 📎 อ้างอิงไฟล์
```

---

## Logic แต่ละส่วน (พอสังเขป)

**1. Ingest** (`pipeline.py`)
- `hash (sha256)` = ตัวตนของเอกสาร → **dedup**: ถ้า `indexed` แล้วไม่ทำซ้ำ; record ค้าง/`failed` → ล้างแล้วลองใหม่
- **guard (R1)**: ไฟล์ > `MAX_FILE_MB` → ปฏิเสธ (กัน OOM)
- ลำดับเขียน: `metadata(processing) → extract → vector upsert → metadata(indexed)`

**2. Router + Extractors** (`router.py`, `extractors/`)
- เลือก extractor จาก **magic bytes** ไม่ใช่นามสกุล
- PDF → opendataloader (OCR สแกนในตัว) · Office → markitdown (+LibreOffice สำหรับ .doc เก่า) · รูป → PaddleOCR
- คืน `Document(text, markdown, meta)` รูปแบบเดียวกันหมด

**3. Clean / Sanitize** (`textutil.py`)
- `clean_text`: ตัด base64 image / อักขระ PUA / บรรทัดว่างซ้ำ
- `sanitize_pii` (R2, เปิดด้วย `SANITIZE`): มาสก์ email / เบอร์ / เลขบัตร → `[EMAIL] [PHONE] [ID]`

**4. Vector store** (`vectordb.py`)
- chunk ~1500 ตัวอักษร overlap 200 (break ที่ขึ้นบรรทัด — เหมาะภาษาไทย)
- embed ด้วย `paraphrase-multilingual-MiniLM` (384 มิติ, cosine)
- payload ทุก chunk ผูก `doc_id` กลับ metadata + summary-vector (`kind='summary'`) สำหรับค้นระดับเอกสาร

**5. Metadata store** (`store.py`)
- SQLAlchemy Core → สลับ **SQLite ↔ PostgreSQL** ด้วย `DATABASE_URL` เดียว
- system-of-record ของ "มีเอกสารอะไรบ้าง" (ชนิด, สถานะ, overview, ผู้ส่ง)

**6. RAG** (`rag.py`)
- `answer(q, doc_id=None)`: retrieve → ประกอบ context → Ollama → ตอบ (ตอบจาก context เท่านั้น กัน hallucination)
- `summarize_document`: สรุปทั้งไฟล์เป็นหัวข้อ + bullet
- `describe_document`: overview สั้น (ประเภท + เนื้อหาโดยรวม) ตอน ingest

**7. Bot** (`bot.py`)
- `@restricted` (allowlist) ครอบทุก handler
- คำสั่ง: ส่งไฟล์ · `/list` · `/doc <id>` (สรุป+โหมดคุยรายไฟล์) · `/all` · `/summarize <คำค้น>`
- งาน blocking (extract/embed/LLM) โยนเข้า thread executor ไม่ให้ event loop ค้าง

---

## Stack

| ชั้น | เทคโนโลยี |
|------|-----------|
| Chat | python-telegram-bot |
| Extract | opendataloader-pdf (Java) · markitdown · PaddleOCR · LibreOffice |
| Vector | ChromaDB + sentence-transformers (MiniLM multilingual) |
| Metadata | PostgreSQL (Docker) / SQLite — ผ่าน SQLAlchemy Core |
| LLM | Ollama · qwen2.5:3b (local) |

**Single Source of Truth:** เอกสาร 1 ไฟล์ = 1 identity (hash) · metadata แหล่งเดียว (Postgres) · Chroma อ้าง `doc_id` กลับเสมอ

---

## Design decisions (รายละเอียดใน [ARCHITECTURE.md](./ARCHITECTURE.md))
ADR-001 extraction · 002 SQLite · 003 Chroma · 004 embedding · 005 LLM · 006 Telegram · 007 SSoT
· 008 PostgreSQL/Docker · 009 Folders+หมวดหมู่ (ออกแบบ) · 010 RBAC (ออกแบบ)
ความเสี่ยง + module ที่จำเป็น: [AUDIT.md](./AUDIT.md) · แผน/สถานะ: [PLAN.md](./PLAN.md)

---

## สถานะปัจจุบัน
✅ Phase 0–5 + overview + Postgres(Docker) live · e2e flow test ผ่าน 11/11
🔜 Folders + หมวดหมู่ (ADR-009) → RBAC (ADR-010, ออกแบบไว้แล้ว)
