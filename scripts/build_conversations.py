#!/usr/bin/env python3
"""
Assemble "conversation" LoRA training examples from claim clusters produced
by portfolio_architect.claims.clustering — each cluster becomes one
question + a cited, synthesized answer showing what corroborates or
contradicts the underlying claim across papers.

Usage:
    python scripts/build_conversations.py --project-id <id> [--limit N] [--concurrency N]
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.migrations import run_migrations
from portfolio_architect.db.claim_clusters import (
    get_clusters_for_project,
    get_cluster_members,
    set_conversation,
)
from portfolio_architect.db.query_log import get_cost_summary
from portfolio_architect.claims.conversation import build_conversation

DEFAULT_CONCURRENCY = 10


_CITATION_RE = re.compile(r"(pmid:\d+|nct:NCT\d+)")


def _citations_valid(answer: str, members: list[dict]) -> bool:
    valid_ids = {m["source_id"] for m in members}
    cited = set(_CITATION_RE.findall(answer))
    return bool(cited) and cited.issubset(valid_ids)


async def _process_cluster(pool, project_id: UUID, cluster: dict, sem: asyncio.Semaphore, counters: dict) -> None:
    async with sem:
        async with pool.acquire() as conn:
            members = await get_cluster_members(conn, cluster["id"])
            question, answer = await build_conversation(conn, project_id, cluster, members)
            if answer:
                valid = _citations_valid(answer, members)
                await set_conversation(conn, cluster["id"], question, answer, valid)
                counters["done"] += 1
                if not valid:
                    counters["bad_citations"] += 1
            else:
                counters["failed"] += 1
            total = counters["done"] + counters["failed"]
            if total % 10 == 0:
                print(f"  {total}/{counters['total']} clusters processed...", end="\r")


async def main(args) -> None:
    print("=" * 65)
    print("  Conversation Assembly — AI Portfolio Architect")
    print("=" * 65)

    project_id = UUID(args.project_id)
    pool = await create_pool()
    await run_migrations(pool)

    async with pool.acquire() as conn:
        clusters = await get_clusters_for_project(conn, project_id)

    pending = [
        c for c in clusters
        if not c.get("answer") and (c.get("member_count") or 0) >= args.min_members
    ]
    if args.limit is not None:
        pending = pending[: args.limit]

    if not pending:
        print("\nNo clusters pending conversation synthesis. Nothing to do.")
        await close_pool()
        return

    print(f"\nSynthesizing conversations for {len(pending)} cluster(s) "
          f"(concurrency={args.concurrency})...\n")

    sem = asyncio.Semaphore(args.concurrency)
    counters = {"done": 0, "failed": 0, "bad_citations": 0, "total": len(pending)}

    await asyncio.gather(*[
        _process_cluster(pool, project_id, c, sem, counters) for c in pending
    ])

    print(f"\n\nDone. {counters['done']} conversations built, {counters['failed']} failed, "
          f"{counters['bad_citations']} with unverifiable citations.")

    async with pool.acquire() as conn:
        cost = await get_cost_summary(conn, project_id)
    print(f"\nCost summary (cumulative, this project, conversation_synthesis calls included):")
    print(f"  LLM calls   : {cost.get('calls', 0)}")
    print(f"  Total tokens: {cost.get('total_tokens', 0)}")

    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assemble conversation LoRA examples from claim clusters")
    parser.add_argument("--project-id", required=True, help="Project ID to process")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap how many clusters this run processes")
    parser.add_argument("--min-members", type=int, default=1, metavar="N",
                        help="Only synthesize clusters with >= N members "
                             "(use 2 to skip singletons and bound cost)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, metavar="N",
                        help=f"Max concurrent LLM calls (default: {DEFAULT_CONCURRENCY})")
    args = parser.parse_args()

    asyncio.run(main(args))
