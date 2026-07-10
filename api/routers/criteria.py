from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from api.deps import get_conn
from portfolio_architect.models.criterion import (
    CriterionResponse,
    CriterionPatch,
    GoldLabelCreate,
)
from portfolio_architect.db.criteria import (
    get_criteria,
    patch_criterion,
    delete_criterion,
    upsert_gold_label,
    get_gold_labels,
)
from portfolio_architect.db.projects import get_project

router = APIRouter(prefix="/projects/{project_id}", tags=["criteria"])


def _row_to_response(r: dict) -> CriterionResponse:
    return CriterionResponse(
        id=r["id"],
        project_id=r["project_id"],
        workstream_run_id=r.get("workstream_run_id"),
        criterion_type=r["criterion_type"],
        statement=r["statement"],
        rationale=r["rationale"],
        source_ids=r["source_ids"] or [],
        confidence=r["confidence"],
        is_gold=r["is_gold"],
        gold_note=r.get("gold_note"),
        gold_set_at=r.get("gold_set_at"),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


@router.get("/criteria", response_model=list[CriterionResponse])
async def list_criteria(project_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    rows = await get_criteria(conn, project_id)
    return [_row_to_response(r) for r in rows]


@router.patch("/criteria/{criterion_id}", response_model=CriterionResponse)
async def update_criterion(
    project_id: UUID,
    criterion_id: UUID,
    body: CriterionPatch,
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await patch_criterion(conn, criterion_id, project_id, body.model_dump(exclude_none=True))
    if not row:
        raise HTTPException(404, f"Criterion {criterion_id} not found")
    return _row_to_response(row)


@router.delete("/criteria/{criterion_id}", status_code=204)
async def remove_criterion(
    project_id: UUID,
    criterion_id: UUID,
    conn: asyncpg.Connection = Depends(get_conn),
):
    removed = await delete_criterion(conn, criterion_id, project_id)
    if not removed:
        raise HTTPException(404, f"Criterion {criterion_id} not found")


@router.post("/gold-labels", status_code=201)
async def create_gold_label(
    project_id: UUID,
    body: GoldLabelCreate,
    conn: asyncpg.Connection = Depends(get_conn),
):
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    row = await upsert_gold_label(conn, project_id, body.model_dump())
    return dict(row)


@router.get("/gold-labels")
async def list_gold_labels(project_id: UUID, conn: asyncpg.Connection = Depends(get_conn)):
    return await get_gold_labels(conn, project_id)
