# Audit — ความเสี่ยง & Module ที่จำเป็น (OCR-File-Chat)

> วันที่: 2026-07-11 · ขอบเขต: ระบบปัจจุบัน (Phase 0–5 + overview/folder-plan)
> หลักการ: **แก้เท่าที่จำเป็นจริง ไม่ Over-Engineer** — แต่ละข้อระบุ "ทำเลย / ทำเมื่อโต / ข้าม"

---

## 1. ความเสี่ยง (จัดลำดับตามผลกระทบ × โอกาส)

| # | ความเสี่ยง | สถานะปัจจุบัน | ผลกระทบ | ข้อเสนอ (ระดับ) |
|---|-----------|--------------|---------|----------------|
| R1 | **ไฟล์อันตราย/ใหญ่เกิน** — ไฟล์จาก Telegram ไม่จำกัดขนาด → soffice/paddle/embed อาจ OOM หรือ zip-bomb | ไม่มี guard | สูง | **ทำเลย**: จำกัดขนาดไฟล์ (เช่น ≤25MB) + timeout ต่อ extractor |
| R2 | **PII / ข้อมูลลับราชการ** เก็บ plaintext ใน `data/` + ส่งเข้า LLM | ไม่มีการปกปิด | สูง | **ทำเลย (ง่าย)**: opendataloader มี `sanitize=True` (แทน email/เบอร์/บัตร); ระบุ scope ผู้เข้าถึง (RBAC ADR-010) |
| R3 | **Secret ใน .env** — token เคยถูกวางในแชท | .env gitignored ✅ แต่ token exposed | กลาง | revoke/regenerate token; ระยะยาวใช้ secret manager เมื่อ deploy |
| R4 | **2-store consistency** — SQLite + Chroma ไม่มี transaction ร่วม, process ตายกลางทาง | มี status `failed`+retry แล้ว | กลาง | **พอแล้ว**; เพิ่ม cleanup job ลบ orphan เมื่อโต |
| R5 | **Ollama เป็น SPOF** — ล่ม → Q&A ตอบไม่ได้, overview ตอน ingest หาย | มี try/except + ข้อความ error | ต่ำ-กลาง | **พอแล้ว**; เพิ่ม health-check ตอน start (nice-to-have) |
| R6 | **Concurrency** — bot ประมวลผลหลายไฟล์พร้อมกัน (thread executor) เขียน SQLite/Chroma ชนกัน | เดี่ยว/โหลดต่ำ = ok | ต่ำ | **ทำเมื่อโต**: ย้าย Postgres (ADR-008) + คิว |
| R7 | **ไม่มี backup** — `data/` (db+vector+raw) หายคือหายหมด | ไม่มี | กลาง | **ทำเมื่อโต**: cron สำเนา `data/` / pg_dump |
| R8 | **Prompt injection** ผ่านเนื้อหาเอกสาร → หลอก LLM ตอนสรุป/ตอบ | ไม่มีการกัน | ต่ำ-กลาง | opendataloader มี content-safety filter; system prompt กันบางส่วนแล้ว |
| R9 | **ไม่มี test อัตโนมัติใน CI** — มีแต่ `local_ingest_test.py` รันมือ | manual | ต่ำ | **ทำเมื่อโต**: pytest + fixture ไฟล์ตัวอย่าง |

---

## 2. Module ที่ "จำเป็นจริง" (ควรเพิ่ม — เรียงความคุ้ม)

| Module | ทำไมจำเป็น | ขนาดงาน | เมื่อไหร่ |
|--------|-----------|---------|---------|
| **`limits`/guard** (R1) — เช็คขนาด+ประเภท+timeout ก่อน extract | กันระบบล่ม/OOM จากไฟล์เดียว | เล็ก | **ตอนนี้** |
| **`sanitize` flag** (R2) — เปิด opendataloader sanitize + ตัวเลือกใน config | เอกสารราชการมี PII จริง | เล็ก | **ตอนนี้** |
| **Postgres store** (ADR-008) | ฐานของ folders + RBAC + concurrent | กลาง | เมื่อเริ่ม multi-user |
| **Folders + category** (ADR-009) | ผู้ใช้ขอ + จัดระเบียบ + ขอบเขตสิทธิ์ | กลาง | ถัดไป |
| **RBAC** (ADR-010) | หลายผู้ใช้ + ข้อมูลลับ | กลาง-ใหญ่ | เมื่อมีผู้ใช้จริงหลายคน |
| **health/startup check** | บอกชัดว่า Ollama/DB พร้อมไหมตอน start | เล็ก | nice-to-have |
| **pytest + CI** | กันพังตอนแก้โค้ด | กลาง | เมื่อทีมโต |

---

## 3. สิ่งที่ **ไม่ควรทำตอนนี้** (Over-Engineering)

- ❌ **Message queue (Celery/Redis/RabbitMQ)** — โหลดปัจจุบันเดี่ยว, thread executor พอ
- ❌ **Kubernetes / microservices** — mini project, รันเครื่องเดียวพอ
- ❌ **ORM เต็ม + repository pattern หลายชั้น** — SQLAlchemy Core พอ (ADR-008)
- ❌ **Policy engine (Casbin/OPA)** สำหรับ RBAC — เริ่ม global role ง่ายๆ ก่อน
- ❌ **Vector DB แบบ distributed (Qdrant cluster/Milvus)** — Chroma embedded พอจนกว่าจะหลายแสน–ล้าน chunk
- ❌ **API gateway / auth server แยก** — allowlist + RBAC ในบอทพอระยะแรก
- ❌ **Multi-model router / GPU cluster** — qwen2.5:3b บน CPU พอสำหรับ RAG สรุป

---

## 4. สรุปข้อเสนอทันที — ✅ ทำแล้ว (2026-07-11)

1. **R1 — file-size guard** ✅ `MAX_FILE_MB` (default 25) ใน `config` + เช็คใน `pipeline.ingest_file` → คืน `too_large` · บอทตอบชัด
   - verified: ไฟล์ 3000B > limit → `too_large`
2. **R2 — sanitize PII** ✅ `SANITIZE` (default false) + `textutil.sanitize_pii()` มาสก์ email/เบอร์/เลขบัตร/บัตรเครดิต ครอบ **ทุกชนิดไฟล์**
   - verified: CSV มี email+เบอร์ → extracted เป็น `[EMAIL] [PHONE]` ไม่รั่ว

### ค้างไว้ (ทำเมื่อจำเป็น — ไม่เร่ง)
- **extractor timeout** (paddle/markitdown ในโปรเซส) — ต้อง isolate ด้วย subprocess/multiprocessing จึงจะ kill ได้ (soffice มี timeout 180s แล้ว) → เลี่ยง over-engineer ตอนนี้
- **plain text `.txt/.md`** ยัง `unsupported` — เพิ่มใน office extractor ได้ถ้าต้องการ (งานเล็ก)
