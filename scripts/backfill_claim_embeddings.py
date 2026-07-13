#!/usr/bin/env python3
"""
Backfill embeddings for claims.claim_text — needed for Phase 3 clustering
(grouping claims about the same underlying hypothesis across papers).

Resumable: only processes claims where claim_embedding IS NULL.

Usage:
    python scripts/backfill_claim_embeddings.py --project-id <id>
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
from portfolio_architect.embedding import codec
from portfolio_architect.embedding.client import embed_batch

BATCH_SIZE = 64


async def main(args) -> None:
    project_id = UUID(args.project_id)
    pool = await create_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, claim_text FROM claims WHERE project_id = ? AND claim_embedding IS NULL",
            str(project_id),
        )

    if not rows:
        print("No unembedded claims found. Nothing to do.")
        await close_pool()
        return

    print(f"Embedding {len(rows)} claims in batches of {BATCH_SIZE}...")
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        texts = [r["claim_text"] for r in batch]
        embeddings = await embed_batch(texts)

        async with pool.acquire() as conn:
            for row, emb in zip(batch, embeddings):
                await conn.execute(
                    "UPDATE claims SET claim_embedding = ? WHERE id = ?",
                    codec.encode(emb), row["id"],
                )

        total += len(batch)
        print(f"  Embedded {total}/{len(rows)}...", end="\r")

    print(f"\nDone. Embedded {total} claims.")
    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill embeddings for extracted claims")
    parser.add_argument("--project-id", required=True, help="Project ID to process")
    args = parser.parse_args()

    asyncio.run(main(args))
