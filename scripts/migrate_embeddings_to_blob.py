"""One-off migration: convert embedding columns from legacy JSON text to packed
float32 bytes (see portfolio_architect/embedding/codec.py).

Why: JSON-text embeddings are ~4× larger on disk and slow to parse. The 4096-dim
claim vectors dominate the DB size, so converting them is the biggest single
speed/size win short of moving to pgvector.

Safe + resumable: only rows still stored as text are touched
(`typeof(col) = 'text'`); converted rows become BLOBs and are skipped on re-run.
Readers already accept both formats via codec.decode, so the app keeps working
before, during, and after this runs.

Usage:
    python scripts/migrate_embeddings_to_blob.py            # convert in place
    python scripts/migrate_embeddings_to_blob.py --vacuum   # + reclaim disk after
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.embedding import codec

# (table, primary-key column, embedding column)
TARGETS = [
    ("chunks", "id", "embedding"),
    ("claims", "id", "claim_embedding"),
    ("decisions", "id", "doc_embedding"),
    ("documents", "id", "doc_embedding"),
]

BATCH = 500


async def _count_text(conn, table, col) -> int:
    row = await conn.fetchrow(
        f"SELECT COUNT(*) AS n FROM {table} WHERE {col} IS NOT NULL AND typeof({col}) = 'text'"
    )
    return row["n"]


async def migrate_column(pool, table, pk, col) -> int:
    async with pool.acquire() as conn:
        remaining = await _count_text(conn, table, col)
    if remaining == 0:
        print(f"  {table}.{col}: already migrated (0 text rows)")
        return 0

    print(f"  {table}.{col}: {remaining} text rows to convert…")
    done = 0
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {pk} AS pk, {col} AS v FROM {table} "
                f"WHERE {col} IS NOT NULL AND typeof({col}) = 'text' LIMIT ?",
                BATCH,
            )
            if not rows:
                break
            for r in rows:
                blob = codec.encode(codec.decode(r["v"]))  # JSON text -> float32 bytes
                await conn.execute(
                    f"UPDATE {table} SET {col} = ? WHERE {pk} = ?", blob, r["pk"]
                )
        done += len(rows)
        print(f"    {table}.{col}: {done}/{remaining}", end="\r")
    print(f"  {table}.{col}: {done} converted            ")
    return done


async def main(vacuum: bool) -> None:
    pool = await create_pool()
    print("Converting embedding columns JSON text -> float32 blob…")
    total = 0
    for table, pk, col in TARGETS:
        try:
            total += await migrate_column(pool, table, pk, col)
        except Exception as e:
            # A table/column may not exist in every DB — skip, don't abort.
            print(f"  {table}.{col}: skipped ({e})")
    print(f"Done. {total} rows converted.")

    if vacuum:
        print("VACUUM (reclaiming disk — needs free space ≈ current DB size)…")
        async with pool.acquire() as conn:
            await conn.execute("VACUUM")
        print("VACUUM complete.")

    await close_pool()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vacuum", action="store_true",
                    help="Run VACUUM afterwards to shrink the file (needs temp free space).")
    args = ap.parse_args()
    asyncio.run(main(args.vacuum))
