# Architecture Decision Records — OCR-File-Chat

> เขียนด้วยรูปแบบ **ADR** ตาม skill `/architecture`
> ระบบ: รับไฟล์เอกสารทาง Telegram → สกัด → เก็บเป็น Single Source of Truth → สรุป/ตอบทาง chat
> **ข้อจำกัดหลัก (constraints):** รัน local ทั้งหมด, ไม่มีค่า API, เครื่องผู้ใช้สเปคทั่วไป (ไม่มี GPU), รองรับภาษาไทย, mini project (เน้นเรียบง่าย)

## สารบัญ
- [ADR-001: Extraction pipeline (router + multi-extractor)](#adr-001)
- [ADR-002: Metadata store — SQLite](#adr-002)
- [ADR-003: Vector database — ChromaDB](#adr-003)
- [ADR-004: Embedding model — multilingual MiniLM](#adr-004)
- [ADR-005: Summarization LLM — Ollama (local)](#adr-005)
- [ADR-006: Chat interface — python-telegram-bot](#adr-006)
- [ADR-007: "Single Source of Truth" — สอง store ผูกด้วย doc_id](#adr-007)
- [ADR-008: รองรับ PostgreSQL (DATABASE_URL + SQLAlchemy Core)](#adr-008)
- [ADR-009: Folder + หมวดหมู่ (Categorization)](#adr-009)
- [ADR-010: RBAC (อนาคต — ออกแบบไว้ก่อน)](#adr-010)

> **สถานะ:** ADR-001–007 = implemented ✅ · ADR-008–010 = design/config (ยังไม่ implement เต็ม) · Audit: [AUDIT.md](./AUDIT.md)

---

<a name="adr-001"></a>
# ADR-001: Extraction pipeline — Router + Multi-extractor

**Status:** Accepted
**Date:** 2026-07-11
**Deciders:** เจ้าของโปรเจกต์

## Context
ระบบต้องรองรับ "เอกสารทั่วไปทั้งหมด" — PDF (text + สแกน), Office (docx/xlsx/pptx), และรูปภาพ
ไม่มีเครื่องมือตัวเดียวที่ทำได้ดีทุกชนิด: opendataloader-pdf เก่งเฉพาะ PDF, PaddleOCR เก่งเฉพาะรูป/OCR

## Decision
ใช้ **router pattern**: ตรวจชนิดไฟล์ด้วย `python-magic` (magic bytes ไม่ใช่นามสกุล) แล้วส่งต่อ extractor เฉพาะทาง
ทุก extractor คืน interface เดียวกัน `Document(text, markdown, meta)`

- PDF (text + สแกน) → **opendataloader-pdf** (local mode, XY-Cut++ reading order; OCR ในตัวจัดการ PDF สแกนเอง)
- Office (docx/xlsx/pptx) → **markitdown** (Microsoft, pure-python, เบา — office เป็น XML มีโครงสร้างอยู่แล้ว ไม่ต้องใช้ ML)
- รูปเดี่ยว (jpg/png) → **PaddleOCR** (จาก skill `smart-ocr`, `lang=['th','en']`)

> **หมายเหตุ scope OCR:** PaddleOCR ใช้เฉพาะ **ไฟล์รูปเดี่ยว** เท่านั้น เพื่อเลี่ยงการลง/รัน paddle ซ้อนกับ OCR ของ opendataloader (PDF สแกน) — ลด dependency ที่หนักบนเครื่อง RAM ≤8GB

## Options Considered

### Option A: opendataloader-pdf อย่างเดียว
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | ฟรี |
| Scalability | ครอบคลุมแค่ PDF |
| Team familiarity | Med |

**Pros:** simple, dependency น้อย
**Cons:** ไม่รองรับ docx/xlsx/รูปโดยตรง — ผิดเป้า G3

### Option B: Router + opendataloader + markitdown + PaddleOCR(รูปเดี่ยว) ✅
| Dimension | Assessment |
|-----------|------------|
| Complexity | Med |
| Cost | ฟรี (local) |
| Scalability | ครอบคลุมทุกชนิดที่ต้องการ, เพิ่ม extractor ใหม่ได้ |
| Team familiarity | Med — มี skill `smart-ocr` ช่วยส่วน OCR |

**Pros:** เลือกเครื่องมือที่ดีที่สุดต่อชนิด (opendataloader คุม PDF, markitdown เบาสำหรับ office, paddle เฉพาะรูป), ขยายง่าย, ใช้ skill ที่ลงไว้
**Cons:** ต้องดูแล interface กลาง; paddle ยังหนักตอนลง (จำกัด scope เหลือแค่รูปเดี่ยวช่วยลดผลกระทบ)

### Option C: docling ตัวเดียว (รองรับ PDF/office/รูปในตัว)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low-Med |
| Cost | ฟรี แต่หน้า complex ดึง model มา |
| Scalability | กว้าง แต่คุมคุณภาพต่อชนิดยาก |
| Team familiarity | Low |

**Pros:** ตัวเดียวจบ
**Cons:** ทิ้งจุดเด่น opendataloader (โจทย์ตั้งต้นคือ clone ตัวนี้มาใช้) + ทิ้ง skill smart-ocr

## Trade-off Analysis
Option B แลกความซับซ้อนเล็กน้อยกับความครอบคลุมและการได้ใช้เครื่องมือที่แข็งที่สุดต่อชนิด
โจทย์ระบุให้ clone opendataloader มาใช้ + เพิ่งลง skill smart-ocr(PaddleOCR) → B ใช้ของที่มีอยู่ให้คุ้ม
router interface ทำให้ downgrade ไป A/C ได้ทีหลังโดยไม่กระทบส่วนอื่น

## Consequences
- ✅ ง่ายในการเพิ่มชนิดไฟล์ใหม่ (แค่เพิ่ม extractor + ลง router)
- ✅ ส่วน OCR ใช้ domain knowledge จาก skill `smart-ocr` ได้ทันที
- ⚠️ PaddlePaddle/PaddleOCR ลงหนักและบางเครื่องยุ่งยาก → มี fallback (ADR ระบุใน risk table ของ PLAN)
- ⚠️ ต้องรักษา `Document` interface ให้นิ่ง

## Action Items
1. [ ] `extractors/base.py` นิยาม `Document` + `extract(path)`
2. [ ] router map: mime → extractor
3. [ ] fallback OCR ถ้า paddle ลงไม่ได้

---

<a name="adr-002"></a>
# ADR-002: Metadata store — SQLite

**Status:** Accepted
**Date:** 2026-07-11

## Context
ต้องเก็บ metadata ของทุกไฟล์ (ชนิด, hash, ผู้ส่ง, เวลา, สถานะ) เพื่อ query, dedup, และผูกกับ vector store
เป็น mini project รันเครื่องเดียว ผู้ใช้น้อย

## Decision
ใช้ **SQLite** (ไฟล์เดียว `data/metadata.db`) ผ่าน `sqlite3` มาตรฐานของ Python

## Options Considered

### Option A: SQLite ✅
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low — ไม่ต้องตั้ง server |
| Cost | ฟรี, built-in |
| Scalability | พอสำหรับ single-node/ผู้ใช้น้อย |

**Pros:** zero-setup, พกพาไฟล์เดียว, ธุรกรรม ACID
**Cons:** ไม่เหมาะ concurrent write สูง (ไม่ใช่ปัญหาที่นี่)

### Option B: PostgreSQL (+ pgvector)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Med-High — ต้องรัน server |
| Cost | ฟรีแต่มี overhead ติดตั้ง |
| Scalability | สูง, รวม vector ในที่เดียวได้ |

**Pros:** ถ้าใช้ pgvector จะรวม metadata + vector เป็น DB เดียว
**Cons:** เกินความจำเป็นของ mini project, setup หนัก

## Trade-off Analysis
Postgres+pgvector น่าสนใจเพราะรวม store ได้ แต่แลกด้วย setup ที่ขัดกับหลัก "เรียบง่าย + local"
SQLite (metadata) + Chroma (vector) แยกกันแต่ผูกด้วย `doc_id` (ดู ADR-007) เพียงพอและตั้งค่าเป็นศูนย์

## Consequences
- ✅ เริ่มได้ทันที ไม่มี service ต้องดูแล
- ⚠️ ถ้าโตเป็น multi-user/concurrent สูง ค่อยย้ายไป Postgres (schema เดียวกัน migrate ได้)

## Action Items
1. [ ] schema `documents` + index บน `sha256`
2. [ ] `store.py` CRUD + dedup

---

<a name="adr-003"></a>
# ADR-003: Vector database — ChromaDB

**Status:** Accepted
**Date:** 2026-07-11

## Context
ต้องเก็บ embedding ของ chunks และค้นแบบ semantic — เป็นหัวใจของ "Single Source of Truth" ที่ RAG ดึงไปสรุป
ต้องการ local, persist ลงดิสก์, ตั้งค่าง่าย

## Decision
ใช้ **ChromaDB** แบบ persistent client (`data/chroma/`)

## Options Considered

### Option A: ChromaDB ✅
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low — `pip install chromadb`, embedded mode |
| Cost | ฟรี, local |
| Scalability | พอสำหรับหลักหมื่น-แสน chunks |

**Pros:** API ง่ายสุด, persist ในตัว, metadata filter ได้, ใส่ embedding เองหรือให้ auto ก็ได้
**Cons:** ไม่เหมาะ scale ใหญ่มาก/distributed

### Option B: Qdrant (local/docker)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Med — รันผ่าน docker/binary |
| Cost | ฟรี |
| Scalability | สูง, filtering ทรงพลัง |

**Pros:** โปรดักชันเกรด, เร็ว
**Cons:** ต้องรัน service แยก — เกินจำเป็นเฟสแรก

### Option C: pgvector (ใน Postgres)
**Pros:** รวมกับ metadata store
**Cons:** ผูกกับการเลือก Postgres (ดู ADR-002 — เราเลือก SQLite)

## Trade-off Analysis
Qdrant/pgvector แข็งแรงกว่าแต่ต้องมี service/DB server
ChromaDB embedded ให้ semantic search ครบโดยไม่มี ops overhead — ตรงหลัก "local + เรียบง่าย"
Abstraction ใน `vectordb.py` ทำให้สลับไป Qdrant ทีหลังได้ถ้าต้องการ

## Consequences
- ✅ semantic search ใช้ได้ทันที ไม่มี service เพิ่ม
- ✅ metadata payload (`doc_id`) ผูกกลับ SQLite ได้ (ADR-007)
- ⚠️ ถ้า corpus โตมากค่อยพิจารณา Qdrant

## Action Items
1. [ ] `vectordb.py` wrapper: `upsert`, `search`
2. [ ] เก็บ `doc_id`, `chunk_idx`, `source_filename` ใน payload

---

<a name="adr-004"></a>
# ADR-004: Embedding model — paraphrase-multilingual-MiniLM-L12-v2

**Status:** Accepted
**Date:** 2026-07-11

## Context
เอกสารเป็น "ทั่วไปทั้งหมด" และคาดว่ามี **ภาษาไทย** ผู้ใช้เลือก "local เบาๆ ไม่หนักเครื่อง (ไม่มี GPU)"
คุณภาพ retrieval ขึ้นกับ embedding ที่เข้าใจภาษาไทย

## Decision
ใช้ **`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`** (~470MB) รันบน CPU

## Options Considered

### Option A: all-MiniLM-L6-v2 (~80MB)
| Dimension | Assessment |
|-----------|------------|
| ขนาด | เล็กมาก |
| ภาษาไทย | ❌ อ่อน (เทรนอังกฤษเป็นหลัก) |
| ความเร็ว | เร็วสุด |

**Cons:** retrieval ภาษาไทยแย่ → ขัดเป้า G4/G5

### Option B: paraphrase-multilingual-MiniLM-L12-v2 (~470MB) ✅
| Dimension | Assessment |
|-----------|------------|
| ขนาด | ปานกลาง (ยังเบา, CPU ไหว) |
| ภาษาไทย | ✅ รองรับ 50+ ภาษา |
| ความเร็ว | เร็วบน CPU |

**Pros:** สมดุลที่สุดระหว่างเบา + รองรับไทย
**Cons:** ใหญ่กว่า all-MiniLM ~6 เท่า (ยังถือว่าเล็ก)

### Option C: BAAI/bge-m3 (~2.2GB)
| Dimension | Assessment |
|-----------|------------|
| ขนาด | ใหญ่ |
| ภาษาไทย | ✅ ดีมาก, รองรับ long context |
| ความเร็ว | ช้ากว่าบน CPU |

**Pros:** คุณภาพสูงสุด, multilingual + hybrid
**Cons:** หนักเกินคำสั่ง "ไม่หนักเครื่อง"

## Trade-off Analysis
all-MiniLM เบาสุดแต่ทิ้งภาษาไทย = ใช้ไม่ได้จริง; bge-m3 ดีสุดแต่หนักเกินข้อจำกัด
Option B คือจุดสมดุล: เบาพอรัน CPU สบาย + รองรับไทย → ตรงทั้งคำสั่งผู้ใช้และเป้าคุณภาพ
ถ้าภายหลังคุณภาพ retrieval ไม่พอ ค่อย upgrade เป็น bge-m3 (เปลี่ยนแค่ชื่อ model ใน config)

## Consequences
- ✅ retrieval ภาษาไทยใช้งานได้จริง โดยไม่กินทรัพยากรมาก
- ⚠️ dimension = 384 → ผูกกับ collection ของ Chroma (เปลี่ยน model ต้อง re-index)

## Action Items
1. [ ] ตั้ง `EMBEDDING_MODEL` ใน config
2. [ ] ทดสอบ retrieval ด้วยคำถามไทยจริงใน Phase 3

---

<a name="adr-005"></a>
# ADR-005: Summarization LLM — Ollama (local)

**Status:** Accepted
**Date:** 2026-07-11

## Context
ต้องสรุป/ตอบคำถามจาก context ที่ retrieve มา ผู้ใช้เลือก **Local (Ollama)** — ไม่มีค่า API, ข้อมูลไม่ออกนอกเครื่อง
ต้องตอบภาษาไทยได้ดีและรันบนเครื่อง **RAM ≤8GB (ไม่มี GPU)** → ขนาด model ถูกจำกัดที่ ~3B

## Decision
ใช้ **Ollama** เป็น LLM runtime, model **`qwen2.5:3b`** (ล็อกไว้ — เครื่องเป้าหมาย RAM ≤8GB; `7b`/`14b` ไว้พิจารณาเมื่ออัปเกรดแรมภายหลัง)

## Options Considered

### Option A: Ollama + qwen2.5:3b ✅ (เหมาะ RAM ≤8GB)
| Dimension | Assessment |
|-----------|------------|
| ขนาด/แรม | ~2-3GB, พอดีเครื่อง 8GB, CPU ไหว |
| ภาษาไทย | ✅ Qwen เก่งไทยกว่า Llama รุ่นเล็ก |
| Cost | ฟรี, local |

**Pros:** เบา, ภาษาไทยดี, ตั้งค่าง่าย (`ollama pull`), มี REST API — **รันได้บน 8GB โดยไม่ swap หนัก**
**Cons:** คุณภาพ reasoning สู้ 7B/API ไม่ได้ (พอสำหรับสรุป RAG); ต้องคุมความยาว context ให้พอดี

### Option B: Ollama + llama3.2:3b
**Pros:** นิยม, เบาพอกัน
**Cons:** ภาษาไทยอ่อนกว่า Qwen ในขนาดใกล้กัน

### Option C: Cloud API (Claude/GPT)
**Pros:** คุณภาพสูงสุด, ไม่กินเครื่อง
**Cons:** ❌ ขัดข้อกำหนด "local, ไม่มีค่า API, ข้อมูลไม่ออกนอกเครื่อง"

## Trade-off Analysis
ผู้ใช้ล็อกเป็น local แล้ว → ตัด Option C ออก
ระหว่างเล็ก 3B: Qwen ชนะเรื่องภาษาไทย → เลือก qwen2.5:3b เป็น default
Abstraction ใน `rag.py` (เรียกผ่าน Ollama REST) ทำให้สลับ model/ขนาดได้ด้วยการแก้ config

## Consequences
- ✅ ข้อมูลไม่ออกนอกเครื่อง, ไม่มีค่าใช้จ่าย, รันบน 8GB ได้
- ✅ เปลี่ยนเป็น 7b/14b ได้เมื่ออัปเกรดแรม (แก้ `OLLAMA_MODEL` อย่างเดียว — abstraction รองรับ)
- ⚠️ 3B reasoning จำกัด → prompt ต้องชัด, งานเน้น "สรุปจาก context" ไม่ใช่ reasoning ซับซ้อน
- ⚠️ ต้องมี Ollama service รันอยู่ + จัดการกรณี service ล่ม (Phase 6)
- ⚠️ context window จำกัด → ต้องคุมจำนวน chunk ที่ยัดเข้า prompt (top-k เล็ก)

## Action Items
1. [ ] ตั้ง `OLLAMA_MODEL`, `OLLAMA_HOST` ใน config
2. [ ] `rag.py` เรียก Ollama `/api/generate` (หรือ `/api/chat`)
3. [ ] จำกัด top-k + ตัด context ให้พอดี window

---

<a name="adr-006"></a>
# ADR-006: Chat interface — python-telegram-bot

**Status:** Accepted
**Date:** 2026-07-11

## Context
ต้องรับไฟล์และโต้ตอบผ่าน Telegram โจทย์เดิมเคยพิจารณา skill `chatbot-builder` แต่พบว่าเป็น integration
กับแพลตฟอร์ม Chatbot Builder (chatbot.com) ผ่าน Membrane — ต้องมีบัญชี/network, **ไม่ตรงกับ Telegram**

## Decision
เขียน bot เองด้วย **`python-telegram-bot`** (async) — คุมทุกอย่าง, local, ฟรี

## Options Considered

### Option A: python-telegram-bot ✅
**Pros:** library มาตรฐาน, docs ดี, async, จัดการ file download ในตัว, ไม่มี dependency บริการภายนอก
**Cons:** ต้องเขียน handler เอง (แต่ควบคุมได้เต็มที่)

### Option B: skill chatbot-builder (Membrane)
**Pros:** มี action สำเร็จรูป
**Cons:** ❌ ผูกกับแพลตฟอร์ม Chatbot Builder ไม่ใช่ Telegram, ต้องมีบัญชี Membrane + network — ผิดหลัก local

## Trade-off Analysis
chatbot-builder แก้คนละปัญหา (SaaS CRM chatbot) — ไม่ช่วยงาน Telegram
python-telegram-bot ตรงเป้า, local, และผูกกับ pipeline ของเราได้ตรงๆ

## Consequences
- ✅ ควบคุม flow เต็มที่ (dedup, สถานะ, คำสั่ง `/list` `/summarize`)
- ⚠️ ต้องมี `TELEGRAM_BOT_TOKEN` (สร้างจาก @BotFather)
- ℹ️ skill `chatbot-builder` เก็บไว้เผื่ออนาคตถ้าต้องต่อ CRM

## Action Items
1. [ ] สร้าง bot token จาก @BotFather → ใส่ `.env`
2. [ ] `bot.py`: handlers `on_document`, `on_message`, `/start`, `/list`, `/summarize`

---

<a name="adr-007"></a>
# ADR-007: "Single Source of Truth" — สอง store ผูกด้วย doc_id

**Status:** Accepted
**Date:** 2026-07-11

## Context
โจทย์ต้องการให้ข้อมูลเป็น "Single Source of Truth" แต่เราใช้ 2 store (SQLite = metadata, Chroma = vector)
ต้องออกแบบให้ไม่เกิดข้อมูลกำกวม/ซ้ำซ้อน และ dedup ไฟล์เดิมได้

## Decision
- **ไฟล์ต้นฉบับ** ตั้งชื่อด้วย `sha256` เก็บที่ `data/raw/<hash>` → hash คือ identity ของเอกสาร
- **SQLite** เป็น system-of-record ของ metadata (แหล่งความจริงเรื่อง "มีเอกสารอะไรบ้าง") มี `doc_id` (PK)
- **Chroma** เก็บเฉพาะ embedding + payload ที่อ้าง `doc_id` กลับ SQLite เสมอ
- **dedup:** ก่อนประมวลผลเช็ก `sha256` ใน SQLite — ถ้ามีแล้วไม่ทำซ้ำ (ไฟล์เดียว = record เดียว = ชุด vector เดียว)

## Options Considered

### Option A: SQLite เป็น record หลัก + Chroma อ้าง doc_id ✅
**Pros:** แต่ละเอกสารมีตัวตนเดียว (hash), ไม่ซ้ำ, ลบ/อัปเดตตามหลังได้, query metadata แยกจาก vector
**Cons:** ต้องรักษาความสอดคล้อง 2 store (mitigate ด้วยลำดับ: insert metadata → index → update สถานะ)

### Option B: เก็บทุกอย่างใน Chroma (metadata เป็น payload)
**Pros:** store เดียว
**Cons:** query/aggregate metadata ลำบาก, ไม่มีธุรกรรม, dedup ยุ่งยาก

### Option C: Postgres + pgvector (store เดียวจริง)
**Pros:** SSoT ในเชิงกายภาพ store เดียว
**Cons:** ขัด ADR-002/003 (setup หนัก เกินจำเป็น)

## Trade-off Analysis
"Single Source of Truth" ในที่นี้คือ **แต่ละเอกสารมี identity เดียว (hash) และ metadata มีแหล่งเดียว (SQLite)**
ไม่จำเป็นต้องเป็น physical store เดียว การผูกด้วย `doc_id` + dedup ด้วย hash ให้ความจริงหนึ่งเดียวเชิงตรรกะ
ความสอดคล้องระหว่าง store คุมได้ด้วย state machine ของสถานะ (`processing → indexed`/`failed`)

## Consequences
- ✅ ไฟล์ซ้ำไม่ถูกประมวลผล/index ซ้ำ
- ✅ ตรวจสอบย้อนได้ว่าทุก chunk มาจากเอกสารไหน (citation)
- ✅ ลบเอกสาร = ลบ record + ลบ vector ตาม `doc_id` (backlog)
- ⚠️ ต้องกัน orphan: ถ้า index ล้มกลางทาง → สถานะ `failed` + retry/ล้าง

## Action Items
1. [ ] hash-based naming ใน `data/raw/`
2. [ ] ลำดับเขียน: metadata(processing) → extract → vector upsert → metadata(indexed)
3. [ ] payload ใน Chroma ต้องมี `doc_id` ทุก chunk

---

<a name="adr-008"></a>
# ADR-008: รองรับ PostgreSQL (DATABASE_URL + SQLAlchemy Core)

**Status:** ✅ Accepted & Implemented — ใช้ **Docker** (`postgres:17-alpine` @ host **5434**)
**Date:** 2026-07-11

## Context
อนาคตต้องการ Postgres (multi-user, RBAC, query ซับซ้อน, concurrent write) เครื่อง dev มี **Postgres 18 รันอยู่ @ localhost:5432** แล้ว
SQLite ยังเหมาะกับ dev/เดี่ยว จึงอยากได้ทั้งสองแบบโดยไม่เขียนโค้ดซ้ำ

## Decision
- เพิ่ม `DATABASE_URL` (default `sqlite:///data/metadata.db`) — สลับเป็น Postgres ด้วย env เดียว
- refactor `store.py` ใช้ **SQLAlchemy Core** (ไม่ใช่ ORM เต็ม) → dialect เดียวรองรับทั้ง SQLite + Postgres
- เก็บ SQLite เป็น default; Postgres เปิดเมื่อพร้อม

## Options Considered
| Option | Complexity | หมายเหตุ |
|--------|-----------|---------|
| A. เขียน SQL 2 ภาษาเอง | Med | เปราะ, ต้อง maintain 2 ชุด |
| **B. SQLAlchemy Core** ✅ | Med | โค้ดชุดเดียว, พอดี ไม่หนักเกิน |
| C. ORM เต็ม (models/relationships) | High | over-engineer สำหรับ mini project |
| D. ย้ายไป Postgres ล้วน ทิ้ง SQLite | Low-Med | เสีย zero-setup dev, ต้องมี PG ตลอด |

## Trade-off / ข้อควรระวัง (สำคัญ)
⚠️ **doc_id ใน Chroma payload ผูกกับ PK ของ metadata** — การย้าย store ต้อง **รักษา doc_id เดิม** ไม่งั้น vector หลุดจาก metadata
แผน migration: (1) สร้าง schema ใน PG → (2) copy rows พร้อม id เดิม (`OVERRIDING SYSTEM VALUE`) หรือ (3) re-ingest ใหม่ทั้งหมด (Chroma ล้างแล้วสร้างใหม่)

## Consequences
- ✅ รองรับ concurrent + เป็นฐานของ RBAC/folders (ADR-009/010)
- ➕ deps: `sqlalchemy`, `psycopg[binary]`
- ⚠️ ต้องมี Postgres service รันอยู่เมื่อเปิดใช้

## Action Items
1. [x] เพิ่ม `DATABASE_URL`, `DB_BACKEND` ใน config + .env
2. [x] Postgres ผ่าน **Docker** (`docker-compose.yml`, host:5434) แทนการใช้ PG ของ host โดยตรง — แยกสะอาด
3. [x] refactor `store.py` → SQLAlchemy Core (รองรับ SQLite + Postgres API เดิม)
4. [x] `scripts/migrate_sqlite_to_pg.py` — ย้าย 7 rows **รักษา id 1-7** + reset sequence → doc_id linkage (Chroma↔PG) ยังตรง (verified)

> **Verified:** ingest จริงผ่าน PG (id ต่อถูก), search Chroma → get PG ตรง doc_id, บอทรันด้วย backend=postgresql

---

<a name="adr-009"></a>
# ADR-009: Folder + หมวดหมู่ (Categorization)

**Status:** Proposed (design)
**Date:** 2026-07-11

## Context
ผู้ใช้ต้องการ **จัดไฟล์เป็นโฟลเดอร์** + **หมวดหมู่** เพื่อค้น/กรอง และเป็นขอบเขตของสิทธิ์ (RBAC ในอนาคต)

## Decision
**Data model** (เพิ่มใน metadata store):
```
folders(id, name, parent_id → folders.id, owner, created_at)   -- ต้นไม้ (hierarchy)
documents.folder_id → folders.id  (nullable = root/ยังไม่จัด)
documents.category  TEXT          -- หมวดหมู่ (auto จาก LLM ตอน ingest)
-- อนาคต: tags many-to-many  document_tags(document_id, tag)
```
**หมวดหมู่อัตโนมัติ:** ต่อยอดจาก `describe_document` ที่มีอยู่ — ให้ LLM จัดหมวดจาก taxonomy คงที่
(`ระเบียบ/รายงาน/แบบฟอร์ม/ประกาศ/สัญญา/หนังสือราชการ/อื่นๆ`) แล้วเก็บ `documents.category`
> โมเดลปัจจุบันก็ระบุประเภทได้อยู่แล้ว (เห็นจาก overview: "เอกสารเป็นแบบฟอร์ม/ระเบียบ...")

**Chroma:** เพิ่ม `folder_id` + `category` ใน payload ของ chunk/summary → retrieval filter ตามโฟลเดอร์/หมวดได้

## Flow
- **Ingest:** ผู้ใช้ตั้ง "โฟลเดอร์ปัจจุบัน" (คำสั่ง `/folder <ชื่อ>` เก็บใน user_data) → ไฟล์ใหม่เข้าโฟลเดอร์นั้น + auto-category
- **Query:** `/folder <ชื่อ>` scope การค้นเฉพาะโฟลเดอร์; หรือถามข้ามทั้งคลังตามเดิม
- **จัดการ:** `/folders` ดูรายการ, `/mv <doc_id> <folder>` ย้าย

## Options
| Option | หมายเหตุ |
|--------|---------|
| A. tags แบนๆ อย่างเดียว | ง่ายสุด แต่ไม่มีลำดับชั้น |
| **B. โฟลเดอร์ (tree) + auto-category** ✅ | สมดุล ตอบโจทย์ + เป็นฐาน RBAC |
| C. taxonomy management UI เต็ม | over-engineer ตอนนี้ |

## Consequences
- ✅ จัดระเบียบ + กรอง retrieval ได้ + เป็นขอบเขตสิทธิ์
- ⚠️ Chroma payload เดิมยังไม่มี folder_id → ต้อง backfill (หรือ default root)
- ผูกกับ ADR-008 (โครง relational เหมาะกับ Postgres มากขึ้นเมื่อมี hierarchy/FK)

## Action Items
1. [ ] ตาราง `folders` + `documents.folder_id`, `documents.category`
2. [ ] auto-category ใน `describe_document` step
3. [ ] คำสั่งบอท `/folder`, `/folders`, `/mv`
4. [ ] เพิ่ม folder_id/category ใน Chroma payload + filter

---

<a name="adr-010"></a>
# ADR-010: RBAC (อนาคต — ออกแบบไว้ก่อน)

**Status:** Proposed (design เท่านั้น — ยังไม่ implement)
**Date:** 2026-07-11

## Context
เมื่อมีหลายผู้ใช้ ต้องจำกัด "ใครเห็น/จัดการโฟลเดอร์-เอกสารไหนได้"
ปัจจุบันมี `ALLOWED_USER_IDS` (allowlist) = **เมล็ดพันธุ์ของ RBAC** (all-or-nothing)

## Decision (ออกแบบ, ยังไม่ทำ)
**Data model:**
```
users(id, telegram_id unique, name, created_at)
roles(id, name)                       -- admin / editor / viewer
user_roles(user_id, role_id)
folder_acl(folder_id, subject_type, subject_id, permission)  -- read/write ต่อโฟลเดอร์ (เฟรมภายหลัง)
```
**Enforcement:** decorator ในบอท (ต่อยอดจาก `restricted`) เช็คสิทธิ์ก่อน ingest/query/summarize
**เริ่มแบบง่าย:** global role ก่อน (admin ทำได้ทุกอย่าง, viewer อ่านอย่างเดียว) → ค่อยเพิ่ม per-folder ACL

## Options
| Option | หมายเหตุ |
|--------|---------|
| **A. global roles ง่ายๆ ก่อน** ✅ | เริ่มจากตรงนี้ ต่อยอด allowlist เดิม |
| B. per-folder ACL | ขั้นถัดไปเมื่อมีโฟลเดอร์ (ADR-009) |
| C. policy engine (Casbin ฯลฯ) | over-engineer ตอนนี้ |

## Consequences
- ต้องมี Postgres (ADR-008) + Folders (ADR-009) ก่อนจึงคุ้มทำเต็ม
- ⚠️ ต้องคิดเรื่อง PII/ความลับของเอกสารราชการควบคู่ (ดู AUDIT.md)

## Action Items (เมื่อถึงเวลา)
1. [ ] ตาราง users/roles/user_roles
2. [ ] global-role enforcement ในบอท (ต่อจาก `restricted`)
3. [ ] per-folder ACL (เฟสหลัง)
