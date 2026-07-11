"""Central config — โหลดจาก .env (มี default ที่รันได้ทันที)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ───────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR") or (BASE_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"
EXTRACTED_DIR = DATA_DIR / "extracted"
CHROMA_DIR = DATA_DIR / "chroma"
METADATA_DB = DATA_DIR / "metadata.db"

# ── Database (metadata store) ───────────────────────────────
# default = SQLite (dev, zero-setup)
# ใช้ Postgres: DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/ocr_file_chat
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{METADATA_DB}"
DB_BACKEND = "postgresql" if DATABASE_URL.startswith("postgres") else "sqlite"

# ── Telegram ────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# จำกัดผู้ใช้ที่ใช้บอทได้ (เว้นว่าง = ทุกคน)
_allowed = os.getenv("ALLOWED_USER_IDS", "").replace(",", " ").split()
ALLOWED_USER_IDS: set[int] = {int(x) for x in _allowed if x.strip().isdigit()}

# admin: แก้/ลบเอกสารของใครก็ได้ (เจ้าของไฟล์แก้ของตัวเองได้อยู่แล้ว)
_admins = os.getenv("ADMIN_USER_IDS", "").replace(",", " ").split()
ADMIN_USER_IDS: set[int] = {int(x) for x in _admins if x.strip().isdigit()}

# ── Embedding ───────────────────────────────────────────────
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

# ── Ollama / LLM ────────────────────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")  # default ทุก task

# override โมเดลราย task (เว้นว่าง = ใช้ OLLAMA_MODEL) — เช่นใช้ตัวใหญ่กว่าเฉพาะตอนสรุป
ANSWER_MODEL = os.getenv("ANSWER_MODEL") or OLLAMA_MODEL
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL") or OLLAMA_MODEL

# generation options (ส่งเข้า Ollama options)
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))   # ต่ำ = ตรงข้อเท็จจริง เหมาะ RAG
LLM_NUM_CTX = int(os.getenv("LLM_NUM_CTX", "8192"))            # context window (กัน prompt ยาวโดนตัด)
LLM_NUM_PREDICT = int(os.getenv("LLM_NUM_PREDICT", "1024"))    # max output tokens (-1 = ไม่จำกัด)
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))             # วินาที

# ── OCR ─────────────────────────────────────────────────────
OCR_LANG = os.getenv("OCR_LANG", "th")

# ── Chunking / Retrieval ────────────────────────────────────
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
TOP_K = int(os.getenv("TOP_K", "5"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "documents")

# ── Safety / limits ─────────────────────────────────────────
MAX_FILE_MB = float(os.getenv("MAX_FILE_MB", "25"))   # R1: กันไฟล์ใหญ่/zip-bomb → OOM
SANITIZE = os.getenv("SANITIZE", "false").lower() in ("1", "true", "yes")  # R2: ปกปิด PII

# ── Auto-category (taxonomy ปรับได้) ────────────────────────
CATEGORIES = [
    c.strip() for c in os.getenv(
        "CATEGORIES",
        "ระเบียบ/กฎหมาย,หนังสือราชการ,รายงาน,แบบฟอร์ม,ประกาศ,สัญญา,อื่นๆ",
    ).split(",") if c.strip()
]


def ensure_dirs() -> None:
    """สร้างโฟลเดอร์ data ทั้งหมด (idempotent)."""
    for d in (DATA_DIR, RAW_DIR, EXTRACTED_DIR, CHROMA_DIR):
        d.mkdir(parents=True, exist_ok=True)
