"""Bounded routing for the VAD → ASR → Turn Manager cascaded input path."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from server.conversation_journal import (
    ConversationItem,
)
from server.core.interaction_context import InteractionContext
from server.core.turn_content import TurnContent
from server.realtime.capabilities.asr import (
    AppendAsrAudio,
    AsrCapabilityProvider,
    AsrCapabilitySession,
    AsrEndpointHint,
    AsrTranscriptDelta,
    CommitAsrInput,
    DiscardAsrInput,
)
from server.realtime.capabilities.assistant_echo import project_assistant_echo
from server.realtime.capabilities.reply_revision_controller import ReplyRevision
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    AsrDiscardRequested,
    ObserveAsrEvent,
    ObserveAssistantPlayback,
    ObserveAssistantSpokenText,
    ObserveAssistantYielded,
    ObserveConversationItem,
    ObserveSystemResponseCompleted,
    ObserveSystemResponseStarted,
    ObserveVadEvent,
    TurnManagerCapabilityProvider,
    TurnManagerCapabilitySession,
    TurnManagerEvent,
)
from server.realtime.capabilities.vad import (
    AnalyzeVadAudio,
    VadCapabilityProvider,
    VadCapabilitySession,
    VadSpeechStarted,
)
from server.realtime.protocol.audio import AudioFrame
from server.realtime.protocol.commands import ReportPlaybackProgress
from server.realtime.protocol.playback import ReplyPlayback

if TYPE_CHECKING:
    from server.realtime.provider_latency import ProviderLatencyObserver

_CLOSED = object()


@dataclass(frozen=True, slots=True, kw_only=True)
class CascadedCapabilityFailed:
    context: InteractionContext
    capability: str
    error: str

    def __post_init__(self) -> None:
        if not self.capability or not self.error:
            raise ValueError("cascaded capability failure must identify its source and error")


CascadedInputEvent = AsrTranscriptDelta | TurnManagerEvent | CascadedCapabilityFailed


class CascadedInputPipeline:
    """Owns capability routing; individual sessions never call each other."""

    def __init__(
        self,
        *,
        vad: VadCapabilitySession,
        asr: AsrCapabilitySession,
        turn_manager: TurnManagerCapabilitySession,
        context: InteractionContext,
        event_queue_size: int,
        provider_timing: ProviderLatencyObserver | None = None,
    ) -> None:
        self._context = context
        self._vad = vad
        self._provider_timing = provider_timing
        self._asr: AsrCapabilitySession
        if provider_timing:
            from server.realtime.provider_latency import TimedAsrSession

            self._asr = TimedAsrSession(asr, provider_timing)
        else:
            self._asr = asr
        self._turn_manager = turn_manager
        self._events: asyncio.Queue[CascadedInputEvent | object] = asyncio.Queue(
            maxsize=event_queue_size
        )
        self._response_active = False
        self._latest_assistant_text = ""
        self._closed = False
        self._tasks = (
            asyncio.create_task(
                self._guard_route("vad", self._route_vad()),
                name="cascaded-route-vad",
            ),
            asyncio.create_task(
                self._guard_route("asr", self._route_asr()),
                name="cascaded-route-asr",
            ),
            asyncio.create_task(
                self._guard_route("turn_manager", self._route_turn_manager()),
                name="cascaded-route-turn",
            ),
        )

    @classmethod
    async def open(
        cls,
        *,
        context: InteractionContext,
        vad: VadCapabilityProvider,
        asr: AsrCapabilityProvider,
        turn_manager: TurnManagerCapabilityProvider,
        event_queue_size: int = 64,
        provider_timing: ProviderLatencyObserver | None = None,
    ) -> CascadedInputPipeline:
        if event_queue_size < 1:
            raise ValueError("event_queue_size must be positive")
        opened = await asyncio.gather(
            vad.open(context=context),
            asr.open(context=context),
            turn_manager.open(context=context),
            return_exceptions=True,
        )
        failure = next(
            (result for result in opened if isinstance(result, BaseException)),
            None,
        )
        if failure is not None:
            await asyncio.gather(
                *(
                    result.close()
                    for result in opened
                    if not isinstance(result, BaseException)
                ),
                return_exceptions=True,
            )
            raise failure
        vad_session, asr_session, turn_session = opened
        return cls(
            context=context,
            vad=cast(VadCapabilitySession, vad_session),
            asr=cast(AsrCapabilitySession, asr_session),
            turn_manager=cast(TurnManagerCapabilitySession, turn_session),
            event_queue_size=event_queue_size,
            provider_timing=provider_timing,
        )

    def set_prefetch_turn_builder(self, builder: Callable[[str, int], Awaitable[TurnContent]]) -> None:
        bind = getattr(self._turn_manager, "set_prefetch_turn_builder", None)
        if bind is not None:
            bind(builder)

    def response_delivery_allowed(self, response_id: str) -> bool:
        check = getattr(self._turn_manager, "response_delivery_allowed", None)
        return bool(check(response_id)) if check is not None else True

    def response_revision(self, response_id: str) -> ReplyRevision | None:
        read = getattr(self._turn_manager, "response_revision", None)
        return read(response_id) if read is not None else None

    async def invalidate_response(self, response_id: str, *, context: InteractionContext, reason: str) -> None:
        invalidate = getattr(self._turn_manager, "invalidate_response", None)
        if invalidate is not None:
            await invalidate(response_id, context=context, reason=reason)

    async def append_audio(
        self,
        frame: AudioFrame,
        *,
        context: InteractionContext | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("cascaded input pipeline is closed")
        await self._vad.send(AnalyzeVadAudio(frame=frame, context=context))
        await self._asr.send(AppendAsrAudio(frame=frame, context=context))

    async def response_completed(
        self,
        response_id: str,
        *,
        context: InteractionContext | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("cascaded input pipeline is closed")
        await self._turn_manager.send(
            ObserveSystemResponseCompleted(response_id=response_id, context=context)
        )
        self._response_active = False

    async def response_started(
        self,
        response_id: str,
        *,
        context: InteractionContext | None = None,
        preparing: bool = False,
    ) -> None:
        if self._closed:
            raise RuntimeError("cascaded input pipeline is closed")
        self._latest_assistant_text = ""
        await self._turn_manager.send(
            ObserveSystemResponseStarted(response_id=response_id, context=context, preparing=preparing)
        )
        self._response_active = True

    async def assistant_spoken_text(
        self,
        text: str,
        *,
        context: InteractionContext,
        playback_started: bool = True,
    ) -> None:
        if self._closed:
            raise RuntimeError("cascaded input pipeline is closed")
        self._latest_assistant_text = text
        await self._turn_manager.send(
            ObserveAssistantSpokenText(context=context, text=text, playback_started=playback_started)
        )

    async def assistant_playback(self, command: ReportPlaybackProgress, *, response_id: str) -> None:
        await self._turn_manager.send(ObserveAssistantPlayback(
            context=command.context, response_id=response_id,
            fact=ReplyPlayback(output_epoch=command.output_epoch, speech_id=command.speech_id,
                played_audio_end_us=command.played_audio_end_us, confirmed_text_end=command.delivered_text_end,
                observed_at_ns=command.observed_at_ns or time.monotonic_ns(),
                position_precision="sample" if command.played_position_samples is not None else "unknown",
                played_position_samples=command.played_position_samples, sample_rate_hz=command.sample_rate_hz,
                current_sentence=command.current_sentence if command.played_position_samples is not None else None,
                terminal=command.completed or command.stopped),
        ))

    async def assistant_yielded(self, *, context: InteractionContext) -> None:
        if self._closed:
            raise RuntimeError("cascaded input pipeline is closed")
        await self._turn_manager.send(ObserveAssistantYielded(context=context))

    async def observe_conversation_item(self, item: ConversationItem) -> None:
        """Refresh the session-local EoT history after Journal projection."""

        if self._closed:
            raise RuntimeError("cascaded input pipeline is closed")
        await self._turn_manager.send(ObserveConversationItem(item=item))

    async def _route_vad(self) -> None:
        async for event in self._vad.events():
            if self._provider_timing is not None and isinstance(event, VadSpeechStarted):
                self._provider_timing.asr_speech_started(event.context)
            await self._turn_manager.send(ObserveVadEvent(event=event))

    async def _route_asr(self) -> None:
        async for event in self._asr.events():
            routed_event = self._project_asr_event(event)
            if routed_event is None:
                # Turn Manager still needs the raw echo as evidence so it can
                # restore SPEAK and request that the provider buffer be discarded.
                await self._turn_manager.send(ObserveAsrEvent(event=event))
                continue
            if isinstance(routed_event, AsrTranscriptDelta):
                await self._events.put(routed_event)
            await self._turn_manager.send(ObserveAsrEvent(event=routed_event))

    def _project_asr_event(self, event):
        if not self._response_active or not self._latest_assistant_text:
            return event
        if isinstance(event, AsrTranscriptDelta):
            projected = project_assistant_echo(
                event.accumulated_text,
                self._latest_assistant_text,
            )
            if projected is None:
                return None
            if projected == event.accumulated_text:
                return event
            return AsrTranscriptDelta(
                context=event.context,
                revision=event.revision,
                delta=projected,
                accumulated_text=projected,
                audio_timestamp_us=event.audio_timestamp_us,
                replaces_previous=True,
            )
        if isinstance(event, AsrEndpointHint):
            projected = project_assistant_echo(event.text, self._latest_assistant_text)
            if projected is None:
                return None
            if projected == event.text:
                return event
            return AsrEndpointHint(
                context=event.context,
                revision=event.revision,
                text=projected,
            )
        return event

    async def _route_turn_manager(self) -> None:
        async for event in self._turn_manager.events():
            if isinstance(event, AsrCommitRequested):
                await self._asr.send(
                    CommitAsrInput(reason=event.reason, context=event.context)
                )
            elif isinstance(event, AsrDiscardRequested):
                await self._asr.send(DiscardAsrInput(reason=event.reason))
            await self._events.put(event)

    async def _guard_route(self, capability: str, route) -> None:
        try:
            await route
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - capability failures are events
            await self._events.put(
                CascadedCapabilityFailed(
                    context=self._context,
                    capability=capability,
                    error=str(error),
                )
            )

    async def events(self) -> AsyncIterator[CascadedInputEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(CascadedInputEvent, event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.gather(
            self._vad.close(),
            self._asr.close(),
            self._turn_manager.close(),
        )
        await self._events.put(_CLOSED)
