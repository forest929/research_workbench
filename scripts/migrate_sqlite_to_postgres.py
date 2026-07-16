"""One-shot data migration: SQLite corpus  →  Managed PostgreSQL + pgvector.

Copies every application table from the local SQLite DB into Postgres, converting
the packed-float32 embedding BLOBs (and any legacy JSON embeddings) into pgvector
`vector` values on the way. The full-text `chunks_fts` table is skipped — on
Postgres, search rides on the generated `chunks.content_tsv` column, which fills
itself as rows land.

Usage:
    # Point DATABASE_URL at the target Postgres, then:
    DATABASE_URL=postgresql://user:pass@host:5432/dbname \\
        python scripts/migrate_sqlite_to_postgres.py --sqlite portfolio_architect.db

    # Options:
    #   --sqlite PATH   source SQLite file (default: portfolio_architect.db)
    #   --batch N       rows per insert batch (default: 500)
    #   --skip-migrate  don't run schema migrations first (assume tables exist)

The target schema is created by the app's own migrations before any data is
copied, so the run is self-contained. Re-running is safe: every insert uses
ON CONFLICT DO NOTHING, so a partial/interrupted run resumes cleanly.
"""

import argparse
import asyncio
import os
import sys

import aiosqlite

# Insert parents before children so ON DELETE CASCADE foreign keys are satisfied.
TABLE_ORDER = [
    "projects",
    "documents",
    "chunks",
    "criteria",
    "gold_labels",
    "workstream_runs",
    "judge_verdicts",
    "query_log",
    "decisions",
    "disagreements",
    "preference_observations",
    "claims",
    "claim_clusters",
    "user_sources",
    "saved_publications",
    "assistant_answers",
    "drug_aliases",
]

EMBEDDING_COLUMNS = {"embedding", "claim_embedding", "doc_embedding"}


async def _sqlite_columns(sconn: aiosqlite.Connection, table: str) -> list[str]:
    async with sconn.execute(f"PRAGMA table_info({table})") as cur:
        return [r[1] for r in await cur.fetchall()]


async def _pg_columns(pconn, table: str) -> set[str]:
    rows = await pconn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    return {r["column_name"] for r in rows}


class _ResilientPg:
    """asyncpg connection wrapper that survives the public endpoint dropping a
    long-running connection. On a connection-level error it reconnects (re-
    registering the pgvector codec) and retries the operation. Combined with the
    inserts' ON CONFLICT DO NOTHING, this makes the copy self-healing."""

    _CONN_ERRORS = None  # set lazily to avoid importing asyncpg at module import

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._c = None

    async def connect(self) -> None:
        import asyncpg
        from pgvector.asyncpg import register_vector

        if _ResilientPg._CONN_ERRORS is None:
            _ResilientPg._CONN_ERRORS = (
                asyncpg.exceptions.ConnectionDoesNotExistError,
                asyncpg.exceptions.InterfaceError,
                asyncpg.exceptions.PostgresConnectionError,
                ConnectionResetError,
                ConnectionError,
                OSError,
            )
        self._c = await asyncpg.connect(self._dsn, timeout=30)
        await register_vector(self._c)

    async def _retry(self, fn, *args, retries: int = 6):
        for attempt in range(retries):
            try:
                return await fn(*args)
            except _ResilientPg._CONN_ERRORS:
                if attempt == retries - 1:
                    raise
                delay = min(2 ** attempt, 30)
                print(f"\n  connection lost — reconnecting in {delay}s "
                      f"(attempt {attempt + 1}/{retries})…")
                await asyncio.sleep(delay)
                try:
                    await self.connect()
                except Exception:
                    pass  # next loop iteration retries the connect too

    async def fetch(self, sql, *args):
        return await self._retry(lambda: self._c.fetch(sql, *args))

    async def executemany(self, sql, records):
        return await self._retry(lambda: self._c.executemany(sql, records))

    async def close(self) -> None:
        if self._c is not None:
            await self._c.close()


async def _migrate_table(sconn, pconn, table: str, batch: int) -> int:
    from portfolio_architect.embedding import codec

    scols = await _sqlite_columns(sconn, table)
    if not scols:
        print(f"  {table}: not present in source — skipped")
        return 0
    pcols = await _pg_columns(pconn, table)
    cols = [c for c in scols if c in pcols]  # only columns that exist on both sides
    emb_idx = {i for i, c in enumerate(cols) if c in EMBEDDING_COLUMNS}

    col_list = ", ".join(cols)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    insert = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT DO NOTHING"
    )

    total = 0
    async with sconn.execute(f"SELECT {col_list} FROM {table}") as cur:
        while True:
            rows = await cur.fetchmany(batch)
            if not rows:
                break
            records = []
            for row in rows:
                rec = list(row)
                for i in emb_idx:
                    rec[i] = codec.decode(rec[i])  # bytes/JSON → ndarray for pgvector
                records.append(tuple(rec))
            await pconn.executemany(insert, records)
            total += len(records)
            print(f"  {table}: {total} rows", end="\r", flush=True)
    print(f"  {table}: {total} rows        ")
    return total


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="portfolio_architect.db")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--skip-migrate", action="store_true")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn.startswith(("postgresql://", "postgres://")):
        sys.exit("DATABASE_URL must be a postgresql:// URL for the target database.")
    if not os.path.exists(args.sqlite):
        sys.exit(f"Source SQLite file not found: {args.sqlite}")

    import asyncpg
    from pgvector.asyncpg import register_vector

    # 1. Build the target schema via the app's own migrations (creates tables,
    #    the pgvector extension, vector columns, and the tsvector FTS column).
    if not args.skip_migrate:
        from portfolio_architect.db.pool import create_pool, close_pool
        from portfolio_architect.db.migrations import run_migrations

        print("Running schema migrations on target Postgres…")
        pool = await create_pool()
        await run_migrations(pool)
        await close_pool()

    # 2. Copy the data. Use a self-healing connection: the public endpoint has
    #    been observed to reset long-running connections mid-copy, and a single
    #    connection for the whole run would abort the migration. _ResilientPg
    #    reconnects and retries; ON CONFLICT DO NOTHING makes retries idempotent.
    sconn = await aiosqlite.connect(args.sqlite)
    pconn = _ResilientPg(dsn)
    await pconn.connect()
    try:
        grand = 0
        print(f"Migrating {args.sqlite} → Postgres")
        for table in TABLE_ORDER:
            grand += await _migrate_table(sconn, pconn, table, args.batch)
        print(f"Done. {grand} rows migrated.")
    finally:
        await sconn.close()
        await pconn.close()


if __name__ == "__main__":
    asyncio.run(main())
