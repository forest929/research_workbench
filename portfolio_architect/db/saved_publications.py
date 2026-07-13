"""CRUD for the curated reading list (saved_publications).

A researcher bookmarks publications while reviewing clusters/conversations, or
adds them by DOI. Rows are project-scoped so each project keeps its own separate
curated set. Saves are idempotent via UNIQUE(project_id, source_id) — re-saving
the same source updates the note/title rather than duplicating.
"""

from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def save_publication(
    conn: _ConnProxy,
    project_id: UUID | str,
    source_id: str,
    doi: str | None = None,
    title: str | None = None,
    note: str | None = None,
    added_from: str | None = None,
) -> dict:
    """Insert or update a saved publication. On conflict (same project+source)
    refresh doi/title/note but keep the original id and created_at. `added_from`
    is preserved when None — so editing a DOI-added item's note doesn't reset
    its provenance to 'conversation'. A brand-new row with added_from=None
    defaults to 'conversation'. Note clears to empty string but not to NULL
    (pass "" to clear, None to leave unchanged)."""
    await conn.execute(
        """
        INSERT INTO saved_publications (id, project_id, source_id, doi, title, note, added_from)
        VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, 'conversation'))
        ON CONFLICT(project_id, source_id) DO UPDATE SET
            doi        = COALESCE(excluded.doi, saved_publications.doi),
            title      = COALESCE(excluded.title, saved_publications.title),
            note       = COALESCE(excluded.note, saved_publications.note),
            added_from = COALESCE(?, saved_publications.added_from)
        """,
        str(uuid4()), str(project_id), source_id, doi, title, note, added_from, added_from,
    )
    return await conn.fetchrow(
        "SELECT * FROM saved_publications WHERE project_id = ? AND source_id = ?",
        str(project_id), source_id,
    )


async def list_saved(conn: _ConnProxy, project_id: UUID | str) -> list[dict]:
    return await conn.fetch(
        "SELECT * FROM saved_publications WHERE project_id = ? ORDER BY created_at DESC",
        str(project_id),
    )


async def delete_saved(conn: _ConnProxy, project_id: UUID | str, source_id: str) -> None:
    await conn.execute(
        "DELETE FROM saved_publications WHERE project_id = ? AND source_id = ?",
        str(project_id), source_id,
    )


async def saved_source_ids(conn: _ConnProxy, project_id: UUID | str) -> list[str]:
    """Just the bookmarked source_ids — powers the save/unsave toggle state."""
    rows = await conn.fetch(
        "SELECT source_id FROM saved_publications WHERE project_id = ?",
        str(project_id),
    )
    return [r["source_id"] for r in rows]
