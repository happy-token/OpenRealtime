"""Small public seam for stateful realtime conversation implementations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from server.core.interaction_context import InteractionContext
from server.realtime.protocol.commands import RealtimeCommand
from server.realtime.protocol.events import (
    AgentDelegationRequestProposed,
    AudioDelta,
    DisplayContentDelta,
    RealtimeEvent,
    ResponseStarted,
    SpeechAudioDelta,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextAlignment,
    SpeechTextCommitted,
    SpokenContentDelta,
    ToolRequested,
)

VERSIONED_OUTPUT_EVENTS = (
    ResponseStarted, DisplayContentDelta, SpokenContentDelta, AudioDelta,
    SpeechTextAlignment, ToolRequested, AgentDelegationRequestProposed,
    SpeechStarted, SpeechTextAccepted, SpeechTextCommitted, SpeechAudioDelta,
)


def is_output_deliverable(conversation: RealtimeConversation, event: RealtimeEvent) -> bool:
    """Optional engine permission, read again after every delivery queue.

    Native/legacy engines without version gates retain their existing contract.
    Wrappers forward this read; it must not make a new business decision.
    """
    if not isinstance(event, VERSIONED_OUTPUT_EVENTS):
        return True  # Closing/quiescing a delegate cannot hide terminal/diagnostic facts.
    gate = getattr(conversation, "output_delivery_allowed", None)
    return bool(gate(event)) if gate is not None else True


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
