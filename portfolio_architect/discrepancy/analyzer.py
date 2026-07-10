"""Cross-team semantic discrepancy analyzer.

Identifies friction points where two competing scope definitions conflict in
wording, evidence interpretation, or logical boundary.
"""

import json
import math
import asyncpg
from uuid import UUID, uuid4

from portfolio_architect.llm import client as llm
from portfolio_architect.embedding.client import embed_text
from portfolio_architect.prompts.evolutionary import DISCREPANCY_SYSTEM, DISCREPANCY_USER


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag = lambda v: math.sqrt(sum(x * x for x in v))  # noqa: E731
    ma, mb = mag(a), mag(b)
    return dot / (ma * mb) if ma > 0 and mb > 0 else 0.0


async def analyze(
    conn: asyncpg.Connection,
    project_id: UUID,
    definition_a: str,
    definition_b: str,
    label_a: str = "Team A",
    label_b: str = "Team B",
) -> dict:
    run_id = uuid4()

    # Semantic overlap via embedding cosine similarity
    try:
        emb_a, emb_b = await asyncio_gather_embeddings(definition_a, definition_b)
        semantic_overlap = _cosine_similarity(emb_a, emb_b)
    except Exception:
        semantic_overlap = 0.0

    messages = [
        {"role": "system", "content": DISCREPANCY_SYSTEM},
        {"role": "user", "content": DISCREPANCY_USER.format(
            label_a=label_a,
            definition_a=definition_a,
            label_b=label_b,
            definition_b=definition_b,
        )},
    ]

    try:
        raw = await llm.generate(
            messages,
            temperature=0.1,
            call_type="discrepancy",
            conn=conn,
            project_id=project_id,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        parsed = json.loads(raw)
        friction_points = parsed.get("friction_points", [])
        recommendation = parsed.get("recommendation", "")
    except Exception as e:
        friction_points = []
        recommendation = f"Analysis failed: {e}"

    return {
        "project_id": project_id,
        "run_id": run_id,
        "friction_points": friction_points,
        "semantic_overlap": round(semantic_overlap, 4),
        "recommendation": recommendation,
    }


async def asyncio_gather_embeddings(text_a: str, text_b: str) -> tuple[list[float], list[float]]:
    import asyncio
    embs = await asyncio.gather(embed_text(text_a), embed_text(text_b))
    return embs[0], embs[1]
