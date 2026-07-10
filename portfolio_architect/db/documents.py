import json
from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


async def insert_document(
    conn: _ConnProxy,
    project_id: UUID,
    source_id: str,
    raw_content: str,
    doc_type: str = "paper",
) -> dict:
    """Insert a document for this project. Returns the existing row if (project_id, source_id) already present."""
    pid = str(project_id)
    did = str(uuid4())
    # ON CONFLICT DO NOTHING keeps the existing row intact (no ID churn, no cascade delete)
    await conn.execute(
        """
        INSERT INTO documents (id, project_id, source_id, doc_type, raw_content)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project_id, source_id) DO NOTHING
        """,
        did, pid, source_id, doc_type, raw_content,
    )
    return await conn.fetchrow(
        "SELECT * FROM documents WHERE project_id = ? AND source_id = ?",
        pid, source_id,
    )


async def insert_chunks(
    conn: _ConnProxy,
    document_id: UUID,
    project_id: UUID,
    chunks: list[str],
) -> list[dict]:
    did = str(document_id)
    pid = str(project_id)
    chunk_ids = [str(uuid4()) for _ in chunks]

    await conn.executemany(
        "INSERT OR IGNORE INTO chunks (id, document_id, project_id, chunk_index, content) VALUES (?, ?, ?, ?, ?)",
        [(chunk_ids[i], did, pid, i, c) for i, c in enumerate(chunks)],
    )
    await conn.executemany(
        "INSERT OR IGNORE INTO chunks_fts (chunk_id, project_id, content) VALUES (?, ?, ?)",
        [(chunk_ids[i], pid, c) for i, c in enumerate(chunks)],
    )
    return [{"id": chunk_ids[i], "chunk_index": i, "content": c} for i, c in enumerate(chunks)]


async def update_chunk_embedding(
    conn: _ConnProxy,
    chunk_id: UUID,
    embedding: list[float],
) -> None:
    await conn.execute(
        "UPDATE chunks SET embedding = ? WHERE id = ?",
        json.dumps(embedding), str(chunk_id),
    )


async def mark_document_embedded(conn: _ConnProxy, document_id: UUID, chunk_count: int) -> None:
    await conn.execute(
        "UPDATE documents SET embedded = 1, chunk_count = ? WHERE id = ?",
        chunk_count, str(document_id),
    )


async def get_unembedded_chunks(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    return await conn.fetch(
        """
        SELECT c.id, c.document_id, c.content
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.project_id = ?
          AND d.embedded = 0
          AND c.embedding IS NULL
        ORDER BY c.created_at
        """,
        str(project_id),
    )


async def get_documents(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at",
        str(project_id),
    )
    for r in rows:
        r["embedded"] = bool(r["embedded"])
    return rows
