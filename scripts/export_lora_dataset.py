#!/usr/bin/env python3
"""
Export claim-cluster conversations as an OpenAI-style chat-messages JSONL
file, ready for LoRA fine-tuning.

Usage:
    python scripts/export_lora_dataset.py --project-id <id> [--out data/lora_training/conversations.jsonl]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.claim_clusters import get_clusters_for_project

SYSTEM_PROMPT = (
    "You are an evidence-grounded oncology research assistant specializing in drug therapy "
    "evidence for breast, ovarian, cervical, and endometrial cancer. Answer using only the "
    "evidence available to you, cite your sources, and explicitly note disagreement between "
    "sources rather than picking a side. This is an evidence summary, not clinical advice."
)


async def main(args) -> None:
    project_id = UUID(args.project_id)
    pool = await create_pool()

    async with pool.acquire() as conn:
        clusters = await get_clusters_for_project(conn, project_id, with_answer_only=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_unverified = 0
    with out_path.open("w") as f:
        for cl in clusters:
            if not cl.get("question") or not cl.get("answer"):
                continue
            if not args.include_unverified and not cl.get("citations_valid"):
                skipped_unverified += 1
                continue
            record = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": cl["question"]},
                    {"role": "assistant", "content": cl["answer"]},
                ]
            }
            f.write(json.dumps(record) + "\n")
            written += 1

    print(f"Wrote {written} conversations to {out_path}")
    if skipped_unverified:
        print(f"Skipped {skipped_unverified} with unverified citations "
              f"(use --include-unverified to include them anyway)")

    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export claim-cluster conversations as LoRA training JSONL")
    parser.add_argument("--project-id", required=True, help="Project ID to export")
    parser.add_argument("--out", default="data/lora_training/conversations.jsonl", help="Output JSONL path")
    parser.add_argument("--include-unverified", action="store_true",
                        help="Include conversations whose citations failed the deterministic source_id check")
    args = parser.parse_args()

    asyncio.run(main(args))
