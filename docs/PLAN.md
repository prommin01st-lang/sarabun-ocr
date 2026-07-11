# OCR-File-Chat — Project Plan

> ระบบรับไฟล์เอกสารทาง **Telegram** → แยกชนิด → สกัดเนื้อหา → เก็บเป็น **Single Source of Truth**
> (metadata + vector) → **ค้นหา/สรุป** กลับออกทาง chat ได้ — ทำงาน **local ทั้งหมด ไม่มีค่า API**

- **สถานะ:** Phase 0–5 เสร็จ + verify รันจริงครบทุกชั้น (รวม Ollama + Telegram live) ✅ · Phase 6 เหลือ run-skill
- **อัปเดตล่าสุด:** 2026-07-11

> **สรุป verify (รันจริงในเครื่อง dev):** PDF→markdown (opendataloader+Java17), office→markdown (markitdown),
> SQLite dedup+status, chunking, embed+Chroma upsert+semantic search, ingest pipeline ครบวงจร, rag retrieval+prompt,
> bot import+handlers+token guard — **ผ่านหมด** · ยังรอ runtime ผู้ใช้: Ollama (LLM), Telegram token
>
> **Local test เอกสารราชการไทยจริง (7 ไฟล์, `tests/local_ingest_test.py`):** .doc×2 + PDF×4 + PNG×1 →
> **indexed 7/7** ✅, idempotency ✅, retrieval ไทยแม่น (dist 0.257) · แก้ bug ที่เจอ: (1) raw ไม่มีนามสกุล
> (2) record fail ค้าง block retry (3) .doc เก่าต้องผ่าน LibreOffice (4) markitdown ต้องมี docx extras
> (5) paddleocr 3.x API + ปิด mkldnn เลี่ยง oneDNN bug
- **สถาปัตยกรรม (ADR):** ดู [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## 1. เป้าหมาย (Goals)

| # | เป้าหมาย | วัดผลอย่างไร |
|---|---------|-------------|
| G1 | รับไฟล์เอกสารทาง Telegram chat | ส่งไฟล์แล้วบอทตอบรับ + เก็บไฟล์ได้ |
| G2 | แยกแยะ **ชนิด** ของไฟล์เอกสารและเก็บลง DB | query ดูชนิด/metadata ของทุกไฟล์ได้ |
| G3 | สกัดเนื้อหา (รวม OCR สแกน/รูป) | ได้ text/markdown ที่ถูกต้องจากทุกชนิดที่รองรับ |
| G4 | เก็บใน **vector database** เป็น Single Source of Truth | ค้นหา semantic เจอ chunk ที่เกี่ยวข้อง |
| G5 | **สรุป/ตอบคำถาม** ออกทาง chat | พิมพ์ถามใน Telegram → ได้คำตอบอ้างอิงเอกสารจริง |

**Non-goals (เฟสแรก):** multi-user auth ซับซ้อน, การแก้ไขเอกสาร, UI เว็บ, cloud deploy

---

## 2. Stack (สรุป — เหตุผลอยู่ใน ADR)

| ส่วน | เครื่องมือ | ADR |
|------|-----------|-----|
| Chat interface | `python-telegram-bot` | ADR-006 |
| แยกชนิดไฟล์ | `python-magic` (ตรวจ magic bytes) | ADR-001 |
| สกัด PDF (text + สแกน) | **opendataloader-pdf** (local mode, OCR ในตัว) | ADR-001 |
| สกัด Office (docx/xlsx/pptx) | **markitdown** (pure-python, เบา) | ADR-001 |
| OCR รูปเดี่ยว (jpg/png) | **PaddleOCR** (จาก skill `smart-ocr`, `lang='th'`) | ADR-001 |
| Metadata DB | **SQLite** | ADR-002 |
| Vector DB | **ChromaDB** (persist local) | ADR-003 |
| Embedding | `paraphrase-multilingual-MiniLM-L12-v2` | ADR-004 |
| LLM สรุป | **Ollama** + `qwen2.5:3b` (ล็อก — RAM ≤8GB) | ADR-005 |

---

## 3. โครงสร้างโปรเจกต์

```
OCR-File-Chat/
├── docs/
│   ├── PLAN.md              ← ไฟล์นี้
│   └── ARCHITECTURE.md      ← ADR ทั้งหมด
├── external/
│   └── opendataloader-pdf/  ← clone (เฟส 0)
├── src/
│   ├── config.py            ← โหลด .env, ค่าคงที่
│   ├── router.py            ← แยกชนิดไฟล์ → เลือก extractor
│   ├── extractors/
│   │   ├── base.py          ← interface: extract(path) -> Document
│   │   ├── pdf.py           ← opendataloader-pdf (รวม OCR PDF สแกน)
│   │   ├── office.py        ← markitdown
│   │   └── image.py         ← PaddleOCR (smart-ocr) — เฉพาะรูปเดี่ยว
│   ├── store.py             ← SQLite metadata (CRUD + dedup ด้วย hash)
│   ├── vectordb.py          ← chunk + embed + ค้น (ChromaDB)
│   ├── rag.py               ← retrieve + summarize ผ่าน Ollama
│   └── bot.py               ← Telegram handlers
├── data/
│   ├── raw/                 ← ไฟล์ต้นฉบับ (ตั้งชื่อด้วย hash)
│   ├── extracted/           ← markdown/json ที่สกัดได้
│   ├── metadata.db          ← SQLite
│   └── chroma/              ← ChromaDB persist
├── tests/
├── .env.example            ← TELEGRAM_BOT_TOKEN, OLLAMA_MODEL, ...
├── requirements.txt
└── README.md
```

---

## 4. Data Flow

```
                    ┌──────────── ส่งไฟล์ ────────────┐
 Telegram user ──── │                                 │ ──► bot.py (on_document)
                    └─────────────────────────────────┘        │
                                                               ▼
  hash ไฟล์ → เช็ก dedup ใน store.py ──(ซ้ำ)──► ตอบ "มีแล้ว"    │
                       │ (ใหม่)                                  ▼
                       ▼                                    router.py
             บันทึกไฟล์ data/raw/<hash>            (magic bytes → ชนิด)
                       │                                        │
                       ▼                    ┌───────────────────┼───────────────────┐
              store.py: insert metadata     ▼                   ▼                   ▼
              (ชนิด, ชื่อ, hash, ผู้ส่ง,   pdf.py            office.py           image.py
               เวลา, สถานะ=processing)   (opendataloader)    (docling)         (PaddleOCR)
                                            └───────────────────┼───────────────────┘
                                                                ▼
                                                    Document(text, markdown, meta)
                                                                │
                                                                ▼
                                              vectordb.py: chunk → embed → upsert
                                              (payload ผูก doc_id กลับไป SQLite)
                                                                │
                                                                ▼
                                              store.py: update สถานะ=indexed
                                                                │
                                                                ▼
                                                  ตอบ Telegram: "เก็บแล้ว N chunks"

 ── ถาม/สั่งสรุป ──►  bot.py (on_message) ──► rag.py:
        1) embed คำถาม → ค้น top-k ใน ChromaDB
        2) ประกอบ context + prompt → Ollama (qwen2.5)
        3) ตอบกลับ + อ้างอิงชื่อไฟล์ต้นทาง
```

---

## 5. เฟสการพัฒนา (Phased Roadmap)

> หลักการ: **แต่ละเฟสต้องรัน/ทดสอบได้เอง** ก่อนไปเฟสถัดไป (vertical slices)

### Phase 0 — Setup & Scaffold ✅
- **เป้า:** โครงโปรเจกต์พร้อม, dependency ลงครบ, config อ่านได้
- **งาน:**
  - [x] สร้างโครง `src/`, `data/`, `tests/`, `.env.example`, `requirements.txt`
  - [x] `git init` + `.gitignore` (data/, .env, __pycache__, external/)
  - [x] clone `opendataloader-pdf` เข้า `external/` + ยืนยัน `pip install opendataloader-pdf` ใช้ได้
  - [x] `config.py` โหลด `.env` (TELEGRAM_BOT_TOKEN, OLLAMA_MODEL, paths)
  - [x] ยืนยัน Java 17 พร้อม (opendataloader ต้องการ 11+)
  - [x] ติดตั้ง Ollama (rootless v0.31.2) + `ollama pull qwen2.5:3b` (1.9GB) ✅
- **เสร็จเมื่อ:** import core packages ผ่าน + Ollama ตอบได้ → **✅ ครบ**
- **ต้องมีก่อน:** —

### Phase 1 — File Router + Extractors ✅
- **เป้า:** ให้ path ไฟล์ → คืน `Document(text, markdown, meta)` ได้ทุกชนิด
- **งาน:**
  - [x] `router.py`: `python-magic` แยกชนิด (pdf / office / image / unsupported)
  - [x] `extractors/base.py`: interface `extract(path) -> Document`
  - [x] `extractors/pdf.py`: opendataloader-pdf → markdown — **verified บน lorem.pdf**
  - [x] `extractors/office.py`: markitdown (+ LibreOffice สำหรับ .doc/.xls/.ppt เก่า) — **verified บน .doc ไทย×2**
  - [x] `extractors/image.py`: PaddleOCR 3.x (`lang='th'`, ปิด mkldnn) เฉพาะรูปเดี่ยว — **verified บน PNG ไทย**
  - [x] จัดการ error: ชนิดไม่รองรับ → `UnsupportedFileError` / คืน status ชัดเจน
- **เสร็จเมื่อ:** `python -m src.router sample.pdf` พิมพ์ markdown ถูกต้อง → ✅ **ครบ 3 ชนิด (pdf/office/image) ยืนยันจริง**
- **ต้องมีก่อน:** Phase 0

### Phase 2 — Metadata Store (SQLite) ✅
- **เป้า:** เก็บ/ค้น record ของทุกไฟล์ + dedup ด้วย hash
- **งาน:**
  - [x] schema: `documents(id, sha256, filename, mime_type, doc_type, source_chat, source_user, bytes, status, n_chunks, created_at, extracted_path)`
  - [x] `store.py`: `add()`, `get_by_hash()`, `update_status()`, `list_docs()`, `get()`, `delete()`
  - [x] dedup: ถ้า `sha256` มี + status `indexed` → คืน record เดิม (record `failed`/ค้าง → ล้างแล้ว retry)
- **เสร็จเมื่อ:** เพิ่มไฟล์ซ้ำ 2 ครั้ง → record เดียว, `list()` ถูกต้อง → **✅ verified**
- **ต้องมีก่อน:** Phase 1

### Phase 3 — Vector DB + Embedding (Single Source of Truth) ✅
- **เป้า:** chunk + embed เนื้อหา → ค้น semantic ได้ พร้อมผูกกลับ metadata
- **งาน:**
  - [x] `vectordb.py`: `chunk_text` (char-based ~1500, overlap 200, break ที่ขึ้นบรรทัด) + embed ด้วย `sentence-transformers`
  - [x] `index_document(doc_id, filename, text)` — payload เก็บ `doc_id`, `chunk_idx`, `source_filename`
  - [x] `search(query, k)` → คืน chunks + doc_id + distance
  - [x] persist ที่ `data/chroma/` (cosine space) + `delete_document()`
- **เสร็จเมื่อ:** index เอกสาร แล้วค้น → เจอ chunk ที่เกี่ยวข้อง + doc_id ถูก → **✅ verified (MiniLM multilingual)**
- **ต้องมีก่อน:** Phase 2

### Phase 4 — Telegram Bot (รับไฟล์ → ต่อ pipeline 1-3) ✅ live
- **เป้า:** ส่งไฟล์จริงทาง Telegram → เข้า DB + vector ครบวงจร
- **งาน:**
  - [x] `pipeline.py`: ingest ครบวงจร (hash → dedup → router → store → vectordb) — **verified**
  - [x] `bot.py`: `on_document` / `on_photo` — ดาวน์โหลด → เรียก pipeline (blocking โยนเข้า executor)
  - [x] ตอบสถานะ ("กำลังประมวลผล..." → "เก็บแล้ว N chunks" / duplicate / unsupported / error)
  - [x] คำสั่ง `/list`, `/start` (+ `/summarize`)
  - [x] จัดการชนิดไม่รองรับ/error อย่างสุภาพ
  - [x] **allowlist** จำกัดผู้ใช้ (`ALLOWED_USER_IDS`) — เปิดใช้เฉพาะ ID เจ้าของ
- **เสร็จเมื่อ:** ส่ง PDF จริง → บอทตอบ + `/list` เห็นไฟล์ → **✅ @PetanqueMesBot รัน live + polling (getMe ผ่าน); รอผู้ใช้ทักทดสอบ round-trip**
- **ต้องมีก่อน:** Phase 3

### Phase 5 — RAG + Summarize (ตอบ/สรุปทาง chat) ✅ verified (live Ollama)
- **เป้า:** ถาม/สั่งสรุปใน chat → บอทตอบอ้างอิงเอกสารจริง
- **งาน:**
  - [x] `rag.py`: embed คำถาม → retrieve top-k → ประกอบ prompt → Ollama (`/api/generate`)
  - [x] คำสั่ง `/summarize <คำค้น>` — ดึง chunk เยอะกว่า answer
  - [x] Q&A อิสระ: ข้อความธรรมดา → `rag.answer()` จาก corpus
  - [x] แนบ **แหล่งอ้างอิง** (ชื่อไฟล์) ท้ายคำตอบ + กรณีไม่พบข้อมูลตอบตรงๆ
- **เสร็จเมื่อ:** ถามเรื่องในเอกสาร → คำตอบถูก + บอกไฟล์ต้นทาง → **✅ verified กับ Ollama จริง** (ถาม "บริษัทรับสมัครตำแหน่งอะไร" → "วิศวกรโยธา" จาก OCR ของ PNG)
- **ต้องมีก่อน:** Phase 4

### Phase 6 — Polish & Hardening 🚧
- **เป้า:** ระบบทนทาน ใช้งานจริงได้
- **งาน:**
  - [x] error handling: ingest คืน status (`duplicate`/`unsupported`/`error`), bot จับ exception ตอน answer
  - [x] logging (bot) + สถานะงานใน DB (`processing`/`indexed`/`failed`)
  - [x] `README.md` วิธีติดตั้ง/รัน
  - [ ] จัดการ Ollama ล่ม/timeout ให้ผู้ใช้เห็นข้อความชัด (มี try/except พื้นฐานแล้ว — ปรับข้อความเพิ่มได้)
  - [ ] เขียน **run-skill** ด้วย `/run-skill-generator` (ปิดท้าย — หลังบอทรัน live ได้)
- **เสร็จเมื่อ:** clone ใหม่ในเครื่องเปล่า → ทำตาม README → บอททำงานครบ flow
- **ต้องมีก่อน:** Phase 5

---

## 5.5 ฟีเจอร์เสริม — สรุปรายไฟล์ + ถามเจาะรายหัวข้อ ✅ (เพิ่มหลัง core)

- [x] `vectordb.search(doc_id=...)` + `get_document_chunks()` — retrieval scope เฉพาะเอกสารเดียว
- [x] `rag.summarize_document()` — สรุปทั้งไฟล์เป็นหัวข้อ + bullet ย่อย (อ่านจากไฟล์ที่สกัด, cap 12k ตัวอักษร)
- [x] `rag.answer(doc_id=...)` — Q&A scope รายไฟล์
- [x] บอท: `/doc <id>` (สรุป + เข้าโหมดคุยกับไฟล์นั้น), `/all` (กลับทั้งคลัง); เก็บ scope ใน `user_data`
- [x] `textutil.clean_text()` — ตัด base64 image / อักขระ PUA / บรรทัดว่างซ้ำ ก่อน embed+สรุป (ใช้ใน vectordb + rag)
- [x] `SUMMARY_SYSTEM` prompt — เอกสารสั้น/ฟอร์มเปล่า → บรรยายประเภท+หัวข้อ แทนตอบ "ไม่พบข้อมูล"
- **verified (test ละเอียด 7/7 ไฟล์):** สรุปได้ทุกไฟล์เป็นหัวข้อ+bullet ✅ · doc 1 (ฟอร์มบันทึกข้อความเปล่า, เนื้อหา placeholder "กกกก") → บอก "เอกสารเปล่า (แบบฟอร์ม) + ช่อง: ส่วนราชการ/ภาคเหตุ/ภาคความประสงค์/ภาคสรุป" ✅ · scoped Q&A ต่อไฟล์ ✅
- **หมายเหตุ:** บอทรันเป็น harness background task (nohup/setsid ไม่เสถียรในสภาพแวดล้อมนี้)

## 5.6 ฟีเจอร์เสริม — Document Overview (เก็บใน SQLite + Chroma) ✅

- [x] `rag.describe_document()` — สร้าง overview 2-4 ประโยค (ประเภทเอกสาร + เนื้อหาโดยรวม) ตอน ingest
- [x] `store` คอลัมน์ `summary` + migration (`ALTER TABLE` ให้ DB เก่า) + `set_summary()`
- [x] `vectordb.index_summary()` — embed overview เป็น vector 1 ตัว (`chunk_idx=-1`, `kind='summary'`) → **ค้นระดับเอกสารได้**
- [x] pipeline สร้าง overview อัตโนมัติ (try/except — Ollama ล่มก็ยัง index ได้), บอทโชว์ 📝 ตอนอัปโหลด + ใน `/doc`
- **verified:** backfill 7/7 ไฟล์มี overview · ค้น "เอกสารเกี่ยวกับการรับสมัครงาน" → summary vector ไฟล์รับสมัครอันดับ 1 (dist 0.325) ✅
- **หมายเหตุ:** ingest ตอนนี้เรียก Ollama 1 ครั้ง/ไฟล์ (ช้าขึ้นเล็กน้อย); `get_document_chunks` ข้าม vector สรุปแล้ว

## 6. ความเสี่ยง & ข้อควรระวัง

| ความเสี่ยง | ผลกระทบ | การรับมือ |
|-----------|--------|-----------|
| PaddleOCR/paddlepaddle ลงยาก/หนัก | Phase 1 (image) สะดุด | scope เหลือแค่รูปเดี่ยว; ถ้าลงไม่ไหวใช้ opendataloader OCR (แปลงรูป→PDF) แทน |
| RAM ≤8GB จำกัดขนาด LLM | สรุปได้จำกัด | ล็อก `qwen2.5:3b`; คุม top-k + ความยาว context ให้พอดี window |
| opendataloader ต้องใช้ Java 11+ | รันไม่ได้ | เช็ก `java -version` ใน Phase 0; ลง JRE ถ้าขาด |
| ภาษาไทยตัด chunk/embedding เพี้ยน | ค้นไม่เจอ | ใช้ multilingual embedding + ทดสอบ retrieval จริงใน Phase 3 |
| ไฟล์ scan คุณภาพต่ำ | OCR ผิด | preprocess รูป (grayscale/contrast) ตาม smart-ocr |

---

## 7. Backlog (อนาคต — นอกขอบเขตเฟสแรก)

**ออกแบบไว้แล้ว (ดู ADR + AUDIT):**
- ✅ [PostgreSQL store](./ARCHITECTURE.md#adr-008) — **implemented ผ่าน Docker** (`docker-compose.yml`, host:5434), store.py = SQLAlchemy Core, migrate รักษา doc_id เสร็จ · บอทรัน backend=postgresql แล้ว
- 🟡 [Folder + หมวดหมู่](./ARCHITECTURE.md#adr-009) — **Folders + `/list` tree + `/mkfolder`/`/mv`/`/folder` เสร็จ**; auto-category ยังไม่ทำ
- [RBAC](./ARCHITECTURE.md#adr-010) — users/roles ต่อยอด `ALLOWED_USER_IDS`
- [Audit ความเสี่ยง + module ที่จำเป็น](./AUDIT.md) — เร่งด่วน: file-size guard (R1), sanitize PII (R2)

**อื่นๆ:**
- Web UI ดู corpus + citation
- ลบเอกสารผ่าน chat (`/rm <id>` — มี `delete_document`/`store.delete` แล้ว)
- Hybrid search (keyword + vector)
- รองรับ audio/video transcription
