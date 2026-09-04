"""Dependency-free adapters for tests and the local demo."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from inspect import isawaitable
from typing import Any

from server.gpt_voice_reference.models import ConversationItem, RealtimeAction


class InMemoryRealtimeSession:
    def __init__(self, actions: Iterable[RealtimeAction]) -> None:
        self._actions = deque(actions)
        self.cancel_count = 0

    async def next_action(self, items: tuple[ConversationItem, ...]) -> RealtimeAction:
        del items
        if not self._actions:
            raise RuntimeError("No scripted Realtime action remains")
        return self._actions.popleft()

    async def cancel_output(self) -> None:
        self.cancel_count += 1


class InMemoryToolExecutor:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, name: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._handlers[name] = handler

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            handler = self._handlers[name]
        except KeyError as error:
            raise LookupError(f"Unknown tool: {name}") from error
        result = handler(arguments)
        if isawaitable(result):
            result = await result
        return str(result)


class InMemoryWorkerManager:
    def __init__(self) -> None:
        self.started: dict[str, str] = {}
        self.cancelled: list[str] = []

    async def start(self, task: str) -> str:
        worker_id = f"worker-{len(self.started) + 1}"
        self.started[worker_id] = task
        return worker_id

    async def cancel(self, worker_id: str) -> None:
        if worker_id in self.started:
            self.cancelled.append(worker_id)
