"""Conversation Journal protocol and deterministic in-memory conformer."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from server.conversation_journal.models import (
    AppendResult,
    ConversationItem,
    ConversationItemDraft,
    ConversationProjection,
    ConversationVisibility,
    JournalScope,
    item_from_draft,
    utc_now,
)


class JournalConflict(RuntimeError):
    pass


class ThreadVersionConflict(RuntimeError):
    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected thread version {expected}, found {actual}")


class ConversationJournal(Protocol):
    async def append(
        self,
        draft: ConversationItemDraft,
        *,
        expected_thread_version: int | None = None,
    ) -> AppendResult: ...

    async def read(
        self,
        scope: JournalScope,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[ConversationItem, ...]: ...

    async def thread_version(self, scope: JournalScope) -> int: ...

    async def project_for_model(
        self,
        scope: JournalScope,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> ConversationProjection: ...


@runtime_checkable
class ConversationHistoryRetention(Protocol):
    async def delete_threads(self, scopes: Sequence[JournalScope]) -> int: ...


@runtime_checkable
class SessionOwnedHistoryRetention(Protocol):
    async def delete_session_owned_threads(self, scopes: Sequence[JournalScope], voice_session_ids: Sequence[str]) -> int: ...


class InMemoryConversationJournal:
    """A concurrency-safe test conformer; it is deliberately not durable."""

    durable = False

    def __init__(self) -> None:
        self._items_by_id: dict[str, ConversationItem] = {}
        self._threads: dict[JournalScope, list[ConversationItem]] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        draft: ConversationItemDraft,
        *,
        expected_thread_version: int | None = None,
    ) -> AppendResult:
        if expected_thread_version is not None and expected_thread_version < 0:
            raise ValueError("expected_thread_version must be non-negative")
        async with self._lock:
            existing = self._items_by_id.get(draft.item_id)
            if existing is not None:
                if existing.item_digest != draft.item_digest:
                    raise JournalConflict(
                        f"conversation item {draft.item_id!r} was reused with different content"
                    )
                return AppendResult(item=existing, created=False)

            thread = self._threads.setdefault(draft.scope, [])
            actual_version = len(thread)
            if (
                expected_thread_version is not None
                and expected_thread_version != actual_version
            ):
                raise ThreadVersionConflict(
                    expected=expected_thread_version,
                    actual=actual_version,
                )
            item = item_from_draft(
                draft,
                sequence=actual_version + 1,
                recorded_at=utc_now(),
            )
            thread.append(item)
            self._items_by_id[item.item_id] = item
            return AppendResult(item=item, created=True)

    async def read(
        self,
        scope: JournalScope,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[ConversationItem, ...]:
        _validate_window(after_sequence, limit)
        async with self._lock:
            return tuple(
                item
                for item in self._threads.get(scope, ())
                if item.sequence > after_sequence
            )[:limit]

    async def thread_version(self, scope: JournalScope) -> int:
        async with self._lock:
            return len(self._threads.get(scope, ()))

    async def delete_threads(self, scopes: Sequence[JournalScope]) -> int:
        selected = frozenset(scopes)
        if not selected:
            return 0
        async with self._lock:
            existing = selected.intersection(self._threads)
            for scope in existing:
                items = self._threads.pop(scope)
                for item in items:
                    self._items_by_id.pop(item.item_id, None)
        return len(existing)

    async def delete_session_owned_threads(self, scopes: Sequence[JournalScope], voice_session_ids: Sequence[str]) -> int:
        allowed = frozenset(voice_session_ids)
        async with self._lock:
            owned = {scope for scope in scopes if scope in self._threads
                     and all(item.context.voice_session_id in allowed for item in self._threads[scope])}
            for scope in owned:
                for item in self._threads.pop(scope):
                    self._items_by_id.pop(item.item_id, None)
        return len(owned)

    async def project_for_model(
        self,
        scope: JournalScope,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> ConversationProjection:
        items = await self.read(
            scope,
            after_sequence=after_sequence,
            limit=limit,
        )
        return ConversationProjection(
            scope=scope,
            items=tuple(
                item for item in items if ConversationVisibility.MODEL in item.visibility
            ),
            thread_version=await self.thread_version(scope),
        )


def _validate_window(after_sequence: int, limit: int) -> None:
    if after_sequence < 0:
        raise ValueError("after_sequence must be non-negative")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
