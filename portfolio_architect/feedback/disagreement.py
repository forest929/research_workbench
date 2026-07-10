"""Track and analyze LLM vs human disagreements to surface prompt improvement opportunities."""

from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def record_disagreement(
    conn: _ConnProxy,
    project_id: UUID,
    document_id: UUID,
    llm_label: str,
    human_label: str,
    reason_code: str | None,
    llm_confidence: float | None,
) -> None:
    if llm_label == human_label:
        return
    await conn.execute(
        """INSERT INTO disagreements
               (id, project_id, document_id, llm_label, human_label, reason_code, llm_confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        str(uuid4()), str(project_id), str(document_id),
        llm_label, human_label, reason_code, llm_confidence,
    )


async def get_disagreement_stats(conn: _ConnProxy, project_id: UUID) -> dict:
    """Return aggregate disagreement stats for a project."""
    total_decisions = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM decisions WHERE project_id = ?", str(project_id)
    )
    total = total_decisions[0]["cnt"] if total_decisions else 0

    disagreements = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM disagreements WHERE project_id = ?", str(project_id)
    )
    disagree_count = disagreements[0]["cnt"] if disagreements else 0

    by_reason = await conn.fetch(
        """SELECT reason_code, COUNT(*) AS cnt
           FROM disagreements
           WHERE project_id = ? AND reason_code IS NOT NULL
           GROUP BY reason_code
           ORDER BY cnt DESC""",
        str(project_id),
    )

    by_direction = await conn.fetch(
        """SELECT llm_label, human_label, COUNT(*) AS cnt
           FROM disagreements
           WHERE project_id = ?
           GROUP BY llm_label, human_label
           ORDER BY cnt DESC""",
        str(project_id),
    )

    agreement_rate = round((total - disagree_count) / total, 3) if total > 0 else None

    return {
        "total_decisions": total,
        "disagreements": disagree_count,
        "agreement_rate": agreement_rate,
        "by_reason_code": [dict(r) for r in by_reason],
        "by_direction": [dict(r) for r in by_direction],
    }
