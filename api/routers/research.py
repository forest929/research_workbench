import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_conn, get_db_pool
from portfolio_architect.db.projects import get_project
from portfolio_architect.db.criteria import get_criteria
from portfolio_architect.db.judge_verdicts import get_latest_verdict
from portfolio_architect.db.workstream_runs import get_runs_for_project
from portfolio_architect.agents.coordinator import trigger_research_run

router = APIRouter(prefix="/projects/{project_id}", tags=["research"])


@router.post("/run")
async def run_research(
    project_id: UUID,
    pool=Depends(get_db_pool),
    conn=Depends(get_conn),
):
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    allowed_states = {"ingesting", "embedding", "awaiting_review", "complete", "death_spiral"}
    if project["state"] not in allowed_states:
        raise HTTPException(409, f"Cannot run in state '{project['state']}'")

    result = await trigger_research_run(pool, project_id)
    return result


@router.get("/results")
async def get_latest_results(project_id: UUID, conn=Depends(get_conn)):
    """Return the most recent analysis results stored in the DB (criteria, synthesis, verdict)."""
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    criteria = await get_criteria(conn, project_id)
    verdict = await get_latest_verdict(conn, project_id)

    # Pull synthesis text from the most recent completed literature_synthesis run
    synthesis_rows = await conn.fetch(
        """SELECT result_json FROM workstream_runs
           WHERE project_id = ? AND workstream = 'literature_synthesis' AND status = 'complete'
           ORDER BY finished_at DESC LIMIT 1""",
        str(project_id),
    )
    synthesis = ""
    if synthesis_rows:
        try:
            parsed = json.loads(synthesis_rows[0]["result_json"] or "{}")
            synthesis = parsed.get("data", "")
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "project": project,
        "criteria": criteria,
        "synthesis": synthesis,
        "latest_verdict": verdict,
    }


@router.get("/runs")
async def list_runs(project_id: UUID, conn=Depends(get_conn)):
    return await get_runs_for_project(conn, project_id)
