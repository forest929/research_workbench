from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from api.deps import get_conn
from portfolio_architect.models.project import ProjectCreate, ProjectResponse, ProjectResolveRequest
from portfolio_architect.db.projects import insert_project, get_project, list_projects
from portfolio_architect.agents.coordinator import approve_project, resolve_death_spiral

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_response(row: dict) -> ProjectResponse:
    return ProjectResponse(**row)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate, conn: asyncpg.Connection = Depends(get_conn)):
    row = await insert_project(conn, body.name, body.description, body.scope_statement)
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
