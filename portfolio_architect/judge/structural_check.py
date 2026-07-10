"""Stage 1 verification: validate JSON schema of extracted criteria.

This stage does NOT call the LLM for cost efficiency — it validates structure
using the small judge LLM call only if there's an ambiguous structural issue.
Primary validation is pure Python.
"""

import json
import asyncpg
from uuid import UUID


def _validate_criteria_structure(criteria: list) -> tuple[bool, list[str]]:
    errors = []
    if not isinstance(criteria, list):
        return False, ["criteria must be a JSON array"]
    if len(criteria) == 0:
        return False, ["criteria array is empty — no criteria were extracted"]

    for i, c in enumerate(criteria):
        if not isinstance(c, dict):
            errors.append(f"criteria[{i}] is not an object")
            continue
        if c.get("type") not in ("inclusion", "exclusion"):
            errors.append(f'criteria[{i}].type must be "inclusion" or "exclusion", got: {c.get("type")}')
        if not c.get("statement", "").strip():
            errors.append(f"criteria[{i}].statement is empty")
        if not c.get("rationale", "").strip():
            errors.append(f"criteria[{i}].rationale is empty")
        source_ids = c.get("source_ids", [])
        if not isinstance(source_ids, list) or len(source_ids) == 0:
            errors.append(f"criteria[{i}].source_ids must be a non-empty array")

    return len(errors) == 0, errors


async def run(
    conn: asyncpg.Connection,
    project_id: UUID,
    run_id: UUID,
    criteria: list,
) -> dict:
    """Returns a verdict dict compatible with judge_verdicts schema."""
    passed, errors = _validate_criteria_structure(criteria)
    verdict = "pass" if passed else "fail"

    return {
        "verdict": verdict,
        "errors": errors,
        "criteria_count": len(criteria) if isinstance(criteria, list) else 0,
        "raw_llm_response": None,
        # Stage 1 doesn't score dimensions — those are Stage 2
        "faithfulness_score": None,
        "faithfulness_rationale": None,
        "problem_integrity_score": None,
        "problem_integrity_rationale": None,
        "citation_accuracy_score": None,
        "citation_accuracy_rationale": None,
        "uncertainty_score": None,
        "uncertainty_rationale": None,
        "overall_score": None,
        "death_spiral_reason": None,
    }
