"""Run all three workstreams concurrently and persist their results.

Each workstream acquires its own connection from the pool — asyncpg connections
are not safe for concurrent use by multiple coroutines simultaneously.
"""

import asyncio
import asyncpg
from uuid import UUID

from portfolio_architect.db.workstream_runs import insert_run, update_run_status
from portfolio_architect.db.criteria import insert_criteria, get_gold_labels
from portfolio_architect.agents.workstreams import (
    parameter_extraction,
    literature_synthesis,
    cluster_selection,
)


async def _run_workstream(
    pool: asyncpg.Pool,
    project_id: UUID,
    run_id: UUID,
    workstream: str,
    scope_statement: str,
    gold_values: list,
) -> tuple[str, list | str | None, str | None]:
    """Execute one workstream with its own dedicated DB connection."""
    async with pool.acquire() as conn:
        await update_run_status(conn, run_id, workstream, "running")
        try:
            if workstream == "parameter_extraction":
                result = await parameter_extraction.run(conn, project_id, scope_statement, gold_values)
            elif workstream == "literature_synthesis":
                result = await literature_synthesis.run(conn, project_id, scope_statement)
            else:
                result = await cluster_selection.run(conn, project_id, scope_statement)

            await update_run_status(
                conn, run_id, workstream, "complete",
                result={"data": result if isinstance(result, list) else str(result)},
            )
            return workstream, result, None
        except Exception as e:
            err = str(e)
            await update_run_status(conn, run_id, workstream, "failed", error_msg=err)
            return workstream, None, err


async def run_all(
    pool: asyncpg.Pool,
    project_id: UUID,
    run_id: UUID,
    scope_statement: str,
) -> dict:
    """
    Run the three workstreams concurrently, each with its own DB connection.
    Returns dict with keys: criteria, synthesis, prototypes, errors.
    """
    async with pool.acquire() as conn:
        gold_values = await get_gold_labels(conn, project_id)
        for ws in ["parameter_extraction", "literature_synthesis", "cluster_selection"]:
            await insert_run(conn, project_id, run_id, ws)

    results = await asyncio.gather(
        _run_workstream(pool, project_id, run_id, "parameter_extraction", scope_statement, gold_values),
        _run_workstream(pool, project_id, run_id, "literature_synthesis", scope_statement, gold_values),
        _run_workstream(pool, project_id, run_id, "cluster_selection", scope_statement, gold_values),
    )

    output: dict = {"criteria": [], "synthesis": "", "prototypes": [], "errors": {}}
    for ws_name, result, err in results:
        if err:
            output["errors"][ws_name] = err
        elif ws_name == "parameter_extraction":
            output["criteria"] = result or []
        elif ws_name == "literature_synthesis":
            output["synthesis"] = result or ""
        elif ws_name == "cluster_selection":
            output["prototypes"] = result or []

    if output["criteria"]:
        async with pool.acquire() as conn:
            await insert_criteria(conn, project_id, run_id, output["criteria"])

    return output
