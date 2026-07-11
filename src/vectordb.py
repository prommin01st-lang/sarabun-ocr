"""Vector store (ChromaDB) + embedding (multilingual MiniLM) — หัวใจ Single Source of Truth.

model/collection ถูก lazy-load ครั้งแรกที่ใช้ (เลี่ยงโหลด ML ตอน import).
"""
from __future__ import annotations

from typing import Optional

from . import config
from .textutil import clean_text

_client = None
_collection = None
_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(config.EMBEDDING_MODEL)
    return _embedder


def _get_collection():
    global _client, _collection
    if _collection is None:
        import chromadb

        config.ensure_dirs()
        _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        _collection = _client.get_or_create_collection(
            config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    return _collection


def embed(texts: list[str]) -> list[list[float]]:
    return _get_embedder().encode(texts, normalize_embeddings=True).tolist()


def chunk_text(text: str, size: Optional[int] = None, overlap: Optional[int] = None) -> list[str]:
    """ตัด chunk ตามจำนวนตัวอักษร พยายาม break ที่ขึ้นบรรทัดใหม่ (เหมาะกับไทยที่ไม่มีเว้นวรรค)."""
    size = size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            nl = text.rfind("\n", start + size // 2, end)
            if nl != -1:
                end = nl
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def index_document(doc_id: int, filename: str, text: str) -> int:
    """chunk + embed + upsert. คืนจำนวน chunks. payload ผูก doc_id กลับ SQLite เสมอ."""
    chunks = chunk_text(clean_text(text))
    if not chunks:
        return 0
    embeddings = embed(chunks)
    ids = [f"{doc_id}:{i}" for i in range(len(chunks))]
    metadatas = [
        {"doc_id": doc_id, "chunk_idx": i, "source_filename": filename}
        for i in range(len(chunks))
    ]
    _get_collection().upsert(
        ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas
    )
    return len(chunks)


def search(query: str, k: Optional[int] = None, doc_id: Optional[int] = None,
           doc_ids: Optional[list] = None) -> list[dict]:
    """ค้น semantic. scope ได้ด้วย doc_id (ไฟล์เดียว) หรือ doc_ids (กลุ่ม เช่นทั้งหมวด/โฟลเดอร์)."""
    k = k or config.TOP_K
    where = None
    if doc_id is not None:
        where = {"doc_id": doc_id}
    elif doc_ids is not None:
        if not doc_ids:            # กลุ่มว่าง → ไม่มีอะไรให้ค้น
            return []
        where = {"doc_id": {"$in": list(doc_ids)}}
    res = _get_collection().query(query_embeddings=embed([query]), n_results=k, where=where)
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    return [
        {"text": d, "meta": m, "distance": dist}
        for d, m, dist in zip(docs, metas, dists)
    ]


def index_summary(doc_id: int, filename: str, summary: str) -> None:
    """เก็บ document-level overview เป็น vector 1 ตัว (chunk_idx=-1, kind='summary') → ค้นเจอได้."""
    summary = (summary or "").strip()
    if not summary:
        return
    _get_collection().upsert(
        ids=[f"{doc_id}:summary"],
        embeddings=embed([summary]),
        documents=[summary],
        metadatas=[{
            "doc_id": doc_id, "chunk_idx": -1,
            "source_filename": filename, "kind": "summary",
        }],
    )


def get_document_chunks(doc_id: int) -> list[dict]:
    """คืน chunks เนื้อหาของเอกสาร เรียงตาม chunk_idx (ข้าม vector สรุป kind='summary')."""
    res = _get_collection().get(where={"doc_id": doc_id})
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    pairs = [(d, m) for d, m in zip(docs, metas) if m.get("kind") != "summary"]
    pairs.sort(key=lambda x: x[1].get("chunk_idx", 0))
    return [{"text": d, "meta": m} for d, m in pairs]


def delete_document(doc_id: int) -> None:
    _get_collection().delete(where={"doc_id": doc_id})
