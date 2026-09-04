"""Replaceable seams used by :class:`OpenRealtime`."""

from __future__ import annotations

from typing import Any, Protocol

from server.gpt_voice_reference.models import ConversationItem, RealtimeAction


class RealtimeSession(Protocol):
    async def next_action(self, items: tuple[ConversationItem, ...]) -> RealtimeAction: ...

    async def cancel_output(self) -> None: ...


class ToolExecutor(Protocol):
    async def execute(self, name: str, arguments: dict[str, Any]) -> str: ...


class WorkerManager(Protocol):
    async def start(self, task: str) -> str: ...

    async def cancel(self, worker_id: str) -> None: ...
