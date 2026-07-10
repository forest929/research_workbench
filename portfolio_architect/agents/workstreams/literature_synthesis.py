"""Workstream: synthesise retrieved literature into a cited narrative."""

import asyncpg
from uuid import UUID

from portfolio_architect.retrieval.hybrid_search import search_chunks, chunks_to_xml
from portfolio_architect.llm import client as llm
from portfolio_architect.prompts.generation import SYNTHESIS_SYSTEM, SYNTHESIS_USER


async def run(
    conn: asyncpg.Connection,
    project_id: UUID,
    scope_statement: str,
) -> str:
    chunks = await search_chunks(conn, scope_statement, project_id)
    if not chunks:
        return "No source documents found. Please ingest relevant documents before running synthesis."

    chunks_xml = chunks_to_xml(chunks)
    messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM},
        {"role": "user", "content": SYNTHESIS_USER.format(
            scope_statement=scope_statement,
            chunks_xml=chunks_xml,
        )},
    ]

    return await llm.generate(
        messages,
        temperature=0.2,
        call_type="synthesis",
        conn=conn,
        project_id=project_id,
    )
