from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


@asynccontextmanager
async def connection_scope(executor: Any) -> AsyncIterator[Any]:
    acquire = getattr(executor, "acquire", None)
    if acquire is None:
        yield executor
        return
    async with acquire() as connection:
        yield connection
