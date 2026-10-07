"""Deduplicated speculative buffer around a ``StreamingBrain``.

``prepare`` starts one provider stream for a transcript revision before Turn
Policy commits it.  ``stream`` later replays buffered deltas and follows the
same live producer, so semantic endpoint latency overlaps model generation
without issuing a duplicate LLM request. A provider-final revision that only
adds terminal sentence punctuation reuses the same producer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from server.core.async_stream import OwnedStreamCleanupError, owned_async_iterator
from server.core.turn_content import TurnContent, same_response_basis
from server.realtime.capabilities.brain_streaming import StreamingTextBrain
from server.realtime.capabilities.speculative_budget import (
    SpeculativeBudgetExceeded,
    SpeculativeBuffer,
    SpeculativeCleanupOwner,
    SpeculativeOutputBudget,
    SpeculativeState,
    detached_error,
    text_cost,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, kw_only=True)
class _PrefetchState(SpeculativeState):
    turn: TurnContent
    chunks: SpeculativeBuffer[str] = field(init=False)
    first_delta_ns: int | None = None


class SpeculativeStreamingBrain:
    """One active speculative LLM request per voice-session Brain instance."""

    def __init__(
        self,
        brain: StreamingTextBrain,
        *,
        observer: Callable[[str, TurnContent, dict[str, Any]], None] | None = None,
        budget: SpeculativeOutputBudget | None = None,
    ) -> None:
        self._brain = brain
        self._observer = observer
        self._state: _PrefetchState | None = None
        self._lock = asyncio.Lock()
        self._cleanup = SpeculativeCleanupOwner()
        self._budget = budget or SpeculativeOutputBudget()
        self._active: _PrefetchState | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    def _observe(self, operation: str, turn: TurnContent, **attributes: Any) -> None:
        if self._observer is not None:
            try:
                self._observer(operation, turn, attributes)
            except Exception:
                logger.warning("Response prefetch observer failed", exc_info=True)

    async def prepare(self, turn: TurnContent) -> bool:
        """Start only after the prior actual producer and consumer release."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("speculative Brain is closed")
            await self._cleanup.admit()
            if self._active is not None:
                return False
            current = self._state
            if current is not None and _same_turn(current.turn, turn) and not current.invalidated:
                return False
            if current is not None:
                self._state = None
                await self._discard(current)
                await self._cleanup.admit()
            if self._closed:
                raise RuntimeError("speculative Brain is closed")
            state = _PrefetchState(turn=turn)
            state.chunks = SpeculativeBuffer(
                state=state, byte_limit=self._budget.text_bytes,
                chunk_limit=self._budget.text_chunks,
                measure=lambda text: text_cost(text, self._budget.text_bytes),
            )
            state.task = asyncio.create_task(self._produce(state),
                                             name=f"speculative-brain-{turn.generation}")
            self._state = state
            state.expiry_handle = asyncio.get_running_loop().call_later(
                self._budget.candidate_seconds, self._expire, state)
        return True

    def _expire(self, state: _PrefetchState) -> None:
        if state.claimed or state.invalidated:
            return
        if state.error is None:
            state.error = SpeculativeBudgetExceeded("candidate_residency")
        state.chunks.clear()
        state.retired.set()
        state.expiry_handle = None
        self._observe("budget_exceeded", state.turn, reason="candidate_residency")

    async def invalidate(self, generation: int, *, reason: str) -> bool:
        async with self._lock:
            state = self._state
            if state is None or state.turn.generation != generation:
                return False
            self._state = None
        await self._discard(state)
        self._observe("discarded", state.turn, reason=reason)
        return True

    async def stream(self, turn: TurnContent) -> AsyncIterator[str]:
        async with self._lock:
            if self._closed:
                raise RuntimeError("speculative Brain is closed")
            if self._active is not None:
                raise RuntimeError("speculative response consumer is already active")
            await self._cleanup.admit()
            state = self._state
            reason = "not_prepared"
            if state is not None:
                if not _same_turn(state.turn, turn) or state.invalidated:
                    reason = "candidate_mismatch"
                elif state.claim(self._budget):
                    reason = "hit"
                else:
                    reason = "budget_bypass"
                if reason != "hit":
                    self._state = None
                    await self._discard(state, require_confirmation=True)
                    state = None
            if self._closed:
                raise RuntimeError("speculative Brain is closed")
            # A direct stream also reserves this single supplier instance.
            active = state or _PrefetchState(turn=turn)
            self._active = active
            self._idle.clear()
        completed = False
        yielded_text = False
        try:
            if state is None:
                self._observe("miss", turn, reason=reason)
                async with owned_async_iterator(self._brain.stream(turn)) as iterator:
                    async for delta in iterator:
                        if delta:
                            yield delta
                return
            self._observe("hit", turn, buffered_characters=sum(map(len, state.chunks)),
                          prefetch_lead_ms=(time.monotonic_ns() - state.started_ns) / 1_000_000,
                          first_delta_ready=state.first_delta_ns is not None)
            async for delta in self._follow(state):
                yielded_text = True
                yield delta
            completed = True
            if not yielded_text and not state.invalidated:
                async with owned_async_iterator(self._brain.stream(turn)) as iterator:
                    async for delta in iterator:
                        if delta:
                            yield delta
        except Exception as error:
            current = asyncio.current_task()
            if isinstance(error, OwnedStreamCleanupError) or (current is not None and current.cancelling()):
                self._cleanup.record_failure(error)
            raise
        finally:
            try:
                if state is not None and (not completed or state.invalidated):
                    await self._discard(state, require_confirmation=True)
            finally:
                async with self._lock:
                    if self._state is state:
                        self._state = None
                    if self._active is active:
                        self._active = None
                        self._idle.set()

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_owned(), name="speculative-brain-close")
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self._close_task)

    async def _close_owned(self) -> None:
        async with self._lock:
            state, self._state = self._state, None
        if state is not None:
            await self._discard(state, require_confirmation=True)
        await self._cleanup.close()
        await self._idle.wait()

    async def _produce(self, state: _PrefetchState) -> None:
        try:
            if state.retired.is_set():
                return
            async with owned_async_iterator(self._brain.stream(state.turn)) as iterator:
                try:
                    async for delta in iterator:
                        if state.retired.is_set():
                            break
                        if not delta:
                            continue
                        if not await state.chunks.append(delta):
                            break
                        if state.first_delta_ns is None:
                            state.first_delta_ns = time.monotonic_ns()
                finally:
                    state.cleanup_started = True
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - replayed at consumer boundary
            state.error = detached_error(error)
            current = asyncio.current_task()
            if isinstance(error, OwnedStreamCleanupError) or (current is not None and current.cancelling()):
                state.cleanup_error = detached_error(error)
        finally:
            async with state.condition:
                state.done = True
                state.condition.notify_all()
            if isinstance(state.error, SpeculativeBudgetExceeded) and not state.claimed:
                state.chunks.clear()
                self._observe("budget_exceeded", state.turn, reason=str(state.error))

    async def _follow(self, state: _PrefetchState) -> AsyncIterator[str]:
        while True:
            async with state.condition:
                while not state.chunks and not state.done and not state.invalidated:
                    await state.condition.wait()
                if state.invalidated:
                    return
                # A failed private candidate must not publish its buffered prefix.
                # In the speech pipeline that prefix could otherwise outlive the
                # failed lease and start a fresh, unrelated TTS request.
                if state.error is not None:
                    raise state.error
                if state.chunks:
                    chunk = state.chunks.pop()
                else:
                    return
            yield chunk

    async def _discard(self, state: _PrefetchState, *, require_confirmation: bool = False) -> None:
        state.invalidated = True
        state.chunks.clear()
        await self._cleanup.discard(state, confirmed=require_confirmation)


def _same_turn(left: TurnContent, right: TurnContent) -> bool:
    return same_response_basis(left, right)
