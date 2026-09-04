"""Correlated feedback channel for Realtime Brain tool requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolResultFeedback:
    response_id: str
    call_id: str
    success: bool
    model_output: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.call_id or not self.model_output:
            raise ValueError("tool feedback identity and model output must be non-empty")
        if self.success and self.error_code is not None:
            raise ValueError("successful tool feedback cannot carry an error code")


class ToolResultChannel:
    """One-response, single-delivery rendezvous between app and Brain adapter."""

    def __init__(self, response_id: str) -> None:
        if not response_id:
            raise ValueError("response_id must be non-empty")
        self._response_id = response_id
        self._buffered: dict[str, ToolResultFeedback] = {}
        self._waiters: dict[str, asyncio.Future[ToolResultFeedback]] = {}
        self._consumed: set[str] = set()
        self._lock = asyncio.Lock()

    async def submit(self, feedback: ToolResultFeedback) -> None:
        if feedback.response_id != self._response_id:
            raise ValueError("tool feedback belongs to a different response")
        async with self._lock:
            if feedback.call_id in self._consumed or feedback.call_id in self._buffered:
                raise ValueError("tool feedback was already submitted")
            waiter = self._waiters.pop(feedback.call_id, None)
            if waiter is None:
                self._buffered[feedback.call_id] = feedback
                return
            self._consumed.add(feedback.call_id)
            if not waiter.done():
                waiter.set_result(feedback)

    async def wait(self, call_id: str) -> ToolResultFeedback:
        if not call_id:
            raise ValueError("call_id must be non-empty")
        async with self._lock:
            if call_id in self._consumed:
                raise ValueError("tool feedback was already consumed")
            buffered = self._buffered.pop(call_id, None)
            if buffered is not None:
                self._consumed.add(call_id)
                return buffered
            if call_id in self._waiters:
                raise ValueError("tool feedback already has a waiter")
            waiter = asyncio.get_running_loop().create_future()
            self._waiters[call_id] = waiter
        try:
            return await waiter
        finally:
            async with self._lock:
                if self._waiters.get(call_id) is waiter:
                    self._waiters.pop(call_id, None)

    async def close(self) -> None:
        async with self._lock:
            waiters = tuple(self._waiters.values())
            self._waiters.clear()
            self._buffered.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()
