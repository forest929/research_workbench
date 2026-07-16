"""Database connection pool with two interchangeable backends.

Backend is chosen at runtime from `DATABASE_URL` (see config.db_backend):

  - **SQLite** (aiosqlite) — the local-dev default. A fresh connection per
    `acquire()`; single-writer.
  - **Postgres** (asyncpg + pgvector) — the scalable path. A real connection
    pool; multi-writer, so the API can run several uvicorn workers/replicas.

Both expose the SAME `pool.acquire()` -> connection-proxy interface the rest of
the codebase already targets (the asyncpg-shaped shim). Call sites keep using
`?` placeholders and `row["col"]` / `row.get("col")` access regardless of
backend — the Postgres proxy translates `?`→`$n` and returns plain dicts.

`is_postgres()` lets the handful of places with genuinely dialect-specific SQL
(FTS, upserts, vector search) branch explicitly.
"""

import re
from uuid import UUID

from portfolio_architect.config import get_settings


def is_postgres() -> bool:
    return get_settings().db_backend == "postgres"


def _coerce(args: tuple) -> tuple:
    """Convert UUID and bool to DB-native scalar types (shared by both backends).
    Booleans map to 0/1 because the schema stores flags as INTEGER on both
    backends; UUIDs map to str because ids are TEXT columns. numpy arrays (pgvector
    params) and everything else pass through untouched."""
    out = []
    for a in args:
        if isinstance(a, UUID):
            out.append(str(a))
        elif isinstance(a, bool):
            out.append(1 if a else 0)
        else:
            out.append(a)
    return tuple(out)


# ─────────────────────────────────────────────────────────────────────────────
# SQLite backend
# ─────────────────────────────────────────────────────────────────────────────
import aiosqlite  # noqa: E402


class _ConnProxy:
    """Wraps aiosqlite.Connection and mimics an asyncpg Connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._c = conn

    async def execute(self, sql: str, *args) -> None:
        await self._c.execute(sql, _coerce(args))
        await self._c.commit()

    async def fetchrow(self, sql: str, *args) -> dict | None:
        async with self._c.execute(sql, _coerce(args)) as cur:
            row = await cur.fetchone()
            if row is None:
                await self._c.commit()
                return None
            cols = [d[0] for d in cur.description]
            result = dict(zip(cols, row))
        await self._c.commit()
        return result

    async def fetch(self, sql: str, *args) -> list[dict]:
        async with self._c.execute(sql, _coerce(args)) as cur:
            rows = await cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]

    async def executemany(self, sql: str, args_list) -> None:
        await self._c.executemany(sql, [_coerce(tuple(a)) for a in args_list])
        await self._c.commit()


class _AcquireCtx:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> _ConnProxy:
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        # Wait up to 30s for a write lock instead of failing immediately — lets
        # concurrent writers (e.g. batch pipeline scripts + the API) serialize
        # cleanly rather than raising "database is locked".
        await self._conn.execute("PRAGMA busy_timeout=30000")
        return _ConnProxy(self._conn)

    async def __aexit__(self, *_) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None


class _Pool:
    def __init__(self, db_path: str) -> None:
        self._path = db_path

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._path)

    async def close(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Postgres backend (asyncpg + pgvector)
# ─────────────────────────────────────────────────────────────────────────────
def _to_pg_sql(sql: str) -> str:
    """Translate the codebase's SQLite-dialect SQL to Postgres at the proxy seam,
    so call sites stay backend-agnostic. Four substitutions, all with a single
    unambiguous form in this codebase:

      1. `datetime('now')`      → UTC 'YYYY-MM-DD HH24:MI:SS' text (matches the
                                   string format SQLite's datetime() produces).
      2. `GROUP_CONCAT(DISTINCT x)` → `string_agg(DISTINCT x, ',')`.
      3. `instr(x, y)`          → `strpos(x, y)` (both 1-based, 0 when absent;
                                   SQLite `substr` needs no change — identical in
                                   Postgres). Used by the reading-list year sort.
      4. `?` placeholders       → `$1, $2, ...` (positional; no `?` ever appears
                                   inside a string literal in our SQL).
    """
    sql = sql.replace(
        "datetime('now')",
        "to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD HH24:MI:SS')",
    )
    sql = re.sub(
        r"GROUP_CONCAT\(\s*DISTINCT\s+([^)]+?)\s*\)",
        r"string_agg(DISTINCT \1, ',')",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"\binstr\s*\(", "strpos(", sql, flags=re.IGNORECASE)
    # ?  ->  $1, $2, ...
    n = 0

    def _sub(_m):
        nonlocal n
        n += 1
        return f"${n}"

    return re.sub(r"\?", _sub, sql)


class _PgConnProxy:
    """Wraps an asyncpg Connection and mimics the SQLite `_ConnProxy` surface:
    `?` placeholders, and dict rows (so `row.get(...)` keeps working — asyncpg
    Records don't support `.get()`)."""

    def __init__(self, conn) -> None:
        self._c = conn

    async def execute(self, sql: str, *args) -> None:
        await self._c.execute(_to_pg_sql(sql), *_coerce(args))

    async def fetchrow(self, sql: str, *args) -> dict | None:
        row = await self._c.fetchrow(_to_pg_sql(sql), *_coerce(args))
        return dict(row) if row is not None else None

    async def fetch(self, sql: str, *args) -> list[dict]:
        rows = await self._c.fetch(_to_pg_sql(sql), *_coerce(args))
        return [dict(r) for r in rows]

    async def executemany(self, sql: str, args_list) -> None:
        await self._c.executemany(
            _to_pg_sql(sql), [_coerce(tuple(a)) for a in args_list]
        )


class _PgAcquireCtx:
    def __init__(self, pg_pool) -> None:
        self._pg_pool = pg_pool
        self._conn = None

    async def __aenter__(self) -> _PgConnProxy:
        self._conn = await self._pg_pool.acquire()
        return _PgConnProxy(self._conn)

    async def __aexit__(self, *_) -> None:
        if self._conn is not None:
            await self._pg_pool.release(self._conn)
            self._conn = None


class _PgPool:
    def __init__(self, pg_pool) -> None:
        self._pg_pool = pg_pool

    def acquire(self) -> _PgAcquireCtx:
        return _PgAcquireCtx(self._pg_pool)

    async def close(self) -> None:
        await self._pg_pool.close()


async def _create_pg_pool() -> _PgPool:
    """Ensure the pgvector extension exists, then open an asyncpg pool whose
    connections have the pgvector codec registered (vector columns read/write as
    numpy arrays). The extension MUST exist before `register_vector`, so we
    bootstrap it on a throwaway connection first."""
    import asyncpg
    from pgvector.asyncpg import register_vector

    dsn = get_settings().database_url

    boot = await asyncpg.connect(dsn)
    try:
        await boot.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await boot.close()

    settings = get_settings()
    pg_pool = await asyncpg.create_pool(
        dsn,
        min_size=settings.pg_pool_min_size,
        max_size=settings.pg_pool_max_size,
        init=register_vector,
    )
    return _PgPool(pg_pool)


# ─────────────────────────────────────────────────────────────────────────────
# Backend-agnostic entry points
# ─────────────────────────────────────────────────────────────────────────────
_pool: _Pool | _PgPool | None = None


async def create_pool():
    global _pool
    if is_postgres():
        _pool = await _create_pg_pool()
    else:
        _pool = _Pool(get_settings().sqlite_path)
    return _pool


async def get_pool():
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call create_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
    _pool = None
