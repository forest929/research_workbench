from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def insert_project(conn: _ConnProxy, name: str, description: str, scope_statement: str) -> dict:
    pid = str(uuid4())
    return await conn.fetchrow(
        """
        INSERT INTO projects (id, name, description, scope_statement)
        VALUES (?, ?, ?, ?)
        RETURNING *
        """,
        pid, name, description, scope_statement,
    )


async def get_project(conn: _ConnProxy, project_id: UUID) -> dict | None:
    return await conn.fetchrow("SELECT * FROM projects WHERE id = ?", str(project_id))


async def update_project_state(
    conn: _ConnProxy,
    project_id: UUID,
    state: str,
    death_spiral_reason: str | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE projects
        SET state = ?,
            death_spiral_reason = ?,
            updated_at = datetime('now'),
            iteration_count = CASE WHEN ? = 'analyzing' THEN iteration_count + 1 ELSE iteration_count END
        WHERE id = ?
        """,
        state, death_spiral_reason, state, str(project_id),
    )


async def update_scope_statement(conn: _ConnProxy, project_id: UUID, scope_statement: str) -> None:
    await conn.execute(
        "UPDATE projects SET scope_statement = ?, updated_at = datetime('now') WHERE id = ?",
        scope_statement, str(project_id),
    )


async def list_projects(conn: _ConnProxy) -> list[dict]:
    return await conn.fetch("SELECT * FROM projects ORDER BY created_at DESC")
