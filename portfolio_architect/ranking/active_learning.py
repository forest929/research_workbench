"""Active learning ranker: prioritise uncertain documents for human review.

Uses k-NN vote over validated decision embeddings (numpy only, no sklearn).
- confidence = fraction of k nearest neighbours with the majority label
- uncertainty = |confidence - 0.5|  (lower = more uncertain = review first)

Degrades gracefully:
- 0 examples  → FIFO order, confidence = 0.5 for all
- 1–4 examples → k-NN with k = n_examples
- ≥5 examples  → k-NN with k = 5
"""

import json
import math
from uuid import UUID

from portfolio_architect.db.pool import _ConnProxy

_DEFAULT_K = 5


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _knn_predict(
    query: list[float],
    labeled_embeddings: list[list[float]],
    labels: list[str],
    k: int,
) -> tuple[str, float]:
    """Return (predicted_label, confidence) using k-NN vote."""
    if not labeled_embeddings:
        return "exclude", 0.5
    k = min(k, len(labeled_embeddings))
    scored = sorted(
        zip(labeled_embeddings, labels),
        key=lambda x: _cosine_sim(query, x[0]),
        reverse=True,
    )
    neighbours = [lbl for _, lbl in scored[:k]]
    include_votes = neighbours.count("include")
    exclude_votes = neighbours.count("exclude")
    total = include_votes + exclude_votes
    if include_votes >= exclude_votes:
        return "include", include_votes / total
    return "exclude", exclude_votes / total


async def _load_labeled_examples(conn: _ConnProxy, project_id: UUID) -> tuple[list[list[float]], list[str]]:
    rows = await conn.fetch(
        "SELECT doc_embedding, human_label FROM decisions WHERE project_id = ? AND doc_embedding IS NOT NULL",
        str(project_id),
    )
    embeddings = [json.loads(r["doc_embedding"]) for r in rows]
    labels = [r["human_label"] for r in rows]
    return embeddings, labels


async def predict_document(
    conn: _ConnProxy,
    project_id: UUID,
    doc_embedding: list[float],
) -> dict:
    """Return AL prediction for a single document."""
    embeddings, labels = await _load_labeled_examples(conn, project_id)
    if not embeddings:
        return {"label": "unknown", "confidence": 0.5, "method": "no_examples"}
    k = min(_DEFAULT_K, len(embeddings))
    label, confidence = _knn_predict(doc_embedding, embeddings, labels, k)
    return {"label": label, "confidence": confidence, "method": f"knn_k{k}"}


async def rank_pending_documents(
    conn: _ConnProxy,
    project_id: UUID,
    limit: int = 50,
) -> list[dict]:
    """Return pending documents ranked by uncertainty (most uncertain first)."""
    rows = await conn.fetch(
        """SELECT id, source_id, raw_content, doc_embedding, created_at
           FROM documents
           WHERE project_id = ? AND screening_status = 'pending'
           ORDER BY created_at
           LIMIT ?""",
        str(project_id), limit * 3,  # over-fetch so we can re-rank
    )
    if not rows:
        return []

    embeddings, labels = await _load_labeled_examples(conn, project_id)
    k = min(_DEFAULT_K, len(embeddings))

    results = []
    for r in rows:
        doc_emb = json.loads(r["doc_embedding"]) if r.get("doc_embedding") else None
        if doc_emb and embeddings:
            pred_label, confidence = _knn_predict(doc_emb, embeddings, labels, k)
            uncertainty = abs(confidence - 0.5)
        else:
            pred_label, confidence, uncertainty = "unknown", 0.5, 0.0  # FIFO: treat as maximally uncertain

        results.append({
            "id": r["id"],
            "source_id": r["source_id"],
            "content": r["raw_content"],
            "al_label": pred_label,
            "al_confidence": confidence,
            "uncertainty": uncertainty,
        })

    # Sort by uncertainty ascending (lowest = most uncertain = review first)
    results.sort(key=lambda x: x["uncertainty"])
    return results[:limit]
