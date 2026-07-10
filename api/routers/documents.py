import asyncio
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import asyncpg

from api.deps import get_conn
from portfolio_architect.models.document import DocumentCreate, DocumentResponse
from portfolio_architect.db.documents import (
    insert_document,
    insert_chunks,
    get_documents,
    get_unembedded_chunks,
    update_chunk_embedding,
    mark_document_embedded,
)
from portfolio_architect.db.projects import get_project, update_project_state
from portfolio_architect.embedding.client import embed_batch
from portfolio_architect.ingestion.chunker import chunk_text

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


async def _embed_document(doc_id: UUID, project_id: UUID, chunk_texts: list[str]) -> None:
    """Background task: embed all chunks for a document."""
    from portfolio_architect.db.pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            # Fetch chunk IDs in order
            rows = await conn.fetch(
                "SELECT id FROM chunks WHERE document_id = $1 ORDER BY chunk_index",
                doc_id,
            )
            chunk_ids = [r["id"] for r in rows]

            embeddings = await embed_batch(chunk_texts)
            for chunk_id, emb in zip(chunk_ids, embeddings):
                emb_str = "[" + ",".join(str(v) for v in emb) + "]"
                await conn.execute(
                    "UPDATE chunks SET embedding = $2::vector WHERE id = $1",
                    chunk_id, emb_str,
                )
            await mark_document_embedded(conn, doc_id, len(chunk_texts))
        except Exception as e:
            # Log failure; don't crash the background task
            print(f"[embed_document] Failed for doc {doc_id}: {e}")


@router.post("", response_model=DocumentResponse, status_code=201)
async def ingest_document(
    project_id: UUID,
    body: DocumentCreate,
    background_tasks: BackgroundTasks,
    conn: asyncpg.Connection = Depends(get_conn),
):
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    doc = await insert_document(conn, project_id, body.source_id, body.content, body.doc_type)
    chunk_texts = chunk_text(body.content)
    await insert_chunks(conn, doc["id"], project_id, chunk_texts)

    # Move project state to ingesting if needed
    if project["state"] == "onboarding":
        await update_project_state(conn, project_id, "ingesting")

    # Trigger embedding in background
    background_tasks.add_task(_embed_document, doc["id"], project_id, chunk_texts)

    return DocumentResponse(
        id=doc["id"],
        project_id=project_id,
        source_id=doc["source_id"],
        doc_type=doc["doc_type"],
        chunk_count=0,  # Will be updated after embedding
        embedded=False,
        created_at=doc["created_at"],
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(project_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    rows = await get_documents(conn, project_id)
    return [
        DocumentResponse(
            id=r["id"],
            project_id=project_id,
            source_id=r["source_id"],
            doc_type=r["doc_type"],
            chunk_count=r["chunk_count"],
            embedded=r["embedded"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
