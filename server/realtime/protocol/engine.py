"""Small public seam for stateful realtime conversation implementations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from server.core.interaction_context import InteractionContext
from server.realtime.protocol.commands import RealtimeCommand
from server.realtime.protocol.events import RealtimeEvent


class RealtimeConversation(Protocol):
    async def send(self, command: RealtimeCommand) -> None: ...

    def events(self) -> AsyncIterator[RealtimeEvent]: ...

    async def close(self) -> None: ...


ProfileT_contra = TypeVar("ProfileT_contra", contravariant=True)


class RealtimeEngine(Protocol[ProfileT_contra]):
    async def open(
        self,
        *,
        context: InteractionContext,
        profile: ProfileT_contra,
    ) -> RealtimeConversation: ...
