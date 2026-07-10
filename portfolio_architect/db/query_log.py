from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def log_llm_call(
    conn: _ConnProxy,
    call_type: str,
    model: str,
    project_id: UUID | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    latency_ms: int | None = None,
    success: bool = True,
    error_msg: str | None = None,
) -> None:
    lid = str(uuid4())
    pid = str(project_id) if project_id else None
    await conn.execute(
        """
        INSERT INTO query_log
            (id, project_id, call_type, model, prompt_tokens, completion_tokens,
             total_tokens, latency_ms, success, error_msg)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        lid, pid, call_type, model,
        prompt_tokens, completion_tokens, total_tokens,
        latency_ms, 1 if success else 0, error_msg,
    )


async def get_cost_summary(conn: _ConnProxy, project_id: UUID | None = None) -> dict:
    if project_id:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS calls,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                SUM(success) AS successes
            FROM query_log
            WHERE project_id = ?
            """,
            str(project_id),
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS calls,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                SUM(success) AS successes
            FROM query_log
            """
        )
    return row or {}
