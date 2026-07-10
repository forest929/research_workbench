from typing import AsyncGenerator

from portfolio_architect.db.pool import _ConnProxy, get_pool


async def get_conn() -> AsyncGenerator[_ConnProxy, None]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def get_db_pool():
    return await get_pool()
