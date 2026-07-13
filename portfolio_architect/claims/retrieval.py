"""Live topic -> claims retrieval for the workbench's on-the-fly path.

Embeds a free-text interest topic and finds the nearest existing claims across
the project's corpus by cosine similarity, so a conversation can be synthesized
from real, already-verified evidence rather than a fresh ingest. The query MUST
be embedded with the same model that produced the stored claim embeddings
(Qwen/Qwen3-Embedding-8B, dim 4096) — enforced by a runtime dimension check,
since a mismatched model would make cosine distances meaningless.

Vectorized with numpy (like claims/clustering.py) rather than the pure-Python
cosine loops in feedback/decision_memory.py — the claim table runs into the
thousands at 4096-dim, where a single matrix-vector product is far faster.
"""

from uuid import UUID

import numpy as np

from portfolio_architect.db.pool import _ConnProxy
from portfolio_architect.embedding import codec
from portfolio_architect.embedding import client as embedding


async def retrieve_claims_for_topic(
    conn: _ConnProxy,
    project_id: UUID,
    topic: str,
    top_k: int = 40,
) -> list[dict]:
    """Return the top_k claims (with source_id/doc_type joined) most similar to
    `topic`, each annotated with a cosine `score`. Empty list if the project has
    no embedded claims. Raises ValueError if the query embedding dimension does
    not match the stored claim embeddings."""
    rows = await conn.fetch(
        """
        SELECT c.*, d.source_id, d.doc_type
        FROM claims c JOIN documents d ON c.document_id = d.id
        WHERE c.project_id = ? AND c.claim_embedding IS NOT NULL
        """,
        str(project_id),
    )
    if not rows:
        return []

    query_vec = np.array(await embedding.embed_text(topic), dtype=np.float32)

    matrix = np.array([codec.decode(r["claim_embedding"]) for r in rows], dtype=np.float32)
    if matrix.shape[1] != query_vec.shape[0]:
        raise ValueError(
            f"Embedding dimension mismatch: query is {query_vec.shape[0]}-dim but "
            f"stored claim embeddings are {matrix.shape[1]}-dim. The topic must be "
            f"embedded with the same model the corpus was built with "
            f"(check EMBEDDING_MODEL / EMBEDDING_DIM in .env)."
        )

    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1e-9
    q_norm = np.linalg.norm(query_vec) or 1e-9
    sims = (matrix @ query_vec) / (norms * q_norm)

    order = np.argsort(-sims)[:top_k]
    results = []
    for i in order:
        r = dict(rows[int(i)])
        r["score"] = float(sims[int(i)])
        r.pop("claim_embedding", None)  # large; not needed downstream
        r.pop("raw_llm_response", None)
        results.append(r)
    return results
