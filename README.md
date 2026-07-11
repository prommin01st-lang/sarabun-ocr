# OCR-File-Chat

ส่งไฟล์เอกสารทาง **Telegram** → ระบบแยกชนิด → สกัดเนื้อหา (รวม OCR) → เก็บเป็น **Single Source of Truth** (SQLite + Vector DB) → **ถาม/สั่งสรุป** กลับทาง chat ได้ — ทำงาน **local ทั้งหมด ไม่มีค่า API**

> เอกสารออกแบบ: [`docs/PLAN.md`](docs/PLAN.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (ADR)

## สถาปัตยกรรมย่อ
```
Telegram ──file──► router (magic) ──► extractor ──► SQLite (metadata) + ChromaDB (vector)
                     ├ PDF   → opendataloader-pdf                          │
                     ├ office→ markitdown                                  ▼
                     └ image → PaddleOCR                    Telegram ◄─ RAG (Ollama) ◄─ ค้น
```

## ความต้องการระบบ
- **Python 3.10+** (ทดสอบบน 3.12)
- **Java 11+** (opendataloader-pdf เรียก JAR) — เช็ก `java -version`
- **libmagic** (python-magic) — Ubuntu: `sudo apt-get install libmagic1`
- **LibreOffice** (`soffice`) — สำหรับแปลงไฟล์ Word/Excel/PowerPoint **เก่า** (.doc/.xls/.ppt) — Ubuntu: `sudo apt-get install libreoffice`
- **Ollama** — ติดตั้งจาก https://ollama.com แล้ว `ollama pull qwen2.5:3b`

> **หมายเหตุ PaddleOCR:** บาง CPU build ของ paddlepaddle ชน oneDNN bug — โค้ดตั้ง `FLAGS_use_mkldnn=0` + `enable_mkldnn=False` ให้อัตโนมัติแล้ว

## ติดตั้ง
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# clone extractor หลัก (ถ้ายังไม่มี)
git clone --depth 1 https://github.com/opendataloader-project/opendataloader-pdf.git external/opendataloader-pdf

cp .env.example .env      # ใส่ TELEGRAM_BOT_TOKEN (ขอจาก @BotFather)
```

### Database (เลือกอย่างใดอย่างหนึ่ง)
- **SQLite** (default) — ไม่ต้องทำอะไร (`data/metadata.db`)
- **PostgreSQL ผ่าน Docker** (แนะนำเมื่อจะขยาย/multi-user):
  ```bash
  docker compose up -d          # postgres:17-alpine ที่ host:5434
  # ตั้งใน .env:
  # DATABASE_URL=postgresql+psycopg://ocr:ocr_local_pw@localhost:5434/ocr_file_chat
  # ย้ายข้อมูลเดิม (ถ้ามี) รักษา doc_id:
  .venv/bin/python scripts/migrate_sqlite_to_pg.py \
      "sqlite:///$(pwd)/data/metadata.db" \
      "postgresql+psycopg://ocr:ocr_local_pw@localhost:5434/ocr_file_chat"
  ```

## รัน
```bash
# ติดตั้ง + สตาร์ท Ollama ก่อน
ollama pull qwen2.5:3b

# สตาร์ทบอท
python -m src.bot
```
จากนั้นทักบอทใน Telegram → ส่งไฟล์ → พิมพ์ถาม

### คำสั่งในแชท
| คำสั่ง | ทำอะไร |
|--------|--------|
| ส่งไฟล์ (PDF/office/รูป) | สกัด + เก็บเข้าคลัง |
| พิมพ์คำถาม | ตอบจากเอกสารที่มี (RAG) |
| `/list` | ดูเอกสารที่เก็บไว้ |
| `/doc <id>` | สรุปเอกสารนั้นเป็นหัวข้อ + เข้าโหมดถามเจาะรายไฟล์ |
| `/all` | กลับไปถามจากทั้งคลัง |
| `/summarize <คำค้น>` | สรุปเอกสารที่เกี่ยวข้อง |

## ทดสอบ extractor เดี่ยวๆ (ไม่ต้องใช้ Telegram/Ollama)
```bash
python -m src.router path/to/file.pdf     # แยกชนิด + พิมพ์ markdown ที่สกัดได้
```

## หมายเหตุ
- **หน่วยความจำ:** ตั้งค่าเริ่มต้นเหมาะกับเครื่อง RAM ≤8GB (LLM = `qwen2.5:3b`) — ปรับ `OLLAMA_MODEL` ใน `.env` ได้ถ้าเครื่องแรงขึ้น
- **PaddleOCR:** ใช้เฉพาะไฟล์รูปเดี่ยว (PDF สแกนให้ opendataloader จัดการ) ถ้าลง paddle ไม่ได้ ส่วน PDF/office ยังทำงานปกติ
- ข้อมูล/ไฟล์ทั้งหมดเก็บใน `data/` (git-ignored)
- ภาพรวม flow + logic: [docs/OVERVIEW.md](docs/OVERVIEW.md)

## License
เผยแพร่ภายใต้ **GNU AGPL-3.0** — ดู [LICENSE](./LICENSE)

Copyright (C) 2026 the Sarabun authors

หมายเหตุความเข้ากันได้ของ dependencies:
- `python-telegram-bot` (LGPL-3.0) — ใช้เป็น library, เข้ากันได้กับ AGPL-3.0
- `opendataloader-pdf` · `PaddleOCR` · `ChromaDB` · `sentence-transformers` (Apache-2.0), `markitdown` (MIT) — เข้ากันได้
- ⚠️ โมเดล **qwen2.5:3b** มี license ของตัวโมเดลแยก (Qwen) — ไม่กระทบ AGPL ของโค้ด แต่หากใช้เชิงพาณิชย์ควรตรวจเงื่อนไข Qwen หรือสลับเป็น **Qwen2.5-7B (Apache-2.0)**
