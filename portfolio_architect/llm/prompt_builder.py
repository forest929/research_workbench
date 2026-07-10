"""Dynamic few-shot prompt builder for document screening.

Assembles: system prompt + inclusion/exclusion criteria + validated similar examples
+ project-specific reviewer preferences + current abstract.

No LLM fine-tuning — the prompt itself carries all the project-specific learning.
"""

import json

REASON_CODES = [
    "REVIEW_ARTICLE",
    "SIMULATION_ONLY",
    "GREENHOUSE_ONLY",
    "WRONG_POPULATION",
    "WRONG_INTERVENTION",
    "WRONG_OUTCOME",
    "PROTOCOL_PAPER",
    "DUPLICATE",
    "LANGUAGE",
    "DATE",
    "NO_ABSTRACT",
    "OTHER",
]

_SCREENING_SYSTEM = """You are a systematic review screening assistant. \
Your task is to predict whether a document should be INCLUDED or EXCLUDED \
from the review based on the protocol criteria and validated examples.

Output strict JSON only — no prose outside the JSON object:
{
  "label": "include" | "exclude",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<one or two sentences citing which criterion applies>",
  "reason_code": "<one of the reason codes below, or null if include>"
}

Reason codes (use when excluding):
REVIEW_ARTICLE, SIMULATION_ONLY, GREENHOUSE_ONLY, WRONG_POPULATION,
WRONG_INTERVENTION, WRONG_OUTCOME, PROTOCOL_PAPER, DUPLICATE, LANGUAGE, DATE,
NO_ABSTRACT, OTHER

Rules:
1. Base every decision on the criteria and examples — do not add new criteria.
2. confidence must reflect genuine uncertainty (never default to 1.0).
3. When in doubt between include and exclude, set confidence ≤ 0.70 to flag for review."""


def _format_criteria(criteria: list[dict]) -> str:
    inclusion = [c for c in criteria if c.get("criterion_type") == "inclusion" or c.get("type") == "inclusion"]
    exclusion = [c for c in criteria if c.get("criterion_type") == "exclusion" or c.get("type") == "exclusion"]
    parts = []
    if inclusion:
        parts.append("INCLUSION CRITERIA:")
        for c in inclusion:
            parts.append(f"  + {c.get('statement', '')}")
    if exclusion:
        parts.append("EXCLUSION CRITERIA:")
        for c in exclusion:
            parts.append(f"  - {c.get('statement', '')}")
    return "\n".join(parts) if parts else "No criteria defined yet — use best judgment."


def _format_examples(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = ["VALIDATED EXAMPLES FROM THIS PROJECT:"]
    for i, ex in enumerate(examples, 1):
        label = ex.get("human_label", "?").upper()
        reason = ex.get("human_reason") or ex.get("reason_code") or ""
        preview = ex.get("preview", "")[:300]
        lines.append(f"\nExample {i} — {label}")
        if reason:
            lines.append(f"  Reason: {reason}")
        lines.append(f"  Abstract: {preview}")
    return "\n".join(lines)


def build_messages(
    abstract: str,
    criteria: list[dict],
    similar_examples: list[dict],
    project_guidance: str = "",
) -> list[dict]:
    """Return the messages list to send to the LLM for screening prediction."""
    criteria_block = _format_criteria(criteria)
    examples_block = _format_examples(similar_examples)

    user_parts = [criteria_block]
    if project_guidance:
        user_parts.append(f"\n{project_guidance}")
    if examples_block:
        user_parts.append(f"\n{examples_block}")
    user_parts.append(f"\nDOCUMENT TO SCREEN:\n{abstract[:1500]}")
    user_parts.append("\nReturn only the JSON object.")

    return [
        {"role": "system", "content": _SCREENING_SYSTEM},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def parse_prediction(raw: str) -> dict:
    """Defensively parse LLM screening output; return a safe fallback on failure."""
    raw = raw.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw)
        label = str(parsed.get("label", "")).lower()
        if label not in ("include", "exclude"):
            label = "exclude"
        confidence = float(parsed.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        return {
            "label": label,
            "confidence": confidence,
            "reasoning": str(parsed.get("reasoning", "")),
            "reason_code": parsed.get("reason_code"),
            "parse_error": False,
        }
    except Exception as e:
        return {
            "label": "exclude",
            "confidence": 0.5,
            "reasoning": f"[Parse error: {e}] Raw: {raw[:200]}",
            "reason_code": None,
            "parse_error": True,
        }
