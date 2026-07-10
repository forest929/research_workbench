from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
import asyncpg

from api.deps import get_conn
from portfolio_architect.artifact.renderer import render_report
from portfolio_architect.db.projects import get_project

router = APIRouter(prefix="/projects/{project_id}", tags=["artifacts"])


@router.get("/report", response_class=PlainTextResponse)
async def get_report(project_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    report = await render_report(conn, project_id)
    return report
