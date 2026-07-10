#!/usr/bin/env python3
"""
Extract atomic, structured claims from ingested documents via an LLM
"expert systematic reviewer" prompt.

This is Phase 2 of the LoRA training-data pipeline: it turns raw document
text (from scripts/ingest_*.py) into population/intervention/comparator/
outcome claims with a support/contradict/partially_supports/inconclusive
verdict, a verbatim evidence quote, effect size, statistical significance,
and a confidence score. Claim clustering across papers and "conversation"
assembly for fine-tuning are later, separate steps — not built here.

Usage:
    python scripts/extract_claims.py --project-id <id> [--limit N] [--concurrency N]

Options:
    --project-id ID   Project to process (required)
    --limit N         Cap how many new (unprocessed) documents this run processes
    --concurrency N   Max concurrent LLM calls (default: 10)
"""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.migrations import run_migrations
from portfolio_architect.db.claims import (
    get_unprocessed_documents,
    insert_claims,
    mark_document_processed,
    get_verdict_summary,
)
from portfolio_architect.db.query_log import get_cost_summary
from portfolio_architect.claims.extraction import run_one

DEFAULT_CONCURRENCY = 10


async def _process_document(pool, project_id: UUID, document: dict, sem: asyncio.Semaphore, counters: dict) -> None:
    async with sem:
        async with pool.acquire() as conn:
            result = await run_one(conn, project_id, document)
            if result["error"]:
                counters["errors"] += 1
                print(f"  ERROR doc {document['id']}: {result['error'][:100]}")
                return
            if result["claims"]:
                await insert_claims(conn, project_id, document["id"], result["claims"])
            await mark_document_processed(conn, document["id"], result["research_question"])
            counters["processed"] += 1
            counters["claims"] += len(result["claims"])
            done = counters["processed"] + counters["errors"]
            if done % 10 == 0:
                print(f"  {done}/{counters['total']} documents processed "
                      f"({counters['claims']} claims so far)...", end="\r")


async def main(args) -> None:
    print("=" * 65)
    print("  Claim Extraction — AI Portfolio Architect")
    print("=" * 65)

    project_id = UUID(args.project_id)

    pool = await create_pool()
    await run_migrations(pool)

    async with pool.acquire() as conn:
        documents = await get_unprocessed_documents(conn, project_id, limit=args.limit)

    if not documents:
        print("\nNo unprocessed documents found for this project (already fully extracted, "
              "or --limit reached 0 remaining). Nothing to do.")
        await close_pool()
        return

    print(f"\nProcessing {len(documents)} unprocessed document(s) "
          f"(concurrency={args.concurrency})...\n")

    sem = asyncio.Semaphore(args.concurrency)
    counters = {"processed": 0, "errors": 0, "claims": 0, "total": len(documents)}

    await asyncio.gather(*[
        _process_document(pool, project_id, doc, sem, counters) for doc in documents
    ])

    print(f"\n\nDone. Processed {counters['processed']} documents "
          f"({counters['errors']} errors), extracted {counters['claims']} claims.")

    async with pool.acquire() as conn:
        verdicts = await get_verdict_summary(conn, project_id)
        cost = await get_cost_summary(conn, project_id)

    print("\nVerdict breakdown:")
    total_claims = sum(v["count"] for v in verdicts.values()) or 1
    for verdict, stats in sorted(verdicts.items(), key=lambda kv: -kv[1]["count"]):
        verified_rate = (stats["verified"] or 0) / stats["count"] * 100 if stats["count"] else 0
        print(f"  {verdict:20s} {stats['count']:5d}  (quote_verified: {verified_rate:.0f}%)")

    print(f"\nCost summary (this project, cumulative across all claim_extraction calls):")
    print(f"  LLM calls   : {cost.get('calls', 0)}")
    print(f"  Total tokens: {cost.get('total_tokens', 0)}")

    print(f"\nRemaining unprocessed documents can be picked up by re-running this script "
          f"(claims_extracted flag makes this resumable).")

    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract structured claims from ingested documents")
    parser.add_argument("--project-id", required=True, help="Project ID to process")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap how many new documents this run processes")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, metavar="N",
                        help=f"Max concurrent LLM calls (default: {DEFAULT_CONCURRENCY})")
    args = parser.parse_args()

    asyncio.run(main(args))
