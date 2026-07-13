"""Workstream: select representative prototype samples via lightweight k-means clustering."""

import math
from uuid import UUID

from portfolio_architect.embedding import codec
from portfolio_architect.retrieval.hybrid_search import search_chunks


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]


def _kmeans(embeddings: list[list[float]], k: int, max_iters: int = 20) -> list[int]:
    """Minimal k-means; returns cluster assignment for each embedding."""
    n = len(embeddings)
    if n == 0:
        return []
    k = min(k, n)
    # Initialize centroids as first k embeddings
    centroids = [embeddings[i][:] for i in range(k)]
    assignments = [0] * n

    for _ in range(max_iters):
        new_assignments = []
        for emb in embeddings:
            best = max(range(k), key=lambda j: _cosine_similarity(emb, centroids[j]))
            new_assignments.append(best)
        if new_assignments == assignments:
            break
        assignments = new_assignments
        for j in range(k):
            cluster_embs = [embeddings[i] for i, a in enumerate(assignments) if a == j]
            if cluster_embs:
                centroids[j] = _mean_vector(cluster_embs)

    return assignments


async def run(
    conn,
    project_id: UUID,
    scope_statement: str,
    n_clusters: int = 5,
) -> list[dict]:
    """Return one prototype chunk per cluster — the sample closest to its centroid."""
    chunks = await search_chunks(conn, scope_statement, project_id, top_k=50)
    if not chunks:
        return []

    # Fetch embeddings for these chunks
    chunk_ids = [c["chunk_id"] for c in chunks]
    if not chunk_ids:
        rows = []
    else:
        placeholders = ",".join("?" * len(chunk_ids))
        rows = await conn.fetch(
            f"SELECT id, embedding FROM chunks WHERE id IN ({placeholders})",
            *chunk_ids,
        )
    embedding_map: dict = {}
    for row in rows:
        if row["embedding"]:
            embedding_map[row["id"]] = codec.decode_list(row["embedding"])

    chunks_with_emb = [c for c in chunks if c["chunk_id"] in embedding_map]
    if not chunks_with_emb:
        return chunks[:n_clusters]

    embeddings = [embedding_map[c["chunk_id"]] for c in chunks_with_emb]
    assignments = _kmeans(embeddings, k=n_clusters)

    # Pick prototype: chunk with highest cosine similarity to centroid for its cluster
    cluster_groups: dict[int, list[int]] = {}
    for i, a in enumerate(assignments):
        cluster_groups.setdefault(a, []).append(i)

    prototypes = []
    for cluster_id, indices in cluster_groups.items():
        cluster_embs = [embeddings[i] for i in indices]
        centroid = _mean_vector(cluster_embs)
        best_idx = max(indices, key=lambda i: _cosine_similarity(embeddings[i], centroid))
        chunk = chunks_with_emb[best_idx].copy()
        chunk["cluster_id"] = str(cluster_id)
        prototypes.append(chunk)

    return prototypes
