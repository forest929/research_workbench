#!/usr/bin/env python3
"""
Rebuild claim clusters for a project from scratch — verified, PubMed-only.

Clustering had no script before (it was run ad-hoc); this makes it
reproducible and enforces the workbench's data contract: only quote-verified,
paper-sourced claims form clusters, so every piece of evidence shown has a
source URL and a verbatim, verified quote. Trial (NCT) claims are excluded.

Pure compute, no LLM calls — safe to re-run. Run build_conversations.py
afterwards to (re)synthesize the cited answers for the new clusters.

Usage:
    python scripts/rebuild_clusters.py --project-id <id>
      [--threshold 0.82] [--include-trials] [--all-claims]
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
from portfolio_architect.db.claim_clusters import reset_project_clusters
from portfolio_architect.claims.clustering import (
    cluster_project_claims,
    add_singleton_clusters,
    SIMILARITY_THRESHOLD,
)


async def main(args) -> None:
    project_id = UUID(args.project_id)
    verified_only = not args.all_claims
    exclude_trials = not args.include_trials

    pool = await create_pool()
    await run_migrations(pool)
    try:
        async with pool.acquire() as conn:
            print(f"Resetting clusters for {project_id} ...")
            await reset_project_clusters(conn, project_id)

            print(
                f"Clustering (threshold={args.threshold}, "
                f"verified_only={verified_only}, exclude_trials={exclude_trials}) ..."
            )
            multi = await cluster_project_claims(
                conn, project_id,
                threshold=args.threshold,
                verified_only=verified_only,
                exclude_trials=exclude_trials,
            )
            singles = await add_singleton_clusters(conn, project_id, exclude_trials=exclude_trials)

        print("=" * 60)
        print(f"  Multi-source clusters : {len(multi)}")
        print(f"  Singleton clusters    : {len(singles)}")
        print(f"  Total                 : {len(multi) + len(singles)}")
        print("=" * 60)
        print("Next: python scripts/build_conversations.py --project-id", project_id)
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Rebuild claim clusters (verified, PubMed-only).")
    p.add_argument("--project-id", required=True)
    p.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD)
    p.add_argument("--include-trials", action="store_true", help="Also cluster trial (NCT) claims.")
    p.add_argument("--all-claims", action="store_true", help="Include unverified claims.")
    asyncio.run(main(p.parse_args()))
