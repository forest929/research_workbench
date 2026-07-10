"""Orchestration Layer: Project Coordinator.

Manages state transitions and delegates to workstreams.
Acts as the top-level agent that drives the research lifecycle.
"""

import asyncpg
from asyncpg import Pool
from uuid import UUID, uuid4

from portfolio_architect.db.projects import (
    get_project,
    update_project_state,
    update_scope_statement,
)
from portfolio_architect.db.criteria import get_criteria
from portfolio_architect.db.judge_verdicts import insert_verdict
from portfolio_architect.agents import runner
from portfolio_architect.judge.structural_check import run as structural_check
from portfolio_architect.judge.logical_check import run as logical_check
from portfolio_architect.retrieval.hybrid_search import search_chunks, chunks_to_xml


async def trigger_research_run(
    pool: asyncpg.Pool,
    project_id: UUID,
) -> dict:
    """
    Entry point: move project → ANALYZING, run workstreams (parallel, each with own conn),
    run two-stage judge, transition to AWAITING_REVIEW / DEATH_SPIRAL / FAILED.
    """
    async with pool.acquire() as conn:
        project = await get_project(conn, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        scope_statement = project["scope_statement"]
        run_id = uuid4()
        await update_project_state(conn, project_id, "analyzing")

    # Run workstreams — each acquires its own connection from the pool
    ws_output = await runner.run_all(pool, project_id, run_id, scope_statement)
    all_failed = all(ws_output["errors"].get(ws) for ws in
                     ["parameter_extraction", "literature_synthesis", "cluster_selection"])

    if all_failed:
        async with pool.acquire() as conn:
            await update_project_state(conn, project_id, "failed")
        return {
            "project_id": project_id,
            "run_id": run_id,
            "state_after": "failed",
            "errors": ws_output["errors"],
        }

    criteria = ws_output.get("criteria", [])

    # Stage 1: structural check (pure Python, no LLM, no DB needed)
    structural_result = await structural_check(
        conn=None,
        project_id=project_id,
        run_id=run_id,
        criteria=criteria,
    )
    async with pool.acquire() as conn:
        await insert_verdict(conn, project_id, run_id, "structural", structural_result)

    if structural_result["verdict"] == "fail":
        async with pool.acquire() as conn:
            await update_project_state(conn, project_id, "awaiting_review")
        return {
            "project_id": project_id,
            "run_id": run_id,
            "state_after": "awaiting_review",
            "structural_verdict": structural_result,
            "note": "Structural check failed — criteria extracted but need human review.",
            "criteria": criteria,
        }

    # Stage 2: logical/semantic LLM judge (needs chunks for context)
    async with pool.acquire() as conn:
        chunks = await search_chunks(conn, scope_statement, project_id)
        chunks_xml = chunks_to_xml(chunks)
        logical_result = await logical_check(
            conn=conn,
            project_id=project_id,
            run_id=run_id,
            scope_statement=scope_statement,
            criteria=criteria,
            chunks_xml=chunks_xml,
        )
        await insert_verdict(conn, project_id, run_id, "logical", logical_result)

    if logical_result["verdict"] == "death_spiral":
        reason = logical_result.get("death_spiral_reason", "Unresolvable contradiction detected.")
        async with pool.acquire() as conn:
            await update_project_state(conn, project_id, "death_spiral", death_spiral_reason=reason)
        return {
            "project_id": project_id,
            "run_id": run_id,
            "state_after": "death_spiral",
            "death_spiral_reason": reason,
            "logical_verdict": logical_result,
            "criteria": criteria,
        }

    async with pool.acquire() as conn:
        await update_project_state(conn, project_id, "awaiting_review")
    return {
        "project_id": project_id,
        "run_id": run_id,
        "state_after": "awaiting_review",
        "structural_verdict": structural_result,
        "logical_verdict": logical_result,
        "synthesis": ws_output.get("synthesis", ""),
        "prototypes": ws_output.get("prototypes", []),
        "criteria": criteria,
        "errors": ws_output.get("errors", {}),
    }


async def resolve_death_spiral(
    conn: asyncpg.Connection,
    project_id: UUID,
    resolution_guidance: str,
) -> None:
    """Append resolution guidance to scope_statement and reset to ingesting for re-run."""
    project = await get_project(conn, project_id)
    if not project or project["state"] != "death_spiral":
        raise ValueError(f"Project {project_id} is not in death_spiral state")

    new_scope = (
        project["scope_statement"]
        + f"\n\n[RESOLUTION GUIDANCE]\n{resolution_guidance}"
    )
    await update_scope_statement(conn, project_id, new_scope)
    await update_project_state(conn, project_id, "ingesting")


async def approve_project(conn: asyncpg.Connection, project_id: UUID) -> None:
    """Human approves the criteria set — move to COMPLETE."""
    project = await get_project(conn, project_id)
    if not project or project["state"] not in ("awaiting_review",):
        raise ValueError(f"Project {project_id} cannot be approved in state {project.get('state')}")
    await update_project_state(conn, project_id, "complete")
