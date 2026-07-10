from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from api.deps import get_conn
from portfolio_architect.models.workstream import DiscrepancyRequest, DiscrepancyResponse
from portfolio_architect.discrepancy.analyzer import analyze
from portfolio_architect.db.projects import get_project

router = APIRouter(prefix="/projects/{project_id}", tags=["discrepancy"])


@router.post("/discrepancy", response_model=DiscrepancyResponse)
async def analyze_discrepancy(
    project_id: UUID,
    body: DiscrepancyRequest,
    conn: asyncpg.Connection = Depends(get_conn),
):
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    result = await analyze(
        conn, project_id,
        body.definition_a, body.definition_b,
        body.label_a, body.label_b,
    )
    return DiscrepancyResponse(
        project_id=result["project_id"],
        run_id=result["run_id"],
        friction_points=result["friction_points"],
        semantic_overlap=result["semantic_overlap"],
        recommendation=result["recommendation"],
    )
