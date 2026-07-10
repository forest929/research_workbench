"""Decision memory: store and retrieve human-validated screening decisions as few-shot examples."""

import json
import math
from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


async def get_doc_embedding(conn: _ConnProxy, document_id: UUID) -> list[float] | None:
    """Compute mean of chunk embeddings for a document (document-level representation)."""
    rows = await conn.fetch(
        "SELECT embedding FROM chunks WHERE document_id = ? AND embedding IS NOT NULL",
        str(document_id),
    )
    if not rows:
        return None
    vecs = [json.loads(r["embedding"]) for r in rows]
    dim = len(vecs[0])
    mean = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
    return mean


async def store_decision(
    conn: _ConnProxy,
    project_id: UUID,
    document_id: UUID,
    human_label: str,
    human_reason: str | None,
    reason_code: str | None,
    is_protocol_specific: bool,
    reviewer: str | None,
    llm_label: str | None,
    llm_confidence: float | None,
    llm_reasoning: str | None,
) -> dict:
    """Persist a human decision and cache the document embedding for future similarity search."""
    embedding = await get_doc_embedding(conn, document_id)
    emb_json = json.dumps(embedding) if embedding else None

    did = str(uuid4())
    row = await conn.fetchrow(
        """
        INSERT INTO decisions
            (id, project_id, document_id, llm_label, llm_confidence, llm_reasoning,
             human_label, human_reason, reason_code, is_protocol_specific, reviewer, doc_embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        did, str(project_id), str(document_id),
        llm_label, llm_confidence, llm_reasoning,
        human_label, human_reason, reason_code,
        1 if is_protocol_specific else 0,
        reviewer, emb_json,
    )

    # Update the document row with human decision and cached embedding
    await conn.execute(
        """UPDATE documents
           SET screening_status = ?,
               llm_label = ?,
               llm_confidence = ?,
               llm_reasoning = ?,
               doc_embedding = ?
           WHERE id = ?""",
        human_label, llm_label, llm_confidence, llm_reasoning,
        emb_json, str(document_id),
    )
    return dict(row)


async def retrieve_similar_examples(
    conn: _ConnProxy,
    project_id: UUID,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """Return the top_k validated decisions most similar to query_embedding."""
    rows = await conn.fetch(
        """SELECT d.id, d.human_label, d.human_reason, d.reason_code, d.doc_embedding,
                  doc.raw_content, doc.source_id
           FROM decisions d
           JOIN documents doc ON doc.id = d.document_id
           WHERE d.project_id = ? AND d.doc_embedding IS NOT NULL""",
        str(project_id),
    )
    if not rows:
        return []

    scored = []
    for r in rows:
        emb = json.loads(r["doc_embedding"])
        sim = _cosine_sim(query_embedding, emb)
        scored.append((sim, dict(r)))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for sim, row in scored[:top_k]:
        row["similarity"] = round(sim, 4)
        row.pop("doc_embedding", None)
        # Truncate raw content for display
        row["preview"] = row.get("raw_content", "")[:400]
        row.pop("raw_content", None)
        results.append(row)
    return results


async def get_validated_count(conn: _ConnProxy, project_id: UUID) -> int:
    rows = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM decisions WHERE project_id = ?",
        str(project_id),
    )
    return rows[0]["cnt"] if rows else 0
