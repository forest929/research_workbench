from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
import asyncpg

import json

from api.deps import get_conn
from portfolio_architect.models.project import ProjectCreate, ProjectResponse, ProjectResolveRequest
from portfolio_architect.db.projects import insert_project, get_project, list_projects, update_disease_vocab, delete_project
from portfolio_architect.vocab import infer_starter_vocab
from portfolio_architect.agents.coordinator import approve_project, resolve_death_spiral

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_response(row: dict) -> ProjectResponse:
    return ProjectResponse(**row)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate, conn: asyncpg.Connection = Depends(get_conn)):
    row = await insert_project(conn, body.name, body.description, body.scope_statement)
    # Seed a starter disease vocabulary from the scope/name/description so the
    # workbench's disease filter isn't empty on a fresh project. No-op when
    # nothing matches; the researcher can always refine it via "Edit diseases".
    seeded = infer_starter_vocab(body.scope_statement, body.name, body.description)
    if seeded:
        await update_disease_vocab(conn, row["id"], json.dumps(seeded))
        row = await get_project(conn, row["id"])
    return _to_response(row)


@router.get("", response_model=list[ProjectResponse])
async def list_all_projects(conn: asyncpg.Connection = Depends(get_conn)):
    rows = await list_projects(conn)
    return [_to_response(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_one_project(project_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    row = await get_project(conn, project_id)
    if not row:
        raise HTTPException(404, f"Project {project_id} not found")
    return _to_response(row)


@router.delete("/{project_id}", status_code=204)
async def delete_one_project(project_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    """Delete a project and all of its data (documents, claims, clusters, saved
    publications). Cascades via foreign keys. Signals any in-flight build to stop
    first so the cascade delete doesn't race the background pipeline's writes."""
    if not await get_project(conn, project_id):
        raise HTTPException(404, f"Project {project_id} not found")
    from api.routers.ingest import request_cancel
    request_cancel(project_id)
    await delete_project(conn, project_id)


@router.post("/{project_id}/approve", response_model=ProjectResponse)
async def approve(project_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    try:
        await approve_project(conn, project_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    row = await get_project(conn, project_id)
    return _to_response(row)


@router.post("/{project_id}/resolve", response_model=ProjectResponse)
async def resolve(
    project_id: UUID,
    body: ProjectResolveRequest,
    conn: asyncpg.Connection = Depends(get_conn),
):
    try:
        await resolve_death_spiral(conn, project_id, body.resolution_guidance)
    except ValueError as e:
        raise HTTPException(409, str(e))
    row = await get_project(conn, project_id)
    return _to_response(row)
