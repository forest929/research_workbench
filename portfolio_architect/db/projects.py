from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy, is_postgres


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


async def update_disease_vocab(conn: _ConnProxy, project_id: UUID, vocab_json: str) -> None:
    await conn.execute(
        "UPDATE projects SET disease_vocab_json = ?, updated_at = datetime('now') WHERE id = ?",
        vocab_json, str(project_id),
    )


async def list_projects(conn: _ConnProxy) -> list[dict]:
    return await conn.fetch("SELECT * FROM projects ORDER BY created_at DESC")


async def delete_project(conn: _ConnProxy, project_id: UUID | str) -> None:
    """Delete a project and everything under it. Child tables (documents, claims,
    clusters, chunks, saved_publications, user_sources) are ON DELETE CASCADE and
    the pool enables PRAGMA foreign_keys, so one delete cleans up the whole tree.

    chunks_fts is an FTS5 virtual table with no foreign key, so the cascade never
    reaches it — we purge its rows explicitly by project_id (a single FTS scan,
    versus a per-chunk scan a trigger would cost) to avoid orphaning search rows.
    On Postgres full-text search is a generated column on chunks, which the
    cascade removes with its row, so there is nothing extra to purge."""
    pid = str(project_id)
    if not is_postgres():
        await conn.execute("DELETE FROM chunks_fts WHERE project_id = ?", pid)
    await conn.execute("DELETE FROM projects WHERE id = ?", pid)
