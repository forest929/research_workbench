"""Hybrid vector + keyword search using Reciprocal Rank Fusion (RRF).

Vector leg: numpy cosine similarity over stored embeddings (no pgvector needed).
Keyword leg: SQLite FTS5.
"""

import re

import numpy as np
from uuid import UUID

from portfolio_architect.embedding import codec

from portfolio_architect.embedding.client import embed_text
from portfolio_architect.config import get_settings
from portfolio_architect.db.pool import _ConnProxy, is_postgres

_settings = get_settings()

RRF_K = 60


async def _search_chunks_pg(conn, query: str, pid: str, k: int) -> list[dict]:
    """Postgres hybrid search. Both legs run in the database so we never ship the
    embedding blobs over the wire:
      - vector leg: pgvector cosine distance (`<=>`), exact scan, ORDER BY … LIMIT.
      - keyword leg: the generated `content_tsv` GIN index via `plainto_tsquery`.
    Ranks are fused with RRF, identical to the SQLite path.
    """
    vector_ranked: dict[str, tuple[int, dict]] = {}
    try:
        q_emb = codec.encode(await embed_text(query))  # ndarray on PG (pgvector param)
        rows = await conn.fetch(
            "SELECT id, document_id, content FROM chunks "
            "WHERE project_id = ? AND embedding IS NOT NULL "
            "ORDER BY embedding <=> ? LIMIT ?",
            pid, q_emb, k * 2,
        )
        for i, row in enumerate(rows):
            vector_ranked[row["id"]] = (i + 1, row)
    except Exception:
        pass

    keyword_ranked: dict[str, int] = {}
    chunk_data: dict[str, dict] = {cid: row for cid, (_, row) in vector_ranked.items()}
    try:
        rows = await conn.fetch(
            "SELECT id, document_id, content FROM chunks "
            "WHERE project_id = ? AND content_tsv @@ plainto_tsquery('english', ?) "
            "ORDER BY ts_rank(content_tsv, plainto_tsquery('english', ?)) DESC LIMIT ?",
            pid, query, query, k * 2,
        )
        for i, row in enumerate(rows):
            keyword_ranked[row["id"]] = i + 1
            chunk_data.setdefault(row["id"], row)
    except Exception:
        pass

    all_ids = set(vector_ranked) | set(keyword_ranked)
    if not all_ids:
        return []

    fused: list[tuple[float, dict]] = []
    for cid in all_ids:
        v_rank = vector_ranked.get(cid, (None,))[0]
        k_rank = keyword_ranked.get(cid)
        score = 0.0
        if v_rank is not None:
            score += 1.0 / (RRF_K + v_rank)
        if k_rank is not None:
            score += 1.0 / (RRF_K + k_rank)
        fused.append((score, chunk_data[cid]))

    fused.sort(key=lambda x: x[0], reverse=True)
    top = fused[:k]

    doc_ids = list({row["document_id"] for _, row in top})
    doc_source: dict[str, str] = {}
    if doc_ids:
        placeholders = ",".join("?" * len(doc_ids))
        doc_rows = await conn.fetch(
            f"SELECT id, source_id FROM documents WHERE id IN ({placeholders})",
            *doc_ids,
        )
        doc_source = {r["id"]: r["source_id"] for r in doc_rows}

    return [
        {
            "chunk_id": row["id"],
            "document_id": row["document_id"],
            "source_id": doc_source.get(row["document_id"], "unknown"),
            "content": row["content"],
            "score": score,
        }
        for score, row in top
    ]


def _fts_query(query: str) -> str:
    """Escape arbitrary text for FTS5 MATCH — quote individual terms."""
    terms = re.sub(r'["\'\(\)\^\*\+\-:,\.\!]', ' ', query).split()
    if not terms:
        return '""'
    return " ".join(f'"{t}"' for t in terms)


async def search_chunks(
    conn: _ConnProxy,
    query: str,
    project_id: UUID,
    top_k: int | None = None,
) -> list[dict]:
    k = top_k or _settings.retrieval_top_k
    pid = str(project_id)

    if is_postgres():
        return await _search_chunks_pg(conn, query, pid, k)

    # ── Vector leg ──────────────────────────────────────────────────────────
    vector_ranked: dict[str, tuple[int, dict]] = {}
    try:
        query_embedding = await embed_text(query)
        q_vec = np.array(query_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q_vec))
        if q_norm > 0:
            q_unit = q_vec / q_norm
            rows = await conn.fetch(
                "SELECT id, document_id, content, embedding FROM chunks "
                "WHERE project_id = ? AND embedding IS NOT NULL",
                pid,
            )
            scored: list[tuple[float, dict]] = []
            for row in rows:
                vec = codec.decode(row["embedding"])
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    sim = float(np.dot(q_unit, vec / norm))
                    scored.append((sim, row))
            scored.sort(key=lambda x: x[0], reverse=True)
            for i, (_, row) in enumerate(scored[: k * 2]):
                vector_ranked[row["id"]] = (i + 1, row)
    except Exception:
        pass

    # ── Keyword (FTS5) leg ──────────────────────────────────────────────────
    keyword_ranked: dict[str, int] = {}
    try:
        fts_rows = await conn.fetch(
            "SELECT chunk_id FROM chunks_fts WHERE content MATCH ? AND project_id = ? "
            "ORDER BY rank LIMIT ?",
            _fts_query(query), pid, k * 2,
        )
        for i, row in enumerate(fts_rows):
            keyword_ranked[row["chunk_id"]] = i + 1
    except Exception:
        pass

    # ── RRF fusion ──────────────────────────────────────────────────────────
    all_ids = set(vector_ranked) | set(keyword_ranked)
    if not all_ids:
        return []

    # Collect chunk data; fetch any keyword-only chunks from the DB
    chunk_data: dict[str, dict] = {cid: row for cid, (_, row) in vector_ranked.items()}
    missing = [cid for cid in keyword_ranked if cid not in chunk_data]
    if missing:
        placeholders = ",".join("?" * len(missing))
        extra = await conn.fetch(
            f"SELECT id, document_id, content FROM chunks WHERE id IN ({placeholders})",
            *missing,
        )
        for row in extra:
            chunk_data[row["id"]] = row

    fused: list[tuple[float, dict]] = []
    for cid in all_ids:
        v_rank = vector_ranked.get(cid, (None,))[0]
        k_rank = keyword_ranked.get(cid)
        score = 0.0
        if v_rank is not None:
            score += 1.0 / (RRF_K + v_rank)
        if k_rank is not None:
            score += 1.0 / (RRF_K + k_rank)
        fused.append((score, chunk_data[cid]))

    fused.sort(key=lambda x: x[0], reverse=True)
    top = fused[:k]

    # Resolve source_id via documents table
    doc_ids = list({row["document_id"] for _, row in top})
    doc_source: dict[str, str] = {}
    if doc_ids:
        placeholders = ",".join("?" * len(doc_ids))
        doc_rows = await conn.fetch(
            f"SELECT id, source_id FROM documents WHERE id IN ({placeholders})",
            *doc_ids,
        )
        doc_source = {r["id"]: r["source_id"] for r in doc_rows}

    return [
        {
            "chunk_id": row["id"],
            "document_id": row["document_id"],
            "source_id": doc_source.get(row["document_id"], "unknown"),
            "content": row["content"],
            "score": score,
        }
        for score, row in top
    ]


def chunks_to_xml(chunks: list[dict]) -> str:
    parts = [
        f'  <chunk id="{i + 1}" source_id="{c["source_id"]}">\n'
        f'    {c["content"]}\n'
        f'  </chunk>'
        for i, c in enumerate(chunks)
    ]
    return "<chunks>\n" + "\n".join(parts) + "\n</chunks>"
