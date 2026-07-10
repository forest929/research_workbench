"""FunSearch-inspired evolutionary loop for labeling functions.

Generates mutation candidates via LLM, exec()s them, scores against gold labels,
and returns the best performing variant.
"""

import json
import asyncpg
from uuid import UUID

from portfolio_architect.llm import client as llm
from portfolio_architect.prompts.evolutionary import (
    MUTATION_SYSTEM,
    MUTATION_USER,
    DEFAULT_LABELING_FUNCTION,
)
from portfolio_architect.config import get_settings

_settings = get_settings()


def _exec_fn(code: str):  # returns callable or None
    """Safely exec a labeling function string. Returns the callable or None."""
    namespace: dict = {}
    try:
        exec(compile(code, "<mutation>", "exec"), namespace)  # noqa: S102
        fn = namespace.get("label_text")
        if callable(fn):
            return fn
    except Exception:
        pass
    return None


def _score_fn(fn, gold_labels: list[dict], criteria: list[dict]) -> float:
    """Score a labeling function against gold labels. Returns accuracy 0.0–1.0."""
    if not gold_labels:
        return 0.0
    correct = 0
    for gl in gold_labels:
        if not gl.get("is_hard_constraint"):
            continue
        try:
            predicted = fn(gl["text_sample"], criteria)
            if predicted == gl["label"]:
                correct += 1
        except Exception:
            pass
    return correct / len(gold_labels) if gold_labels else 0.0


def _find_failures(fn, gold_labels: list[dict], criteria: list[dict]) -> list[dict]:
    failures = []
    for gl in gold_labels:
        try:
            predicted = fn(gl["text_sample"], criteria)
            if predicted != gl["label"]:
                failures.append({
                    "text_sample": gl["text_sample"],
                    "expected": gl["label"],
                    "predicted": predicted,
                    "note": gl.get("note", ""),
                })
        except Exception as e:
            failures.append({
                "text_sample": gl["text_sample"],
                "expected": gl["label"],
                "predicted": "ERROR",
                "error": str(e),
            })
    return failures


async def evolve(
    conn: asyncpg.Connection,
    project_id: UUID,
    gold_labels: list[dict],
    criteria: list[dict],
    current_fn_code: str | None = None,
    n: int | None = None,
) -> dict:
    """
    Run one evolutionary cycle.
    Returns: {best_code, best_score, mutations, baseline_score}
    """
    n = n or _settings.evolutionary_n_mutations
    current_code = current_fn_code or DEFAULT_LABELING_FUNCTION
    current_fn = _exec_fn(current_code)
    baseline_score = _score_fn(current_fn, gold_labels, criteria) if current_fn else 0.0
    failures = _find_failures(current_fn, gold_labels, criteria) if current_fn else []

    if not failures:
        return {
            "best_code": current_code,
            "best_score": baseline_score,
            "mutations": [],
            "baseline_score": baseline_score,
            "note": "No failures to fix — function already optimal on gold labels.",
        }

    messages = [
        {"role": "system", "content": MUTATION_SYSTEM.format(n=n)},
        {"role": "user", "content": MUTATION_USER.format(
            gold_labels_json=json.dumps(gold_labels[:20], indent=2),
            current_fn_code=current_code,
            failure_cases_json=json.dumps(failures[:10], indent=2),
            n=n,
        )},
    ]

    try:
        raw = await llm.generate(
            messages,
            temperature=0.8,
            call_type="mutation",
            conn=conn,
            project_id=project_id,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        parsed = json.loads(raw)
        mutations = parsed.get("mutations", [])
    except Exception:
        mutations = []

    best_code = current_code
    best_score = baseline_score
    scored_mutations = []
    for m in mutations:
        code = m.get("code", "")
        fn = _exec_fn(code)
        if fn is None:
            m["score"] = 0.0
            m["valid_python"] = False
        else:
            score = _score_fn(fn, gold_labels, criteria)
            m["score"] = score
            m["valid_python"] = True
            if score > best_score:
                best_score = score
                best_code = code
        scored_mutations.append(m)

    return {
        "best_code": best_code,
        "best_score": best_score,
        "baseline_score": baseline_score,
        "mutations": scored_mutations,
    }
