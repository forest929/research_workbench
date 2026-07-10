import json
from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def get_claims_with_embeddings(
    conn: _ConnProxy,
    project_id: UUID,
    verified_only: bool = False,
    exclude_trials: bool = False,
) -> list[dict]:
    """Claims with embeddings for clustering. Optionally restrict to
    quote-verified claims and/or exclude trial-sourced claims (joins documents
    on doc_type) — used to build a clean, verified, PubMed-only cluster set."""
    where = ["c.project_id = ?", "c.claim_embedding IS NOT NULL"]
    params: list = [str(project_id)]
    if verified_only:
        where.append("c.quote_verified = 1")
    if exclude_trials:
        where.append("d.doc_type != 'trial'")
    return await conn.fetch(
        f"""
        SELECT c.*, d.doc_type
        FROM claims c JOIN documents d ON c.document_id = d.id
        WHERE {' AND '.join(where)}
        """,
        *params,
    )


async def reset_project_clusters(conn: _ConnProxy, project_id: UUID) -> None:
    """Delete all clusters for a project and clear claims.cluster_id, so
    clustering can be re-derived from scratch (e.g. after a threshold or
    blocking-key change)."""
    await conn.execute("DELETE FROM claim_clusters WHERE project_id = ?", str(project_id))
    await conn.execute("UPDATE claims SET cluster_id = NULL WHERE project_id = ?", str(project_id))


async def insert_cluster(
    conn: _ConnProxy,
    project_id: UUID,
    intervention_key: str,
    member_claim_ids: list[str],
    distinct_document_count: int,
    verdict_mix: dict,
) -> dict:
    cid = str(uuid4())
    await conn.execute(
        """
        INSERT INTO claim_clusters
            (id, project_id, intervention_key, member_count, distinct_document_count, verdict_mix_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        cid, str(project_id), intervention_key, len(member_claim_ids),
        distinct_document_count, json.dumps(verdict_mix),
    )
    await conn.executemany(
        "UPDATE claims SET cluster_id = ? WHERE id = ?",
        [(cid, claim_id) for claim_id in member_claim_ids],
    )
    return await conn.fetchrow("SELECT * FROM claim_clusters WHERE id = ?", cid)


async def set_conversation(
    conn: _ConnProxy, cluster_id: str, question: str, answer: str, citations_valid: bool
) -> None:
    await conn.execute(
        "UPDATE claim_clusters SET question = ?, answer = ?, citations_valid = ? WHERE id = ?",
        question, answer, 1 if citations_valid else 0, cluster_id,
    )


async def get_clusters_for_project(conn: _ConnProxy, project_id: UUID, with_answer_only: bool = False) -> list[dict]:
    query = "SELECT * FROM claim_clusters WHERE project_id = ?"
    if with_answer_only:
        query += " AND answer IS NOT NULL"
    query += " ORDER BY created_at"
    return await conn.fetch(query, str(project_id))


async def get_cluster_members(conn: _ConnProxy, cluster_id: str) -> list[dict]:
    return await conn.fetch(
        # Explicit columns — never SELECT * here. Two reasons: (1) claim_embedding
        # (a 4096-float JSON blob) and raw_llm_response are huge and unused; (2) we
        # deliberately select ONLY columns stored *before* claim_embedding in row
        # order, so SQLite reads just the main page per row and never chases the
        # blob's overflow pages. Selecting created_at/cluster_id (declared after
        # the blob) would reintroduce that cost. Ordering by id avoids it too.
        # Combined with idx_claims_cluster, a 500-member cluster loads in ms.
        """
        SELECT c.id, c.claim_text, c.population, c.intervention, c.comparator,
               c.outcome, c.verdict, c.evidence_quote, c.quote_verified,
               c.effect_size, c.statistical_significance, c.confidence,
               d.source_id, d.doc_type, d.pub_date
        FROM claims c JOIN documents d ON c.document_id = d.id
        WHERE c.cluster_id = ?
        ORDER BY c.id
        """,
        cluster_id,
    )
