"""Conversation Journal protocol and deterministic in-memory conformer."""

from __future__ import annotations

import asyncio
from bisect import bisect_right
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from server.conversation_journal.models import (
    AppendResult,
    ArtifactReferenceContent,
    ConversationItem,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationProjection,
    ConversationVisibility,
    JournalScope,
    SessionConversationPage,
    SessionInputEvidencePage,
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


@runtime_checkable
class SessionConversationQuery(Protocol):
    async def read_session_page(
        self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200,
    ) -> SessionConversationPage: ...


@runtime_checkable
class SessionInputEvidenceQuery(Protocol):
    async def read_input_evidence_page(
        self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200,
    ) -> SessionInputEvidencePage: ...


@runtime_checkable
class SessionRecordingQuery(Protocol):
    async def read_recording_page(
        self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200,
    ) -> SessionConversationPage: ...

    async def find_recording_artifact(
        self, voice_session_id: str, artifact_id: str,
    ) -> ConversationItem | None: ...


def validate_recording_query_scope(
    session_id: str, recordings: Sequence[JournalScope], dialogue: Sequence[JournalScope],
) -> JournalScope | None:
    if len(recordings) > 1 or len(dialogue) > 1:
        raise ValueError("session recording identity is ambiguous")
    if not recordings:
        return None
    scope = recordings[0]
    suffix = f"::recording:{session_id}"
    if not scope.thread_id.endswith(suffix) or scope.thread_id == suffix:
        raise ValueError("invalid recording evidence thread")
    source = JournalScope(scope.tenant_id, scope.user_id, scope.thread_id[:-len(suffix)])
    if dialogue and dialogue[0] != source:
        raise ValueError("session recording and conversation identity is ambiguous")
    return scope


def validate_input_evidence_query_scope(
    session_id: str, evidence: Sequence[JournalScope], dialogue: Sequence[JournalScope],
) -> JournalScope | None:
    if len(evidence) > 1 or len(dialogue) > 1:
        raise ValueError("session input evidence identity is ambiguous")
    if not evidence:
        return None
    scope = evidence[0]
    suffix = f"::input-evidence:{session_id}"
    if not scope.thread_id.endswith(suffix) or scope.thread_id == suffix:
        raise ValueError("invalid input evidence thread")
    source = JournalScope(scope.tenant_id, scope.user_id, scope.thread_id[:-len(suffix)])
    if dialogue and dialogue[0] != source:
        raise ValueError("session input evidence and conversation identity is ambiguous")
    return scope


class InMemoryConversationJournal:
    """A concurrency-safe test conformer; it is deliberately not durable."""

    durable = False

    def __init__(self) -> None:
        self._items_by_id: dict[str, ConversationItem] = {}
        self._threads: dict[JournalScope, list[ConversationItem]] = {}
        self._session_replay: dict[str, dict[JournalScope, list[ConversationItem]]] = {}
        self._session_input_evidence: dict[str, dict[JournalScope, list[ConversationItem]]] = {}
        self._session_recordings: dict[str, dict[JournalScope, list[ConversationItem]]] = {}
        self._recording_artifacts: dict[tuple[str, str], dict[JournalScope, list[ConversationItem]]] = {}
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
            if item.kind in {ConversationItemKind.USER_INPUT, ConversationItemKind.ASSISTANT_OUTPUT}:
                self._session_replay.setdefault(item.context.voice_session_id, {}).setdefault(draft.scope, []).append(item)
            if item.producer == "semantic.input_evidence":
                self._session_input_evidence.setdefault(item.context.voice_session_id, {}).setdefault(draft.scope, []).append(item)
            if item.producer == "voice-session-recording":
                session = item.context.voice_session_id
                self._session_recordings.setdefault(session, {}).setdefault(draft.scope, []).append(item)
                for artifact_id in {part.artifact_id for part in item.content if isinstance(part, ArtifactReferenceContent)}:
                    self._recording_artifacts.setdefault((session, artifact_id), {}).setdefault(draft.scope, []).append(item)
            return AppendResult(item=item, created=True)

    async def read_session_page(
        self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200,
    ) -> SessionConversationPage:
        validate_session_window(voice_session_id, after_sequence, limit)
        async with self._lock:
            scopes = self._session_replay.get(voice_session_id, {})
            if len(scopes) > 1:
                raise ValueError("session conversation identity is ambiguous")
            items = next(iter(scopes.values()), [])
            start = bisect_right(items, after_sequence, key=lambda item: item.sequence)
            page = tuple(items[start:start + limit])
            more = start + len(page) < len(items)
            return SessionConversationPage(page, page[-1].sequence if more else None)

    async def read_input_evidence_page(
        self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200,
    ) -> SessionInputEvidencePage:
        validate_session_window(voice_session_id, after_sequence, limit)
        async with self._lock:
            evidence = self._session_input_evidence.get(voice_session_id, {})
            scope = validate_input_evidence_query_scope(voice_session_id, tuple(evidence),
                                                        tuple(self._session_replay.get(voice_session_id, {})))
            items = evidence.get(scope, []) if scope is not None else []
            start = bisect_right(items, after_sequence, key=lambda item: item.sequence)
            page = tuple(items[start:start + limit])
            return SessionInputEvidencePage(page, page[-1].sequence if start + len(page) < len(items) else None, scope is not None)

    def _recording_scope(self, session_id: str) -> JournalScope | None:
        return validate_recording_query_scope(session_id, tuple(self._session_recordings.get(session_id, {})),
                                              tuple(self._session_replay.get(session_id, {})))

    async def read_recording_page(
        self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200,
    ) -> SessionConversationPage:
        validate_session_window(voice_session_id, after_sequence, limit)
        async with self._lock:
            scope = self._recording_scope(voice_session_id)
            items = self._session_recordings.get(voice_session_id, {}).get(scope, []) if scope is not None else []
            start = bisect_right(items, after_sequence, key=lambda item: item.sequence)
            page = tuple(items[start:start + limit])
            return SessionConversationPage(page, page[-1].sequence if start + len(page) < len(items) else None)

    async def find_recording_artifact(self, voice_session_id: str, artifact_id: str) -> ConversationItem | None:
        validate_session_window(voice_session_id, 0, 1)
        if not artifact_id or len(artifact_id) > 128:
            raise ValueError("invalid recording artifact identity")
        async with self._lock:
            scope = self._recording_scope(voice_session_id)
            items = self._recording_artifacts.get((voice_session_id, artifact_id), {}).get(scope, []) if scope is not None else []
            if len(items) > 1:
                raise ValueError("recording artifact reference is ambiguous")
            return items[0] if items else None

    def _remove_thread_items(self, scope: JournalScope, items: Sequence[ConversationItem]) -> None:
        sessions = set()
        for item in items:
            self._items_by_id.pop(item.item_id, None)
            sessions.add(item.context.voice_session_id)
        for item in items:
            if item.producer == "voice-session-recording":
                for part in item.content:
                    if isinstance(part, ArtifactReferenceContent):
                        key = (item.context.voice_session_id, part.artifact_id)
                        artifact_scopes = self._recording_artifacts.get(key)
                        if artifact_scopes is not None:
                            artifact_scopes.pop(scope, None)
                            if not artifact_scopes:
                                self._recording_artifacts.pop(key, None)
        for session_id in sessions:
            evidence_scopes = self._session_input_evidence.get(session_id)
            if evidence_scopes is not None:
                evidence_scopes.pop(scope, None)
                if not evidence_scopes:
                    self._session_input_evidence.pop(session_id, None)
            recording_scopes = self._session_recordings.get(session_id)
            if recording_scopes is not None:
                recording_scopes.pop(scope, None)
                if not recording_scopes:
                    self._session_recordings.pop(session_id, None)
            scopes = self._session_replay.get(session_id)
            if scopes is not None:
                scopes.pop(scope, None)
                if not scopes:
                    self._session_replay.pop(session_id)

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
                self._remove_thread_items(scope, items)
        return len(existing)

    async def delete_session_owned_threads(self, scopes: Sequence[JournalScope], voice_session_ids: Sequence[str]) -> int:
        allowed = frozenset(voice_session_ids)
        async with self._lock:
            owned = {scope for scope in scopes if scope in self._threads
                     and all(item.context.voice_session_id in allowed for item in self._threads[scope])}
            for scope in owned:
                self._remove_thread_items(scope, self._threads.pop(scope))
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


def validate_session_window(voice_session_id: str, after_sequence: int, limit: int) -> None:
    if not voice_session_id or len(voice_session_id) > 128:
        raise ValueError("invalid voice session identity")
    if type(after_sequence) is not int or not 0 <= after_sequence <= 2**63 - 1:
        raise ValueError("session cursor must be a non-negative signed bigint")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("session page limit must be between 1 and 1000")
