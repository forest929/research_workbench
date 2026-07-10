#!/usr/bin/env python3
"""Initialize the database: run all migrations and print table list.

Safe to re-run — all statements are idempotent (CREATE IF NOT EXISTS).

Usage:
    python scripts/init_db.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.migrations import run_migrations, list_tables


async def main() -> None:
    print("Connecting to database...")
    pool = await create_pool()
    try:
        print("Running migrations...")
        await run_migrations(pool)
        tables = await list_tables(pool)
        print(f"\n✅ Database ready. Tables ({len(tables)}):")
        for t in tables:
            print(f"   • {t}")
    finally:
        await close_pool()
        print("\nConnection closed.")


if __name__ == "__main__":
    asyncio.run(main())
