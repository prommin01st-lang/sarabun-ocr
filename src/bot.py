"""Telegram bot — รับไฟล์ → ingest, และ chat → RAG. รัน: python -m src.bot

งานที่ block (extract/embed/LLM) ถูกโยนเข้า thread executor เพื่อไม่ให้ event loop ค้าง.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from functools import partial, wraps
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import config, pipeline, rag, store

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("ocr-file-chat")

WELCOME = (
    "👋 สวัสดี! ส่งไฟล์เอกสาร (PDF / Office / รูป) มาได้เลย เดี๋ยวผมสกัดเนื้อหาเก็บให้\n\n"
    "คำสั่ง:\n"
    "• ส่งไฟล์ → เก็บเข้าคลัง\n"
    "• พิมพ์คำถาม → ผมตอบจากเอกสารที่มี\n"
    "• /list → ดูคลัง (จัดเป็นโฟลเดอร์)\n"
    "• /mkfolder <ชื่อ> → สร้างโฟลเดอร์ · /mv <id> <โฟลเดอร์> → ย้ายไฟล์\n"
    "• /folder <ชื่อ> → ตั้งโฟลเดอร์ให้ไฟล์ที่จะส่งต่อไป (/folder - = ยกเลิก)\n"
    "• /doc <id> → สรุป + เข้าโหมดถามเจาะไฟล์นั้น · /all → กลับทั้งคลัง\n"
    "• /summarize <คำค้น> → สรุปเอกสารที่เกี่ยวข้อง"
)


async def _run(func, *args):
    """รันฟังก์ชัน blocking ใน executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args))


def restricted(handler):
    """กันเฉพาะ ALLOWED_USER_IDS (ถ้าตั้งไว้) ให้ใช้บอทได้."""

    @wraps(handler)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if config.ALLOWED_USER_IDS and uid not in config.ALLOWED_USER_IDS:
            log.warning("blocked user %s", uid)
            if update.message:
                await update.message.reply_text("⛔ บอทนี้จำกัดเฉพาะผู้ใช้ที่ได้รับอนุญาต")
            return
        return await handler(update, ctx)

    return wrapper


# ── commands ────────────────────────────────────────────────
@restricted
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


def _doc_line(d) -> str:
    icon = {"indexed": "✅", "failed": "❌", "processing": "⏳"}.get(d["status"], "•")
    return f"   {icon} [{d['id']}] {d['filename'][:40]} ({d['n_chunks']})"


@restricted
async def cmd_list(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows = await _run(store.list_docs, 200)
    flist = await _run(store.list_folders)
    if not rows and not flist:
        await update.message.reply_text("ยังไม่มีเอกสารในคลัง — ส่งไฟล์มาได้เลย")
        return

    by_folder: dict = {}
    for r in rows:
        by_folder.setdefault(r["folder_id"], []).append(r)

    lines = ["📚 คลังเอกสาร\n"]
    for f in flist:  # โฟลเดอร์ → ไฟล์ข้างใน
        docs = by_folder.get(f["id"], [])
        lines.append(f"📁 {f['name']} ({len(docs)})")
        lines += [_doc_line(d) for d in docs] if docs else ["   (ว่าง)"]
    root = by_folder.get(None, [])  # ไฟล์ที่ยังไม่จัดหมวด
    if root:
        lines.append(f"📂 ยังไม่จัดหมวด ({len(root)})")
        lines += [_doc_line(d) for d in root]

    lines.append("\n💡 /mkfolder <ชื่อ> · /mv <id> <โฟลเดอร์> · /doc <id>")
    await update.message.reply_text("\n".join(lines))


@restricted
async def cmd_mkfolder(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = " ".join(ctx.args).strip()
    if not name:
        await update.message.reply_text("ใช้: /mkfolder <ชื่อโฟลเดอร์>")
        return
    await _run(store.create_folder, name)
    await update.message.reply_text(f"📁 สร้างโฟลเดอร์ «{name}» แล้ว")


@restricted
async def cmd_mv(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2 or not ctx.args[0].isdigit():
        await update.message.reply_text("ใช้: /mv <id> <โฟลเดอร์>  (ใช้ - เพื่อเอาออกจากโฟลเดอร์)")
        return
    doc_id = int(ctx.args[0])
    row = await _run(store.get, doc_id)
    if not row:
        await update.message.reply_text(f"ไม่พบเอกสาร id={doc_id}")
        return
    target = " ".join(ctx.args[1:]).strip()
    if target in ("-", "/", "root"):
        await _run(store.move_document, doc_id, None)
        await update.message.reply_text(f"↩️ ย้าย [{doc_id}] ออกจากโฟลเดอร์แล้ว")
    else:
        fid = await _run(store.create_folder, target)
        await _run(store.move_document, doc_id, fid)
        await update.message.reply_text(f"📁 ย้าย [{doc_id}] → «{target}»")


@restricted
async def cmd_folder(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """ตั้งโฟลเดอร์ปลายทางของไฟล์ที่จะส่งต่อไป (ต่อผู้ใช้)."""
    if not ctx.args or ctx.args[0] in ("-", "/"):
        ctx.user_data.pop("upload_folder_id", None)
        ctx.user_data.pop("upload_folder_name", None)
        await update.message.reply_text("📂 ไฟล์ที่ส่งต่อไปจะเข้า 'ยังไม่จัดหมวด'")
        return
    name = " ".join(ctx.args).strip()
    fid = await _run(store.create_folder, name)
    ctx.user_data["upload_folder_id"] = fid
    ctx.user_data["upload_folder_name"] = name
    await update.message.reply_text(f"📁 ไฟล์ที่ส่งต่อไปจะเข้าโฟลเดอร์ «{name}»")


@restricted
async def cmd_doc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("ใช้: /doc <id>  (ดู id จาก /list)")
        return
    doc_id = int(ctx.args[0])
    row = await _run(store.get, doc_id)
    if not row:
        await update.message.reply_text(f"ไม่พบเอกสาร id={doc_id}")
        return
    # เข้าโหมดคุยกับเอกสารนี้
    ctx.user_data["doc_id"] = doc_id
    ctx.user_data["doc_name"] = row["filename"]
    await update.message.chat.send_action("typing")
    res = await _run(rag.summarize_document, doc_id, row["extracted_path"], row["filename"])
    overview = row["summary"] if "summary" in row.keys() else None
    parts = [f"📄 {row['filename']}"]
    if overview:
        parts.append(f"\n📝 ภาพรวม: {overview}")
    parts.append("\n" + res["answer"])
    parts.append("\n💬 ถามรายละเอียด *ในเอกสารนี้* ได้เลย · /all เพื่อกลับไปทั้งคลัง")
    await update.message.reply_text("\n".join(parts))


@restricted
async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.user_data.pop("doc_id", None)
    name = ctx.user_data.pop("doc_name", None)
    msg = f"↩️ ออกจากโหมดเอกสาร «{name}» — ถามจากทั้งคลังได้แล้ว" if name else "ถามจากทั้งคลังได้เลย"
    await update.message.reply_text(msg)


@restricted
async def cmd_summarize(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(ctx.args) if ctx.args else ""
    if not query:
        await update.message.reply_text("ใช้: /summarize <คำค้น/หัวข้อ>")
        return
    await update.message.chat.send_action("typing")
    res = await _run(rag.summarize, query)
    await update.message.reply_text(_format_answer(res))


# ── file ingest ─────────────────────────────────────────────
async def _ingest_and_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                            local_path: str, filename: str) -> None:
    folder_id = ctx.user_data.get("upload_folder_id")
    folder_name = ctx.user_data.get("upload_folder_name")
    await update.message.reply_text(f"📥 กำลังประมวลผล: {filename} ...")
    res = await _run(
        pipeline.ingest_file,
        local_path,
        filename,
        str(update.effective_chat.id),
        update.effective_user.username or str(update.effective_user.id),
        folder_id,
    )
    status = res["status"]
    if status == "indexed":
        msg = f"✅ เก็บแล้ว: {filename}\nชนิด: {res['doc_type']} · {res['n_chunks']} chunks"
        if folder_name:
            msg += f" · 📁 {folder_name}"
        if res.get("summary"):
            msg += f"\n\n📝 {res['summary']}"
    elif status == "duplicate":
        msg = f"♻️ มีไฟล์นี้อยู่แล้ว (id={res['doc_id']}, {res['n_chunks']} chunks) — ไม่ประมวลผลซ้ำ"
    elif status == "too_large":
        msg = f"⚠️ ไฟล์ใหญ่เกิน {res['max_mb']}MB (ไฟล์นี้ {res['size_mb']}MB) — ไม่รับ"
    elif status == "unsupported":
        msg = f"⚠️ ยังไม่รองรับไฟล์ชนิดนี้: {filename}"
    else:
        msg = f"❌ ประมวลผลไม่สำเร็จ: {filename}\n{res.get('error', '')[:300]}"
    await update.message.reply_text(msg)


@restricted
async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    tg_file = await ctx.bot.get_file(doc.file_id)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / (doc.file_name or f"{doc.file_unique_id}")
        await tg_file.download_to_drive(str(local))
        await _ingest_and_reply(update, ctx, str(local), doc.file_name or local.name)


@restricted
async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]  # ขนาดใหญ่สุด
    tg_file = await ctx.bot.get_file(photo.file_id)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / f"{photo.file_unique_id}.jpg"
        await tg_file.download_to_drive(str(local))
        await _ingest_and_reply(update, ctx, str(local), local.name)


# ── chat Q&A ────────────────────────────────────────────────
@restricted
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    question = (update.message.text or "").strip()
    if not question:
        return
    doc_id = ctx.user_data.get("doc_id")  # None = ถามทั้งคลัง
    await update.message.chat.send_action("typing")
    try:
        res = await _run(rag.answer, question, None, doc_id)
        prefix = ""
        if doc_id is not None:
            prefix = f"🔎 (ในเอกสาร «{ctx.user_data.get('doc_name', doc_id)}»)\n"
        await update.message.reply_text(prefix + _format_answer(res))
    except Exception as e:  # noqa: BLE001
        log.exception("answer failed")
        await update.message.reply_text(f"❌ ตอบไม่ได้ตอนนี้: {e}")


def _format_answer(res: dict) -> str:
    text = res.get("answer", "")
    sources = res.get("sources") or []
    if sources:
        text += "\n\n📎 อ้างอิง: " + ", ".join(sources)
    return text


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("ตั้งค่า TELEGRAM_BOT_TOKEN ใน .env ก่อน (ขอจาก @BotFather)")
    store.init_db()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("doc", cmd_doc))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("mkfolder", cmd_mkfolder))
    app.add_handler(CommandHandler("mv", cmd_mv))
    app.add_handler(CommandHandler("folder", cmd_folder))
    app.add_handler(CommandHandler("summarize", cmd_summarize))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("bot started (model=%s, embed=%s)", config.OLLAMA_MODEL, config.EMBEDDING_MODEL)
    app.run_polling()


if __name__ == "__main__":
    main()
