"""Small public seam for stateful realtime conversation implementations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit
from server.realtime.protocol.commands import OutputStopFact, ProjectCommittedItem, RealtimeCommand
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


def is_sentence_permit_current(conversation: RealtimeConversation | None, permit: CurrentSentencePermit) -> bool:
    """Optional read-only authority; unsupported delegates stop immediately."""
    gate = getattr(conversation, "sentence_playback_permit_current", None)
    return bool(gate(permit)) if gate is not None else False


def is_output_context_current(conversation: RealtimeConversation, event: RealtimeEvent) -> bool:
    """Read permission for payload derived from an event, including completion.

    Terminal facts still drain through is_output_deliverable; their synthetic
    subtitles/audio must not bypass the generation's context permission.
    """
    gate = getattr(conversation, "output_context_current", None)
    return bool(gate(event)) if gate is not None else True


def observe_output_admitted(conversation: RealtimeConversation, event: AudioDelta | SpeechAudioDelta) -> None:
    """Record final wire admission synchronously before transport send yields.

    This is a delivery fact, never a playback/physical-speaker confirmation.
    Engines without automatic context repair need not consume this optional fact.
    """
    observer = getattr(conversation, "observe_output_admitted", None)
    if observer is not None:
        observer(event)


async def observe_saved_output_stop(conversation: RealtimeConversation, fact: OutputStopFact) -> None:
    """Notify the original live delegate after canonical persistence, without writing again."""
    observer = getattr(conversation, "observe_saved_output_stop", None)
    if observer is not None:
        await observer(fact)


class RealtimeConversation(Protocol):
    async def send(self, command: RealtimeCommand) -> None: ...

    def events(self) -> AsyncIterator[RealtimeEvent]: ...

    async def close(self) -> None: ...


class CommittedItemProjection(Protocol):
    """Journal writers project committed facts without owning media lifecycle."""

    async def send(self, command: ProjectCommittedItem) -> None: ...


ProfileT_contra = TypeVar("ProfileT_contra", contravariant=True)


class RealtimeEngine(Protocol[ProfileT_contra]):
    async def open(
        self,
        *,
        context: InteractionContext,
        profile: ProfileT_contra,
    ) -> RealtimeConversation: ...
