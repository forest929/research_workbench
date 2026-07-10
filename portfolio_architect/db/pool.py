"""SQLite connection pool shim — matches the asyncpg pool.acquire() interface."""

import aiosqlite
from uuid import UUID

from portfolio_architect.config import get_settings


def _coerce(args: tuple) -> tuple:
    """Convert UUID and bool to SQLite-native types."""
    out = []
    for a in args:
        if isinstance(a, UUID):
            out.append(str(a))
        elif isinstance(a, bool):
            out.append(1 if a else 0)
        else:
            out.append(a)
    return tuple(out)


class _ConnProxy:
    """Wraps aiosqlite.Connection and mimics asyncpg Connection."""

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


_pool: _Pool | None = None


async def create_pool() -> _Pool:
    global _pool
    _pool = _Pool(get_settings().database_path)
    return _pool


async def get_pool() -> _Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call create_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    _pool = None
