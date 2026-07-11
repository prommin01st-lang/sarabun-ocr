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
MAP_WINDOW = 6000        # ขนาดต่อ "ส่วน" ตอน map-reduce (เอกสารยาว)
MAP_MAX_WINDOWS = 20     # กันเอกสารยักษ์เรียก LLM เยอะเกินไป (สรุปครอบ N ส่วนแรก)

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


def answer(question: str, k: Optional[int] = None, doc_id: Optional[int] = None,
           doc_ids: Optional[list] = None) -> dict:
    """ตอบคำถาม. scope ได้ด้วย doc_id (ไฟล์เดียว) หรือ doc_ids (กลุ่ม เช่นทั้งหมวด/โฟลเดอร์)."""
    hits = vectordb.search(question, k=k, doc_id=doc_id, doc_ids=doc_ids)
    if not hits:
        scoped = doc_id is not None or doc_ids is not None
        where = "ในขอบเขตที่เลือก" if scoped else "ในระบบ"
        return {"answer": f"ไม่พบข้อมูลที่เกี่ยวข้องกับคำถามนี้{where}", "sources": []}
    text = _ollama_generate(_build_prompt(question, hits), model=config.ANSWER_MODEL)
    return {"answer": text, "sources": _sources(hits)}


# ดึง context มาช่วยร่างเฉพาะที่ "ใกล้จริง" (distance ต่ำ) เพื่อไม่ให้เอกสารไม่เกี่ยวมาหลอกโมเดล
DRAFT_CTX_MAX_DIST = 0.45


def draft_document(instruction: str, k: int = 4) -> str:
    """ให้ LLM ร่างเอกสารใหม่ตามคำสั่ง.

    - ดึงคลังมาอ้างอิง **เฉพาะเมื่อเกี่ยวข้องจริง** (distance < DRAFT_CTX_MAX_DIST)
      → ฟอร์มทั่วไปที่ไม่เกี่ยวกับคลังจะไม่ถูกเนื้อหาอื่นมาหลอก
    - decoding กัน repetition-loop (repeat_penalty) + สั่งให้ตอบเป็นตัวเอกสารล้วน
    """
    hits = [h for h in vectordb.search(instruction, k=k)
            if h.get("distance", 1.0) < DRAFT_CTX_MAX_DIST]
    ctx_block = ""
    if hits:
        context = "\n\n".join(
            f"[{i}] (จาก {h['meta'].get('source_filename', '?')})\n{h['text']}"
            for i, h in enumerate(hits, 1)
        )
        ctx_block = f"=== ข้อมูลอ้างอิงจากคลัง (ใช้เฉพาะที่เกี่ยวข้อง) ===\n{context}\n\n"

    prompt = (
        "คุณเป็นผู้ช่วยร่างเอกสารราชการภาษาไทย ร่างเอกสารตามคำสั่งให้เป็นทางการ กระชับ ครบถ้วน จัดรูปแบบ markdown\n"
        "กติกาเข้มงวด: ตอบกลับเป็น **ตัวเอกสารเท่านั้น** ห้ามพูดถึงตัวเอง ห้ามมีคำอธิบายนอกเอกสาร "
        "ห้ามใช้ภาษาอังกฤษ เขียนแต่ละส่วนครั้งเดียว ห้ามวนซ้ำหัวข้อ จบเมื่อเนื้อหาครบ\n\n"
        f"{ctx_block}"
        f"=== คำสั่ง ===\n{instruction}\n\n=== เอกสาร ==="
    )
    return _ollama_generate(
        prompt, model=config.SUMMARY_MODEL,
        options={
            "num_predict": 1000, "temperature": 0.3, "top_p": 0.9,
            "repeat_penalty": 1.2, "repeat_last_n": 128,
        },
    )


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


# คำใบ้ต่อหมวด (สำหรับ taxonomy default; หมวดที่ผู้ใช้เพิ่มเองจะไม่มีใบ้ แต่ยังใช้ได้)
CATEGORY_HINTS = {
    "ระเบียบ/กฎหมาย": "ระเบียบ ข้อบังคับ กฎหมาย พ.ร.บ. ประกาศใช้บังคับ",
    "หนังสือราชการ": "บันทึกข้อความ หนังสือติดต่อราชการ มี เรียน/เรื่อง/ส่วนราชการ",
    "รายงาน": "รายงานผล สรุปผล การประชุม ความคืบหน้า สถิติ",
    "แบบฟอร์ม": "แบบฟอร์ม/แบบกรอก มีช่องหรือหัวข้อให้กรอกข้อมูล",
    "ประกาศ": "ประกาศ รับสมัครงาน โฆษณา ประชาสัมพันธ์ เชิญชวน",
    "สัญญา": "สัญญา ข้อตกลง บันทึกความเข้าใจ MOU คู่สัญญา",
    "อื่นๆ": "ไม่เข้าหมวดใดข้างต้นชัดเจน",
}


def classify_document(text: str, filename: str = "", overview: str = "") -> str:
    """จัดหมวดเอกสารเป็น 1 หมวดจาก config.CATEGORIES.

    ใช้ overview (ที่ระบุประเภทเอกสารอยู่แล้ว) เป็นสัญญาณเสริม + hint ต่อหมวด → แม่นขึ้น.
    validate เสมอ; ถ้าโมเดลตอบนอกลิสต์ → fallback หมวดสุดท้าย.
    """
    cats = config.CATEGORIES
    if not cats:
        return ""
    signal = (overview + "\n" + clean_text(text)).strip()
    if not signal:
        return cats[-1]
    listing = "\n".join(
        f"- {c}" + (f" ({CATEGORY_HINTS[c]})" if c in CATEGORY_HINTS else "")
        for c in cats
    )
    prompt = (
        "จัดหมวดหมู่เอกสารต่อไปนี้ให้ตรงที่สุด ตอบเป็น**ชื่อหมวดเดียว**จากรายการนี้เท่านั้น "
        "(คัดลอกชื่อหมวดมาตรงๆ ห้ามอธิบาย ห้ามสร้างหมวดใหม่):\n"
        f"{listing}\n\n"
        f"=== เอกสาร: {filename} ===\n{signal[:4000]}\n\n=== หมวดที่ตรงที่สุด ==="
    )
    out = _ollama_generate(
        prompt, model=config.SUMMARY_MODEL,
        options={"num_predict": 24, "temperature": 0.0},
    ).strip()
    matches = [c for c in cats if c in out or out in c]
    if matches:
        return max(matches, key=len)  # เลือกชื่อที่ตรงยาวสุด กันหมวดสั้นชนะโดยบังเอิญ
    return cats[-1]


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

    src = [filename] if filename else []
    # เอกสารสั้น → สรุปทีเดียว (เร็ว)
    if len(text) <= DOC_TEXT_CAP:
        return {"answer": _ollama_generate(_reduce_prompt(text, filename),
                                           model=config.SUMMARY_MODEL), "sources": src}

    # เอกสารยาว → map-reduce: สรุปทีละส่วน แล้วรวมเป็นสรุปเดียว → ครอบทุกหน้า
    windows = vectordb.chunk_text(text, size=MAP_WINDOW, overlap=200)
    truncated = len(windows) > MAP_MAX_WINDOWS
    windows = windows[:MAP_MAX_WINDOWS]
    partials = []
    for i, w in enumerate(windows, 1):
        mp = (
            f"{SUMMARY_SYSTEM}\n\n"
            f"สรุปเนื้อหาส่วนที่ {i}/{len(windows)} ของเอกสารนี้เป็น bullet สั้นๆ "
            "เก็บสาระ/ตัวเลข/ชื่อ/ข้อกำหนดสำคัญไว้:\n"
            f"=== ส่วนที่ {i} ===\n{w}\n\n=== สรุปส่วนนี้ ==="
        )
        partials.append(_ollama_generate(mp, model=config.SUMMARY_MODEL))

    combined = "\n\n".join(partials)
    final = _ollama_generate(
        f"{SUMMARY_SYSTEM}\n\n"
        "รวม 'สรุปย่อยของแต่ละส่วน' ต่อไปนี้ให้เป็นสรุปภาพรวมของทั้งเอกสาร "
        "จัดเป็น **หัวข้อหลัก** + bullet ย่อย ไม่ซ้ำ ครอบคลุมทุกส่วน ใช้รูปแบบ 📌 หัวข้อ / • ประเด็น:\n"
        f"=== สรุปย่อยแต่ละส่วน ===\n{combined[:DOC_TEXT_CAP]}\n\n=== สรุปภาพรวม ===",
        model=config.SUMMARY_MODEL,
    )
    if truncated:
        final += f"\n\n(⚠️ เอกสารยาวมาก — สรุปครอบ {MAP_MAX_WINDOWS} ส่วนแรก)"
    return {"answer": final, "sources": src}


def _reduce_prompt(text: str, filename: str) -> str:
    return (
        f"{SUMMARY_SYSTEM}\n\n"
        "สรุปเอกสารต่อไปนี้เป็น **หัวข้อหลัก** พร้อม bullet ย่อย 2-4 ข้อใต้แต่ละหัวข้อ "
        "ครอบคลุมสาระสำคัญทั้งหมด ใช้รูปแบบ:\n"
        "📌 <หัวข้อ>\n  • <ประเด็น>\n\n"
        f"=== เอกสาร: {filename} ===\n{text[:DOC_TEXT_CAP]}\n\n=== สรุปเป็นหัวข้อ ==="
    )


def summarize(query: str, k: int = 8) -> dict:
    """สรุปเอกสารที่ตรงกับ query (ดึง chunk เยอะกว่า answer)."""
    hits = vectordb.search(query, k=k)
    if not hits:
        return {"answer": f"ไม่พบเอกสารที่เกี่ยวกับ: {query}", "sources": []}
    prompt = _build_prompt(f"สรุปสาระสำคัญเกี่ยวกับ: {query}", hits)
    text = _ollama_generate(prompt)
    return {"answer": text, "sources": _sources(hits)}
