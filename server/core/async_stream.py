"""Explicit ownership of incremental provider iterators across adapter layers."""

from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager


class OwnedStreamCleanupError(RuntimeError):
    """An owned iterator did not confirm that its resources were released."""


class StreamAdmissionPendingError(RuntimeError):
    """A new stream was not admitted while a previous supplier is still owned.

    This is a request failure, not evidence that resource cleanup failed.
    The supplier owner must still join its real exit during session shutdown.
    """


async def close_async_iterator(iterator: AsyncIterator[object]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception as error:
            raise OwnedStreamCleanupError(f"owned stream cleanup failed: {error}") from error


@asynccontextmanager
async def owned_async_iterator[T](stream: AsyncIterable[T]) -> AsyncIterator[AsyncIterator[T]]:
    iterator = stream.__aiter__()
    try:
        yield iterator
    finally:
        await close_async_iterator(iterator)
