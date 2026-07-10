"""Search-driven ingest router: search term → background scrape → embed."""

import asyncio
import json
from uuid import UUID

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from pydantic import BaseModel

from api.deps import get_conn, get_db_pool
from portfolio_architect.db.projects import get_project
from portfolio_architect.db.documents import insert_document, insert_chunks
from portfolio_architect.ingestion.chunker import chunk_text
from portfolio_architect.ingestion.fetchers import (
    scholar_fetch, arxiv_fetch,
    record_to_text, deduplicate,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["ingest"])

# In-memory progress store keyed by project_id string
_progress: dict[str, dict] = {}


class SearchBody(BaseModel):
    query: str
    sources: list[str] = ["scholar", "arxiv"]
    max_records: int = 200


@router.post("/search")
async def trigger_search(
    project_id: UUID,
    body: SearchBody,
    background_tasks: BackgroundTasks,
    conn=Depends(get_conn),
    pool=Depends(get_db_pool),
):
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    pid_str = str(project_id)
    if _progress.get(pid_str, {}).get("status") == "running":
        raise HTTPException(409, "An ingest job is already running for this project.")

    _progress[pid_str] = {
        "status": "running",
        "query": body.query,
        "sources": body.sources,
        "fetched": 0,
        "ingested": 0,
        "embedded": 0,
        "total": 0,
        "error": None,
    }

    background_tasks.add_task(_run_ingest, pool, project_id, body)
    return {"status": "started", "project_id": pid_str}


@router.get("/ingest-status")
async def ingest_status(project_id: UUID, conn=Depends(get_conn)):
    pid_str = str(project_id)
    progress = _progress.get(pid_str, {"status": "idle"})

    # Also pull live DB counts
    doc_rows = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM documents WHERE project_id = ?", pid_str
    )
    emb_rows = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM documents WHERE project_id = ? AND embedded = 1", pid_str
    )
    pending_rows = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM documents WHERE project_id = ? AND embedded = 0", pid_str
    )

    return {
        **progress,
        "db_total": doc_rows[0]["cnt"] if doc_rows else 0,
        "db_embedded": emb_rows[0]["cnt"] if emb_rows else 0,
        "db_pending": pending_rows[0]["cnt"] if pending_rows else 0,
    }


async def _run_ingest(pool, project_id: UUID, body: SearchBody) -> None:
    pid_str = str(project_id)
    prog = _progress[pid_str]

    def update(**kw):
        prog.update(kw)

    try:
        records: list[dict] = []
        half = body.max_records // max(len(body.sources), 1)

        if "scholar" in body.sources:
            scholar_recs = await asyncio.to_thread(scholar_fetch, body.query, half)
            records.extend(scholar_recs)
            update(fetched=len(records), total=body.max_records)

        if "arxiv" in body.sources:
            arxiv_recs = await asyncio.to_thread(arxiv_fetch, body.query, half)
            records.extend(arxiv_recs)
            update(fetched=len(records))

        records = deduplicate(records)
        if len(records) > body.max_records:
            records = records[: body.max_records]

        update(fetched=len(records), total=len(records))

        # Ingest into DB — insert_document returns existing row on duplicate (project_id, source_id)
        async with pool.acquire() as conn:
            new_count = 0
            for idx, rec in enumerate(records):
                raw_text = record_to_text(rec)
                chunks = chunk_text(raw_text)
                if not chunks:
                    continue
                doc = await insert_document(conn, project_id, rec["source_id"], raw_text)
                # Only chunk/embed if this is a fresh insert (chunk_count == 0)
                if not doc.get("chunk_count"):
                    await insert_chunks(conn, doc["id"], project_id, chunks)
                    new_count += 1
                if idx % 20 == 0:
                    update(ingested=idx + 1)
            update(ingested=new_count)

        update(ingested=len(records), status="embedding")

        # Trigger embedding for all unembedded chunks
        await _embed_all(pool, project_id)
        update(status="done", embedded=len(records))

    except Exception as e:
        update(status="error", error=str(e)[:300])


@router.post("/upload")
async def upload_dataset(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pool=Depends(get_db_pool),
    conn=Depends(get_conn),
):
    """Accept a CSV or Excel file and ingest rows as documents."""
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    content = await file.read()
    records: list[dict] = []

    if file.filename.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            rec = _row_to_record(row)
            if rec:
                records.append(rec)
    elif file.filename.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(503, "openpyxl not installed — cannot read Excel files")
        wb = openpyxl.load_workbook(io.BytesIO(content))
        ws = wb.active
        headers = [str(c.value or "").strip().lower() for c in next(ws.iter_rows(min_row=1, max_row=1))]
        for row in ws.iter_rows(min_row=2, values_only=True):
            d = dict(zip(headers, row))
            rec = _row_to_record(d)
            if rec:
                records.append(rec)
    else:
        raise HTTPException(400, "Only .csv and .xlsx/.xls files are supported")

    records = deduplicate(records)
    pid_str = str(project_id)
    _progress[pid_str] = {"status": "running", "fetched": len(records), "ingested": 0, "embedded": 0, "total": len(records), "error": None}
    background_tasks.add_task(_ingest_records, pool, project_id, records)
    return {"status": "started", "record_count": len(records)}


def _row_to_record(row: dict) -> dict | None:
    title = str(row.get("title") or row.get("Title") or "").strip()
    abstract = str(row.get("abstract") or row.get("Abstract") or row.get("summary") or "").strip()
    if not title and not abstract:
        return None
    import hashlib
    sid = "upload:" + hashlib.md5((title + abstract).encode()).hexdigest()[:12]
    return {
        "source": "upload",
        "source_id": sid,
        "title": title,
        "abstract": abstract,
        "authors": str(row.get("authors") or row.get("author") or ""),
        "journal": str(row.get("journal") or row.get("venue") or ""),
        "year": str(row.get("year") or row.get("pub_year") or ""),
        "doi": str(row.get("doi") or row.get("DOI") or ""),
        "url": str(row.get("url") or row.get("link") or ""),
    }


async def _ingest_records(pool, project_id: UUID, records: list[dict]) -> None:
    pid_str = str(project_id)
    prog = _progress.get(pid_str, {})
    async with pool.acquire() as conn:
        new_count = 0
        for idx, rec in enumerate(records):
            raw_text = record_to_text(rec)
            chunks = chunk_text(raw_text)
            if not chunks:
                continue
            doc = await insert_document(conn, project_id, rec["source_id"], raw_text)
            if not doc.get("chunk_count"):
                await insert_chunks(conn, doc["id"], project_id, chunks)
                new_count += 1
            if idx % 20 == 0:
                prog["ingested"] = idx + 1
    prog["status"] = "embedding"
    await _embed_all(pool, project_id)
    prog["status"] = "done"
    prog["embedded"] = new_count


async def _embed_all(pool, project_id: UUID) -> None:
    """Embed all unembedded chunks for the project."""
    from portfolio_architect.embedding.client import embed_batch
    from portfolio_architect.db.documents import update_chunk_embedding

    pid_str = str(project_id)
    prog = _progress.get(pid_str, {})
    BATCH = 64

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content FROM chunks WHERE project_id = ? AND embedding IS NULL",
            pid_str,
        )

    if not rows:
        return

    embedded_count = 0
    doc_ids: set[str] = set()

    for i in range(0, len(rows), BATCH):
        batch = rows[i: i + BATCH]
        texts = [r["content"] for r in batch]
        try:
            embeddings = await embed_batch(texts)
        except Exception:
            continue
        async with pool.acquire() as conn:
            for row, emb in zip(batch, embeddings):
                await update_chunk_embedding(conn, row["id"], emb)

            # mark docs embedded using a sub-query approach
            chunk_ids = [r["id"] for r in batch]
            for chunk_id in chunk_ids:
                doc_row = await conn.fetchrow(
                    "SELECT document_id FROM chunks WHERE id = ?", chunk_id
                )
                if doc_row:
                    doc_ids.add(doc_row["document_id"])

        embedded_count += len(batch)
        prog["embedded"] = embedded_count

    async with pool.acquire() as conn:
        for doc_id in doc_ids:
            await conn.execute(
                "UPDATE documents SET embedded = 1 WHERE id = ?", doc_id
            )
