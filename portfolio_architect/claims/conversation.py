"""Conversation assembly: turn a claim cluster (multiple papers' claims about
the same underlying hypothesis) into a question + a cited, synthesized
answer — the actual LoRA training example.
"""

import re
from collections import Counter

import asyncpg

from portfolio_architect.llm import client as llm
from portfolio_architect.prompts.conversation_synthesis import (
    CONVERSATION_SYNTHESIS_SYSTEM,
    CONVERSATION_SYNTHESIS_USER,
    build_question,
    claims_to_xml,
)

# Cap how many member claims go into a synthesis prompt. Large generic clusters
# (e.g. "chemotherapy", 170+ members) would otherwise produce a bloated,
# unfocused prompt/answer and burn tokens. We keep the strongest evidence while
# preserving any disagreement (contradicts/partially_supports are always kept).
MAX_SYNTH_MEMBERS = 12

_DISSENT = ("contradicts", "partially_supports")

# Markers that a field was not actually reported (so it carries no evidence).
_NULL_MARKERS = ("null", "none", "nr", "n/a", "na", "not applicable")
_NOT_REPORTED = ("not reported", "not explicitly", "not stated", "not specified", "unclear")
# p-value like "p < 0.001", "P = 0.018", "p ≤ .05"
_P_VALUE_RE = re.compile(r"p\s*([<=≤])\s*(0?\.\d+|\d+(?:\.\d+)?)", re.IGNORECASE)


def _is_absent(text) -> bool:
    if not text:
        return True
    t = str(text).strip().lower()
    return t in _NULL_MARKERS or any(m in t for m in _NOT_REPORTED)


def _significance_level(text) -> str:
    """Classify a statistical_significance field into an ordinal evidence tier.
    Prefers an actual reported p-value; falls back to textual cues. This is the
    load-bearing calibration signal — a reported, significant p-value means the
    claim rests on real inferential statistics, not the model's self-assessment."""
    if _is_absent(text):
        return "none"
    t = str(text).strip().lower()
    ps = []
    for _op, val in _P_VALUE_RE.findall(t):
        try:
            ps.append(float(val))
        except ValueError:
            pass
    if ps:
        return "significant" if min(ps) < 0.05 else "reported"
    if "non-significant" in t or "not significant" in t or "nonsignificant" in t:
        return "reported"
    if "significant" in t:
        return "significant_text"  # asserted significant, no number
    return "none"


def _has_effect_size(text) -> bool:
    """A quantified effect (contains a number) that was actually reported."""
    if _is_absent(text):
        return False
    return bool(re.search(r"\d", str(text)))


def _has_confidence_interval(text) -> bool:
    if not text:
        return False
    t = str(text).lower()
    return "ci" in t or "95%" in t or "confidence interval" in t


_SIGNIFICANCE_WEIGHT = {"significant": 3.0, "significant_text": 2.0, "reported": 1.0, "none": 0.0}


def evidence_strength(m: dict) -> float:
    """A calibrated ranking score built from *checkable* attributes rather than
    the LLM's self-reported `confidence` (which is nearly constant — ~91% of
    claims sit at 0.8–0.9, so it barely discriminates). Rewards, in order of
    weight: a reported significant p-value, a verified verbatim quote, a
    quantified effect size (bonus if a confidence interval is reported). The raw
    LLM confidence is kept only as a light tiebreaker."""
    score = 0.0
    score += _SIGNIFICANCE_WEIGHT[_significance_level(m.get("statistical_significance"))]
    if m.get("quote_verified"):
        score += 2.0
    if _has_effect_size(m.get("effect_size")):
        score += 1.5
        if _has_confidence_interval(m.get("effect_size")):
            score += 1.0
    score += 0.5 * (m.get("confidence") or 0.0)
    return round(score, 3)


def _mode(values: list[str]) -> str:
    values = [v for v in values if v]
    if not values:
        return "this population"
    return Counter(values).most_common(1)[0][0]


def rank_members(members: list[dict]) -> list[dict]:
    """Order members dissent-first (so disagreement is never buried), then by the
    calibrated evidence_strength score within each group. Annotates each member
    with `evidence_strength` for transparency in the UI."""
    for m in members:
        m["evidence_strength"] = evidence_strength(m)
    dissent = [m for m in members if m.get("verdict") in _DISSENT]
    agree = [m for m in members if m.get("verdict") not in _DISSENT]
    dissent.sort(key=lambda m: m["evidence_strength"], reverse=True)
    agree.sort(key=lambda m: m["evidence_strength"], reverse=True)
    return dissent + agree


def _select_members(members: list[dict], limit: int = MAX_SYNTH_MEMBERS) -> list[dict]:
    """Top `limit` members by the calibrated ranking (dissent-first, then
    evidence strength). Small clusters are returned whole, still ranked."""
    return rank_members(members)[:limit]


async def build_conversation(
    conn: asyncpg.Connection,
    project_id,
    cluster: dict,
    members: list[dict],
) -> tuple[str, str]:
    """Returns (question, answer) for a cluster. Never raises — an LLM
    failure yields an empty answer string rather than crashing the batch."""
    population = _mode([m.get("population") for m in members])
    outcome = _mode([m.get("outcome") for m in members])
    question = build_question(cluster["intervention_key"], population, outcome)

    selected = _select_members(members)
    messages = [
        {"role": "system", "content": CONVERSATION_SYNTHESIS_SYSTEM},
        {"role": "user", "content": CONVERSATION_SYNTHESIS_USER.format(
            question=question,
            claims_xml=claims_to_xml(selected),
        )},
    ]

    try:
        answer = await llm.generate(
            messages,
            temperature=0.2,
            call_type="conversation_synthesis",
            conn=conn,
            project_id=project_id,
        )
    except Exception:
        return question, ""

    return question, answer.strip()


async def build_conversation_compare(
    conn: asyncpg.Connection,
    project_id,
    intervention_key: str,
    members: list[dict],
) -> dict:
    """Synthesize the same cited answer with BOTH the base model and the
    self-hosted fine-tuned adapter, for side-by-side comparison in the
    workbench. The fine-tuned call is best-effort: if the adapter endpoint is
    unconfigured or unreachable (GPU VM down), `finetuned_answer` is None and
    `finetuned_error` explains why — never raises on that account.

    `members` must carry `source_id` (join documents) so citations reference
    real corpus records."""
    population = _mode([m.get("population") for m in members])
    outcome = _mode([m.get("outcome") for m in members])
    question = build_question(intervention_key, population, outcome)

    messages = [
        {"role": "system", "content": CONVERSATION_SYNTHESIS_SYSTEM},
        {"role": "user", "content": CONVERSATION_SYNTHESIS_USER.format(
            question=question,
            claims_xml=claims_to_xml(members),
        )},
    ]

    try:
        base_answer = (await llm.generate(
            messages, temperature=0.2, call_type="conversation_synthesis_base",
            conn=conn, project_id=project_id,
        )).strip()
        base_error = None
    except Exception as e:
        base_answer, base_error = None, str(e)

    finetuned_answer, finetuned_error = None, None
    try:
        finetuned_answer = (await llm.generate_finetuned(
            messages, temperature=0.2, call_type="conversation_synthesis_finetuned",
            conn=conn, project_id=project_id,
        )).strip()
    except Exception as e:
        finetuned_error = str(e)

    return {
        "question": question,
        "base_answer": base_answer,
        "base_error": base_error,
        "finetuned_answer": finetuned_answer,
        "finetuned_error": finetuned_error,
    }
