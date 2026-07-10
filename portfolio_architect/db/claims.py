import json
from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def get_unprocessed_documents(conn: _ConnProxy, project_id: UUID, limit: int | None = None) -> list[dict]:
    query = "SELECT * FROM documents WHERE project_id = ? AND claims_extracted = 0 ORDER BY created_at"
    params: list = [str(project_id)]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return await conn.fetch(query, *params)


async def insert_claims(conn: _ConnProxy, project_id: UUID, document_id: UUID, claims: list[dict]) -> None:
    pid = str(project_id)
    did = str(document_id)
    rows = []
    for c in claims:
        rows.append((
            str(uuid4()), pid, did,
            c["claim"], c.get("population"), c.get("intervention"),
            c.get("comparator"), c.get("outcome"), c["verdict"],
            c.get("evidence_quote"), 1 if c.get("quote_verified") else 0,
            c.get("effect_size"), c.get("statistical_significance"),
            c.get("confidence"), c.get("raw_llm_response"),
        ))
    if rows:
        await conn.executemany(
            """
            INSERT INTO claims
                (id, project_id, document_id, claim_text, population, intervention,
                 comparator, outcome, verdict, evidence_quote, quote_verified,
                 effect_size, statistical_significance, confidence, raw_llm_response)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )


async def mark_document_processed(
    conn: _ConnProxy, document_id: UUID, research_question: str | None
) -> None:
    await conn.execute(
        "UPDATE documents SET claims_extracted = 1, research_question = ? WHERE id = ?",
        research_question, str(document_id),
    )


async def get_claims_for_project(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    return await conn.fetch(
        "SELECT * FROM claims WHERE project_id = ? ORDER BY created_at", str(project_id)
    )


async def get_verdict_summary(conn: _ConnProxy, project_id: UUID) -> dict:
    rows = await conn.fetch(
        "SELECT verdict, COUNT(*) AS n, SUM(quote_verified) AS verified FROM claims WHERE project_id = ? GROUP BY verdict",
        str(project_id),
    )
    return {r["verdict"]: {"count": r["n"], "verified": r["verified"]} for r in rows}
