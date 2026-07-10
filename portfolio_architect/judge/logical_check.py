"""Stage 2 verification: LLM-as-judge for faithfulness, integrity, citations, uncertainty.

Fully independent context from the generation workstream — separate client instance,
separate system prompt, no shared state.
"""

import json
import asyncpg
from uuid import UUID

from portfolio_architect.llm import client as llm
from portfolio_architect.prompts.judge import LOGICAL_JUDGE_SYSTEM, LOGICAL_JUDGE_USER


def _parse_judge_response(raw: str) -> dict:
    """Defensive parse: any failure returns verdict='fail', not a crash."""
    raw = raw.strip()
    # Strip markdown fencing if present
    if raw.startswith("```"):
        parts = raw.split("```")
        for part in parts[1:]:
            cleaned = part.lstrip("json").strip()
            if cleaned.startswith("{"):
                raw = cleaned
                break

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "verdict": "fail",
            "faithfulness": {"score": 1, "rationale": "Judge output was not valid JSON"},
            "problem_statement_integrity": {"score": 1, "rationale": "Parse failed"},
            "citation_accuracy": {"score": 1, "rationale": "Parse failed"},
            "uncertainty_transparency": {"score": 1, "rationale": "Parse failed"},
            "overall": 1,
            "death_spiral_reason": None,
        }

    # Ensure required keys exist with safe defaults
    for dim in ("faithfulness", "problem_statement_integrity", "citation_accuracy", "uncertainty_transparency"):
        if dim not in parsed or not isinstance(parsed[dim], dict):
            parsed[dim] = {"score": 1, "rationale": "Missing from judge output"}

    if "verdict" not in parsed or parsed["verdict"] not in ("pass", "fail", "death_spiral"):
        # Infer verdict from scores
        scores = [parsed[d].get("score", 1) for d in
                  ("faithfulness", "problem_statement_integrity", "citation_accuracy", "uncertainty_transparency")]
        if any(s < 3 for s in scores):
            parsed["verdict"] = "fail"
        else:
            parsed["verdict"] = "pass"

    if "overall" not in parsed:
        dims = ("faithfulness", "problem_statement_integrity", "citation_accuracy", "uncertainty_transparency")
        scores = [parsed[d].get("score", 1) for d in dims]
        parsed["overall"] = round(sum(scores) / len(scores))

    parsed.setdefault("death_spiral_reason", None)
    return parsed


async def run(
    conn: asyncpg.Connection,
    project_id: UUID,
    run_id: UUID,
    scope_statement: str,
    criteria: list,
    chunks_xml: str,
) -> dict:
    criteria_json = json.dumps(criteria, indent=2)
    messages = [
        {"role": "system", "content": LOGICAL_JUDGE_SYSTEM},
        {"role": "user", "content": LOGICAL_JUDGE_USER.format(
            scope_statement=scope_statement,
            chunks_xml=chunks_xml,
            criteria_json=criteria_json,
        )},
    ]

    try:
        raw = await llm.judge(
            messages,
            call_type="judge_logical",
            conn=conn,
            project_id=project_id,
        )
    except Exception as e:
        raw = ""
        parsed = {
            "verdict": "fail",
            "faithfulness": {"score": 1, "rationale": f"Judge call failed: {e}"},
            "problem_statement_integrity": {"score": 1, "rationale": "LLM error"},
            "citation_accuracy": {"score": 1, "rationale": "LLM error"},
            "uncertainty_transparency": {"score": 1, "rationale": "LLM error"},
            "overall": 1,
            "death_spiral_reason": None,
        }
    else:
        parsed = _parse_judge_response(raw)

    p = parsed
    f = p.get("faithfulness", {})
    pi = p.get("problem_statement_integrity", {})
    ca = p.get("citation_accuracy", {})
    ut = p.get("uncertainty_transparency", {})

    return {
        "verdict": p["verdict"],
        "faithfulness_score": f.get("score"),
        "faithfulness_rationale": f.get("rationale"),
        "problem_integrity_score": pi.get("score"),
        "problem_integrity_rationale": pi.get("rationale"),
        "citation_accuracy_score": ca.get("score"),
        "citation_accuracy_rationale": ca.get("rationale"),
        "uncertainty_score": ut.get("score"),
        "uncertainty_rationale": ut.get("rationale"),
        "overall_score": p.get("overall"),
        "death_spiral_reason": p.get("death_spiral_reason"),
        "raw_llm_response": raw if raw else None,
    }
