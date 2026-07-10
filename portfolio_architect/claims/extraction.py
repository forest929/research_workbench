"""Claim extraction workstream: turn one document's raw text into atomic,
structured claims via an LLM call, with a cheap deterministic check that the
quoted evidence actually appears in the source text.

This is an offline batch job over the raw corpus (see scripts/extract_claims.py),
not part of the interactive per-query "Re-run Analysis" flow in agents/runner.py.
"""

import json
import re
import asyncpg
from uuid import UUID

from portfolio_architect.llm import client as llm
from portfolio_architect.prompts.claim_extraction import (
    CLAIM_EXTRACTION_SYSTEM,
    CLAIM_EXTRACTION_USER,
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _verify_quote(quote: str, raw_content: str) -> bool:
    if not quote:
        return False
    if quote in raw_content:
        return True
    return _normalize(quote) in _normalize(raw_content)


def _parse_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"research_question": None, "claims": []}
    if not isinstance(parsed, dict):
        return {"research_question": None, "claims": []}
    claims = parsed.get("claims", [])
    if not isinstance(claims, list):
        claims = []
    return {"research_question": parsed.get("research_question"), "claims": claims}


_VALID_VERDICTS = {"supports", "contradicts", "partially_supports", "inconclusive"}


async def run_one(
    conn: asyncpg.Connection,
    project_id: UUID,
    document: dict,
) -> dict:
    """Extract claims for a single document. Returns the parsed result
    (research_question, claims) with each claim annotated with quote_verified
    and raw_llm_response. Never raises — defensive parse failures yield an
    empty claim list rather than crashing the batch runner."""
    messages = [
        {"role": "system", "content": CLAIM_EXTRACTION_SYSTEM},
        {"role": "user", "content": CLAIM_EXTRACTION_USER.format(document_text=document["raw_content"])},
    ]

    try:
        raw = await llm.generate(
            messages,
            temperature=0.0,
            call_type="claim_extraction",
            conn=conn,
            project_id=project_id,
        )
    except Exception as e:
        return {"research_question": None, "claims": [], "error": str(e)}

    parsed = _parse_response(raw)
    valid_claims = []
    for c in parsed["claims"]:
        if not isinstance(c, dict) or not c.get("claim") or not c.get("verdict"):
            continue
        if c["verdict"] not in _VALID_VERDICTS:
            continue
        c["quote_verified"] = _verify_quote(c.get("evidence_quote", ""), document["raw_content"])
        c["raw_llm_response"] = raw
        valid_claims.append(c)

    return {"research_question": parsed["research_question"], "claims": valid_claims, "error": None}
