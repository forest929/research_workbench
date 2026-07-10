from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def insert_verdict(
    conn: _ConnProxy,
    project_id: UUID,
    run_id: UUID,
    stage: str,
    verdict_data: dict,
) -> dict:
    vid = str(uuid4())
    return await conn.fetchrow(
        """
        INSERT INTO judge_verdicts (
            id, project_id, run_id, stage,
            faithfulness_score, faithfulness_rationale,
            problem_integrity_score, problem_integrity_rationale,
            citation_accuracy_score, citation_accuracy_rationale,
            uncertainty_score, uncertainty_rationale,
            overall_score, verdict, death_spiral_reason, raw_llm_response
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        RETURNING *
        """,
        vid, str(project_id), str(run_id), stage,
        verdict_data.get("faithfulness_score"),
        verdict_data.get("faithfulness_rationale"),
        verdict_data.get("problem_integrity_score"),
        verdict_data.get("problem_integrity_rationale"),
        verdict_data.get("citation_accuracy_score"),
        verdict_data.get("citation_accuracy_rationale"),
        verdict_data.get("uncertainty_score"),
        verdict_data.get("uncertainty_rationale"),
        verdict_data.get("overall_score"),
        verdict_data["verdict"],
        verdict_data.get("death_spiral_reason"),
        verdict_data.get("raw_llm_response"),
    )


async def get_verdicts_for_run(conn: _ConnProxy, run_id: UUID) -> list[dict]:
    return await conn.fetch(
        "SELECT * FROM judge_verdicts WHERE run_id = ? ORDER BY stage",
        str(run_id),
    )


async def get_latest_verdict(conn: _ConnProxy, project_id: UUID) -> dict | None:
    return await conn.fetchrow(
        """
        SELECT * FROM judge_verdicts
        WHERE project_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        str(project_id),
    )
