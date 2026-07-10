import json
from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def insert_run(
    conn: _ConnProxy,
    project_id: UUID,
    run_id: UUID,
    workstream: str,
) -> dict:
    rid = str(uuid4())
    return await conn.fetchrow(
        """
        INSERT INTO workstream_runs (id, project_id, run_id, workstream)
        VALUES (?, ?, ?, ?)
        RETURNING *
        """,
        rid, str(project_id), str(run_id), workstream,
    )


async def update_run_status(
    conn: _ConnProxy,
    run_id: UUID,
    workstream: str,
    status: str,
    result: dict | None = None,
    error_msg: str | None = None,
) -> None:
    result_json = json.dumps(result) if result else None
    if status == "running":
        await conn.execute(
            """
            UPDATE workstream_runs
            SET status = ?, started_at = datetime('now')
            WHERE run_id = ? AND workstream = ?
            """,
            status, str(run_id), workstream,
        )
    else:
        await conn.execute(
            """
            UPDATE workstream_runs
            SET status = ?, result_json = ?, error_msg = ?, finished_at = datetime('now')
            WHERE run_id = ? AND workstream = ?
            """,
            status, result_json, error_msg, str(run_id), workstream,
        )


async def get_runs_for_project(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    return await conn.fetch(
        "SELECT * FROM workstream_runs WHERE project_id = ? ORDER BY created_at DESC",
        str(project_id),
    )


async def get_run_group(conn: _ConnProxy, run_id: UUID) -> list[dict]:
    return await conn.fetch(
        "SELECT * FROM workstream_runs WHERE run_id = ? ORDER BY workstream",
        str(run_id),
    )
