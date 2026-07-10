"""Workstream: extract inclusion/exclusion criteria from retrieved chunks."""

import json
import asyncpg
from uuid import UUID

from portfolio_architect.retrieval.hybrid_search import search_chunks, chunks_to_xml
from portfolio_architect.llm import client as llm
from portfolio_architect.prompts.generation import (
    CRITERION_EXTRACTION_SYSTEM,
    CRITERION_EXTRACTION_USER,
)


async def run(
    conn: asyncpg.Connection,
    project_id: UUID,
    scope_statement: str,
    gold_values: list[dict],
) -> list[dict]:
    chunks = await search_chunks(conn, scope_statement, project_id)
    chunks_xml = chunks_to_xml(chunks)

    gold_json = json.dumps(
        [{"type": gv["label"], "statement": gv["text_sample"], "note": gv.get("note", "")}
         for gv in gold_values if gv.get("is_hard_constraint")],
        indent=2,
    )

    messages = [
        {"role": "system", "content": CRITERION_EXTRACTION_SYSTEM},
        {"role": "user", "content": CRITERION_EXTRACTION_USER.format(
            scope_statement=scope_statement,
            gold_values_json=gold_json,
            chunks_xml=chunks_xml,
        )},
    ]

    raw = await llm.generate(
        messages,
        temperature=0.0,
        call_type="extraction",
        conn=conn,
        project_id=project_id,
    )

    # Defensive JSON parse
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw)
        criteria = parsed.get("criteria", [])
    except (json.JSONDecodeError, KeyError):
        criteria = []

    # Attach source metadata from retrieved chunks
    source_map = {c["source_id"]: c for c in chunks}
    for criterion in criteria:
        # Validate source_ids exist in our retrieved set (or are GOLD_VALUE)
        valid_sources = [
            sid for sid in criterion.get("source_ids", [])
            if sid in source_map or sid == "GOLD_VALUE"
        ]
        criterion["source_ids"] = valid_sources or ["unknown"]

    return criteria
