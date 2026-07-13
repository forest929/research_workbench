"""Reading-list router: a researcher's curated set of publications per project.

Bookmark sources while reviewing clusters/conversations (POST), review them
later (GET), and remove them (DELETE). Source ids can contain slashes (e.g.
`doi:10.1001/jama...`), so delete captures `source_id` with a `:path` converter
so the whole id survives routing.
"""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_conn
from portfolio_architect.db.projects import get_project, insert_project, update_disease_vocab
from portfolio_architect.db.documents import parse_source_metadata, insert_document
from portfolio_architect.db.saved_publications import (
    save_publication, list_saved, delete_saved, saved_source_ids,
)
from portfolio_architect.vocab import infer_starter_vocab

router = APIRouter(prefix="/projects/{project_id}/reading-list", tags=["reading-list"])


class SavePublicationBody(BaseModel):
    source_id: str
    doi: str | None = None
    title: str | None = None
    note: str | None = None
    # None preserves existing provenance (e.g. a note edit on a DOI-added item);
    # a brand-new save defaults to 'conversation' in the DB layer.
    added_from: str | None = None


async def _require_project(conn, project_id: UUID) -> None:
    if not await get_project(conn, project_id):
        raise HTTPException(404, f"Project {project_id} not found")


@router.get("")
async def get_reading_list(project_id: UUID, conn=Depends(get_conn)):
    await _require_project(conn, project_id)
    items = await list_saved(conn, project_id)
    # Enrich each saved item with the paper's title / authors / journal / year /
    # DOI, parsed from the ingested document, so the list reads like a citation
    # rather than a bare PMID.
    if items:
        source_ids = [it["source_id"] for it in items]
        placeholders = ",".join("?" for _ in source_ids)
        docs = await conn.fetch(
            f"SELECT source_id, raw_content, pub_date FROM documents "
            f"WHERE project_id = ? AND source_id IN ({placeholders})",
            str(project_id), *source_ids,
        )
        by_id = {d["source_id"]: d for d in docs}
        for it in items:
            doc = by_id.get(it["source_id"])
            md = parse_source_metadata(doc["raw_content"]) if doc else {}
            it["title"] = it.get("title") or md.get("title") or None
            it["authors"] = md.get("authors") or None
            it["journal"] = md.get("journal") or None
            it["year"] = md.get("year") or (doc and doc["pub_date"]) or None
            it["doi"] = it.get("doi") or md.get("doi") or None
    return {"items": items}


@router.post("", status_code=201)
async def add_to_reading_list(
    project_id: UUID, body: SavePublicationBody, conn=Depends(get_conn)
):
    await _require_project(conn, project_id)
    if not body.source_id.strip():
        raise HTTPException(422, "source_id is required")
    return await save_publication(
        conn, project_id, body.source_id.strip(),
        doi=body.doi, title=body.title, note=body.note, added_from=body.added_from,
    )


class SpinoffBody(BaseModel):
    name: str | None = None


@router.post("/spinoff", status_code=201)
async def spinoff_from_reading_list(project_id: UUID, body: SpinoffBody, conn=Depends(get_conn)):
    """Start a NEW review seeded with only the papers in this reading list — the
    researcher's refined selection for the next round. Copies those documents
    into the fresh project; the workbench then analyzes them on open."""
    parent = await get_project(conn, project_id)
    if not parent:
        raise HTTPException(404, f"Project {project_id} not found")
    saved = await saved_source_ids(conn, project_id)
    if not saved:
        raise HTTPException(400, "The reading list is empty — save some papers first.")

    name = (body.name or "").strip() or f"Refined from {parent['name']}"
    scope = parent.get("scope_statement") or name
    new = await insert_project(conn, name, f"Refined selection from “{parent['name']}”.", scope)
    new_id = new["id"]

    seeded = infer_starter_vocab(scope, name)
    if seeded:
        await update_disease_vocab(conn, new_id, json.dumps(seeded))

    # Copy the selected papers' documents into the new project (no re-fetch).
    placeholders = ",".join("?" for _ in saved)
    docs = await conn.fetch(
        f"SELECT source_id, raw_content, doc_type, pub_date FROM documents "
        f"WHERE project_id = ? AND source_id IN ({placeholders})",
        str(project_id), *saved,
    )
    copied = 0
    for d in docs:
        doc = await insert_document(conn, new_id, d["source_id"], d["raw_content"], d["doc_type"])
        if d["pub_date"]:
            await conn.execute("UPDATE documents SET pub_date = ? WHERE id = ?", d["pub_date"], doc["id"])
        copied += 1
    return {"id": new_id, "name": name, "papers": copied}


@router.delete("/{source_id:path}", status_code=204)
async def remove_from_reading_list(
    project_id: UUID, source_id: str, conn=Depends(get_conn)
):
    """`:path` so source ids containing slashes (e.g. `doi:10.1001/jama...`)
    are captured whole from the URL rather than truncated at the first slash."""
    await _require_project(conn, project_id)
    await delete_saved(conn, project_id, source_id)
