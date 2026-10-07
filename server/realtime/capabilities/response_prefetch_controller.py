"""Session-local ownership of speculative response preparation and cleanup."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from server.core.turn_content import TurnContent, same_asr_utterance
from server.realtime.capabilities.turn_manager import ResponsePrefetcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PrefetchCandidate:
    identity: str
    generation: int
    text: str
    revision: int
    speech_active: bool
    interrupted: bool = False
    continuation: bool = False
    committed: bool = False
    source_text: str | None = None
    continuation_of_turn_id: str | None = None
    sentence_permit_id: str | None = None

    @property
    def observed_text(self) -> str:
        return self.text if self.source_text is None else self.source_text

    @property
    def sentence_handoff(self) -> bool:
        return bool(self.interrupted and self.continuation and not self.speech_active
            and self.sentence_permit_id and self.continuation_of_turn_id and self.source_text)


class ResponsePrefetchController:
    def __init__(
        self,
        provider: ResponsePrefetcher | None,
        *,
        enabled: bool,
        is_current: Callable[[PrefetchCandidate], bool],
        observer: Callable[[str, int, dict[str, Any]], None] | None = None,
    ) -> None:
        self._provider = provider
        self._enabled = enabled
        self._is_current = is_current
        self._observer = observer
        self._builder: Callable[[PrefetchCandidate], Awaitable[TurnContent]] | None = None
        self._lock = asyncio.Lock()
        self._candidate: PrefetchCandidate | None = None
        self._version = 0
        self._prepare_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._owned_generation: int | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    def set_turn_builder(self, builder: Callable[[PrefetchCandidate], Awaitable[TurnContent]]) -> None:
        self._builder = builder

    def _notify(self, operation: str, generation: int, **attributes: Any) -> None:
        if self._observer is not None:
            try:
                self._observer(operation, generation, attributes)
            except Exception:
                logger.warning("Response prefetch observer failed", exc_info=True)

    def _spawn(self, operation: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(operation, name="response-prefetch")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def cancel_pending(self) -> None:
        self._version += 1
        if self._prepare_task is not None:
            self._prepare_task.cancel()
            self._prepare_task = None

    def observe_text(self, text: str) -> None:
        if self._candidate is not None and not same_asr_utterance(self._candidate.observed_text, text):
            self.invalidate("asr_revision")

    def matches_continuation(self, text: str, generation: int, parent_turn_id: str | None) -> bool:
        candidate = self._candidate
        return bool(candidate is not None and candidate.sentence_handoff
            and candidate.continuation_of_turn_id == parent_turn_id
            and candidate.generation == generation and same_asr_utterance(candidate.text, text))

    def finalize(self, text: str, generation: int, *, accepted: bool = True) -> None:
        if not accepted:
            self.invalidate("commit_rejected")
        elif self._candidate is not None and (
            self._candidate.generation != generation
            or not same_asr_utterance(self._candidate.text, text)
        ):
            self.invalidate("final_transcript_changed")
        self.cancel_pending()

    def invalidate(self, reason: str) -> None:
        candidate = self._candidate
        if self._closed or candidate is None or self._provider is None:
            return
        provider = self._provider
        self._candidate = None
        self.cancel_pending()

        async def cleanup() -> None:
            try:
                async with self._lock:
                    await provider.invalidate(candidate.generation, reason=reason)
                self._notify("invalidated", candidate.generation, reason=reason)
            except Exception:
                logger.warning("Response prefetch invalidation failed", exc_info=True)
                self._notify("failed", candidate.generation, reason=reason)

        self._spawn(cleanup())

    def prepare(self, candidate: PrefetchCandidate) -> None:
        if (
            self._closed
            or not self._enabled
            or self._provider is None
            or ((candidate.interrupted or candidate.continuation) and not candidate.sentence_handoff)
            or candidate.committed
        ):
            return
        if candidate.speech_active and not candidate.text.rstrip().endswith(
            ("。", "！", "？", ".", "!", "?")
        ):
            return
        provider = self._provider
        current = self._candidate
        if (
            current is not None
            and current.identity == candidate.identity
            and current.generation == candidate.generation
            and same_asr_utterance(current.text, candidate.text)
            and current.continuation_of_turn_id == candidate.continuation_of_turn_id
            and current.sentence_permit_id == candidate.sentence_permit_id
        ):
            return
        self.cancel_pending()
        self._candidate = candidate
        version = self._version

        async def prepare() -> None:
            try:
                async with self._lock:
                    turn = (
                        await self._builder(candidate)
                        if self._builder
                        else TurnContent(text=candidate.text, generation=candidate.generation)
                    )
                    if self._closed or version != self._version or not self._is_current(candidate):
                        return
                    self._owned_generation = candidate.generation
                    prepared = await provider.prepare(turn)
                    self._notify(
                        "prepared" if prepared else "skipped",
                        candidate.generation,
                        transcript_revision=candidate.revision,
                    )
            except Exception:
                logger.warning("Response prefetch failed", exc_info=True)
                self._notify("failed", candidate.generation)
                if self._version == version:
                    self._candidate = None

        self._prepare_task = self._spawn(prepare())

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_owned(), name="response-prefetch-close")
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self._close_task)

    async def _close_owned(self) -> None:
        self.cancel_pending()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=0.1)
            for task in done:
                if not task.cancelled():
                    task.exception()
            for task in pending:
                task.add_done_callback(
                    lambda finished: None if finished.cancelled() else finished.exception()
                )
            if pending:
                logger.warning("Prefetch controller closed with unfinished operations")
        if self._provider is not None:
            close = getattr(self._provider, "close", None)
            if close is not None:
                await close()
            elif self._owned_generation is not None:
                await self._provider.invalidate(self._owned_generation, reason="session_closed")
        self._candidate = None
