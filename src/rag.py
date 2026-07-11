"""RAG — retrieve จาก vector store + สรุป/ตอบด้วย Ollama (local qwen2.5:3b)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import config, vectordb
from .textutil import clean_text

SYSTEM = (
    "คุณเป็นผู้ช่วยสรุปและตอบคำถามจากเอกสารภายในเท่านั้น "
    "ตอบเป็นภาษาไทยกระชับ ตรงประเด็น อ้างอิงเฉพาะข้อมูลใน CONTEXT ที่ให้ "
    "ถ้าข้อมูลไม่พอให้บอกตรงๆ ว่าไม่พบข้อมูลในเอกสาร อย่าเดา"
)

# ระบบสำหรับ 'สรุปทั้งไฟล์' — ไม่ใช้ข้อความ 'ไม่พบข้อมูล' เพราะแม้เนื้อหาน้อยก็ต้องบรรยายเอกสาร
SUMMARY_SYSTEM = (
    "คุณเป็นผู้ช่วยสรุปเอกสารภาษาไทย สรุปเฉพาะจากเนื้อหาที่ให้ ไม่แต่งข้อมูลเพิ่ม "
    "ถ้าเนื้อหาน้อยหรือเป็นแบบฟอร์ม/เอกสารเปล่า ให้ระบุ 'ประเภทเอกสาร' และ 'หัวข้อ/ช่องที่มี' "
    "แทนการบอกว่าไม่พบข้อมูล"
)

# สรุปทั้งเอกสารเป็นหัวข้อ (bullet) — จำกัดความยาว input กัน context เกิน
DOC_TEXT_CAP = 12000

DESCRIBE_SYSTEM = (
    "คุณเป็นผู้ช่วยอธิบายเอกสารภาษาไทย ตอบสั้นกระชับ อ้างจากเนื้อหาที่ให้เท่านั้น ไม่แต่งเพิ่ม"
)


def _build_prompt(question: str, hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        src = h["meta"].get("source_filename", "?")
        blocks.append(f"[{i}] (จาก: {src})\n{h['text']}")
    context = "\n\n".join(blocks)
    return (
        f"{SYSTEM}\n\n"
        f"=== CONTEXT ===\n{context}\n\n"
        f"=== คำถาม ===\n{question}\n\n"
        f"=== คำตอบ ==="
    )


def _ollama_generate(prompt: str, model: Optional[str] = None,
                     options: Optional[dict] = None) -> str:
    import requests

    opts = {
        "temperature": config.LLM_TEMPERATURE,
        "num_ctx": config.LLM_NUM_CTX,
        "num_predict": config.LLM_NUM_PREDICT,
    }
    if options:
        opts.update(options)
    r = requests.post(
        f"{config.OLLAMA_HOST}/api/generate",
        json={
            "model": model or config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": opts,
        },
        timeout=config.LLM_TIMEOUT,
    )
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


def _sources(hits: list[dict]) -> list[str]:
    seen: list[str] = []
    for h in hits:
        s = h["meta"].get("source_filename", "?")
        if s not in seen:
            seen.append(s)
    return seen


def answer(question: str, k: Optional[int] = None, doc_id: Optional[int] = None) -> dict:
    """ตอบคำถาม. ถ้าระบุ doc_id จะตอบจากเฉพาะเอกสารนั้น (โหมดคุยรายไฟล์)."""
    hits = vectordb.search(question, k=k, doc_id=doc_id)
    if not hits:
        scope = "ในเอกสารนี้" if doc_id is not None else "ในระบบ"
        return {"answer": f"ไม่พบข้อมูลที่เกี่ยวข้องกับคำถามนี้{scope}", "sources": []}
    text = _ollama_generate(_build_prompt(question, hits), model=config.ANSWER_MODEL)
    return {"answer": text, "sources": _sources(hits)}


def describe_document(text: str, filename: str = "") -> str:
    """overview ระดับเอกสาร: เป็นเอกสารประเภทใด + เนื้อหาโดยรวมเกี่ยวกับอะไร (2-4 ประโยค)."""
    text = clean_text(text)
    if not text.strip():
        return ""
    prompt = (
        f"{DESCRIBE_SYSTEM}\n\n"
        "อธิบาย 2-4 ประโยคว่า (1) เอกสารนี้เป็นประเภทใด (เช่น ระเบียบ/รายงาน/แบบฟอร์ม/ประกาศ) "
        "(2) เนื้อหาโดยรวมเกี่ยวกับอะไร\n\n"
        f"=== เอกสาร: {filename} ===\n{text[:DOC_TEXT_CAP]}\n\n=== คำอธิบายโดยรวม ==="
    )
    return _ollama_generate(prompt, model=config.SUMMARY_MODEL)


def summarize_document(doc_id: int, extracted_path: Optional[str] = None,
                       filename: str = "") -> dict:
    """สรุปทั้งเอกสารเป็นหัวข้อ + bullet ย่อย (อ่านจากไฟล์ที่สกัดไว้ ถ้าไม่มีค่อยประกอบจาก chunks)."""
    text = ""
    if extracted_path and Path(extracted_path).exists():
        text = Path(extracted_path).read_text(encoding="utf-8")
    if not text.strip():
        text = "\n\n".join(c["text"] for c in vectordb.get_document_chunks(doc_id))

    text = clean_text(text)  # ตัด base64/PUA noise ก่อนสรุป
    if not text.strip():
        return {"answer": "เอกสารนี้ไม่มีเนื้อหาให้สรุป", "sources": [filename] if filename else []}

    prompt = (
        f"{SUMMARY_SYSTEM}\n\n"
        "สรุปเอกสารต่อไปนี้เป็น **หัวข้อหลัก** พร้อม bullet ย่อย 2-4 ข้อใต้แต่ละหัวข้อ "
        "ครอบคลุมสาระสำคัญทั้งหมด ใช้รูปแบบ:\n"
        "📌 <หัวข้อ>\n  • <ประเด็น>\n\n"
        f"=== เอกสาร: {filename} ===\n{text[:DOC_TEXT_CAP]}\n\n=== สรุปเป็นหัวข้อ ==="
    )
    return {"answer": _ollama_generate(prompt, model=config.SUMMARY_MODEL),
            "sources": [filename] if filename else []}


def summarize(query: str, k: int = 8) -> dict:
    """สรุปเอกสารที่ตรงกับ query (ดึง chunk เยอะกว่า answer)."""
    hits = vectordb.search(query, k=k)
    if not hits:
        return {"answer": f"ไม่พบเอกสารที่เกี่ยวกับ: {query}", "sources": []}
    prompt = _build_prompt(f"สรุปสาระสำคัญเกี่ยวกับ: {query}", hits)
    text = _ollama_generate(prompt)
    return {"answer": text, "sources": _sources(hits)}
