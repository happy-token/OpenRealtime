"""Translate the existing browser WebSocket frames to the Realtime protocol."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime.protocol import (
    AppendAudio,
    AppendItem,
    AssistantYieldRequested,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    CancelResponse,
    ConfirmationRequested,
    DisplayContentDelta,
    InputTranscriptCompleted,
    InputTranscriptDelta,
    ItemProjected,
    PlaybackPrecision,
    RealtimeConversation,
    RealtimeEvent,
    ReportPlaybackProgress,
    RequestResponse,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechAudioDelta,
    SpokenContentDelta,
)
from server.realtime.protocol.engine import is_output_deliverable
from server.realtime.protocol.events import (
    RealtimeCapabilityFailed,
    SpeechAudioCompleted,
    SpeechTextAlignment,
)
from server.realtime.transport.output_stop import OutputStopObservation
from server.transport.base import TransportAdapter
from server.transport.frames import (
    AssistantAudioChunkFrame,
    AssistantResponseCompletedFrame,
    AssistantSpeechCancelledFrame,
    AssistantSpeechTextFrame,
    AssistantTextAlignmentFrame,
    AssistantTextFrame,
    CancelAssistantResponseFrame,
    ConfirmationDecisionFrame,
    ConfirmationRequestedFrame,
    InboundFrame,
    OutboundFrame,
    PlaybackProgressFrame,
    UserTextFrame,
    UserTranscriptFrame,
    VoiceSessionReadyFrame,
)
from server.voice_session.protocol import (
    AudioFormat,
    AudioGap,
    InputAudioAck,
    InputAudioFrame,
    InputEpochStarted,
    InputEpochTimeline,
    OutputStopResult,
    PlaybackProgressV2,
    VoiceSessionFailureFrame,
)

InboundFallback = Callable[[InboundFrame], Awaitable[None]]
InputEpochStartedHandler = Callable[[InputEpochStarted], Awaitable[None]]
ConfirmationDecisionHandler = Callable[[ConfirmationDecisionFrame], Awaitable[None]]
logger = logging.getLogger(__name__)
_OUTPUT_FAILURE_IO_TIMEOUT_S = .25


@dataclass(frozen=True, slots=True)
class OutputStopSnapshot:
    request: AssistantSpeechCancelledFrame
    state: Literal["STOP_REQUESTED", "STOP_CONFIRMED", "STOP_UNKNOWN"]
    reason: str | None


@dataclass(slots=True)
class _OutputStop:
    request: AssistantSpeechCancelledFrame
    ready: asyncio.Future[bool]
    target_context: InteractionContext | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    requested_ns: int = field(default_factory=time.monotonic_ns)
    received_at: datetime | None = None
    received_ns: int | None = None
    receipt_outcome: Literal["queue_stopped", "unknown", "stale"] | None = None
    played_position_samples: int | None = None
    state: Literal["STOP_REQUESTED", "STOP_CONFIRMED", "STOP_UNKNOWN"] = "STOP_REQUESTED"
    reason: str | None = None
    deadline: asyncio.TimerHandle | None = None


@dataclass(slots=True)
class _PlaybackState:
    speech_id: str
    generation: int
    context: InteractionContext
    intended_text: str = ""
    audio_end_us: int = 0
    audio_samples: int = 0
    sample_rate_hz: int | None = None
    next_sequence: int = 0
    terminal_audio_sent: bool = False
    generation_complete: bool = False
    delivered_text_end: int = 0
    played_audio_end_us: int = 0
    text_boundaries: list[tuple[int, int]] = field(default_factory=list)


class RealtimeWebSocketFrameBridge:
    """Stateful frame mapper owned by one Endpoint Session.

    It contains wire compatibility only. VAD, ASR, turn policy, Brain and TTS
    remain behind the public Realtime Conversation contract.
    """

    def __init__(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
        transport: TransportAdapter,
        inbound_fallback: InboundFallback | None = None,
        input_epoch_started: InputEpochStartedHandler | None = None,
        confirmation_decision_handler: ConfirmationDecisionHandler | None = None,
        output_epoch: str | None = None,
        precise_output_stop: bool = False,
        output_stop_timeout_ms: int = 1500,
        diagnostic_observer: Callable[[object], None] | None = None,
    ) -> None:
        self._base_context = context
        if output_epoch == "":
            raise ValueError("output epoch must be non-empty")
        self._output_epoch = output_epoch or str(uuid.uuid4())
        if output_stop_timeout_ms <= 0:
            raise ValueError("output stop timeout must be positive")
        self._precise_output_stop = precise_output_stop
        self._output_stop_timeout_s = output_stop_timeout_ms / 1000
        self._output_stops: dict[str, _OutputStop] = {}
        self._stop_by_target: dict[tuple[str, int, str], str] = {}
        self._stop_tasks: set[asyncio.Task[None]] = set()
        self._stop_output_failed = False
        self._closed = False
        self._output_failure = asyncio.Event()
        self._failure_notification_started = False
        self._locally_cancelled_speech: set[str] = set()
        self._conversation = conversation
        self._transport = transport
        self._inbound_fallback = inbound_fallback
        self._input_epoch_started = input_epoch_started
        self._confirmation_decision_handler = confirmation_decision_handler
        self._diagnostic_observer = diagnostic_observer
        self._generation = max(1, context.generation)
        self._response_text: dict[str, str] = {}
        self._response_spoken: dict[str, str] = {}
        self._response_generation_by_id: dict[str, int] = {}
        self._active_response_id: str | None = None
        self._active_response_context: InteractionContext | None = None
        self._playback_by_generation: dict[int, _PlaybackState] = {}
        self._playback_by_speech: dict[str, _PlaybackState] = {}
        self._latest_speech_by_generation: dict[int, str] = {}
        self._retired_speech_ids: set[str] = set()
        self._projection_waiters: dict[str, asyncio.Future[ItemProjected]] = {}
        self._locally_cancelled_generations: set[int] = set()
        self._input_timeline = InputEpochTimeline()
        self._input_format: AudioFormat | None = None
        self._voice_session_sequence = 0

    @property
    def output_epoch(self) -> str:
        # EndpointSession survives reattachment; read its rotated epoch on
        # each receipt rather than retaining the initial connection identity.
        return getattr(self._transport, "output_epoch", self._output_epoch)

    async def handle_inbound(self, frame: InboundFrame) -> None:
        if self._closed:
            return
        if isinstance(frame, InputEpochStarted):
            self._input_timeline.start(frame)
            self._input_format = frame.format
            if self._input_epoch_started is None:
                self._voice_session_sequence += 1
                await self._send_frame(
                    VoiceSessionReadyFrame(
                        session_sequence=self._voice_session_sequence,
                        input_epoch=frame.input_epoch,
                    )
                )
            else:
                await self._input_epoch_started(frame)
        elif isinstance(frame, InputAudioFrame):
            await self._append_v2_audio(frame)
        elif isinstance(frame, UserTextFrame):
            await self._append_user_text(frame.text)
        elif isinstance(frame, CancelAssistantResponseFrame):
            await self._cancel_active_response(reason="user_stop", command_prefix="user-stop")
        elif isinstance(frame, PlaybackProgressFrame):
            await self._report_playback(frame)
        elif isinstance(frame, PlaybackProgressV2):
            await self._report_playback_v2(frame)
        elif isinstance(frame, OutputStopResult):
            await self._report_output_stop(frame)
        elif (
            isinstance(frame, ConfirmationDecisionFrame)
            and self._confirmation_decision_handler is not None
        ):
            await self._confirmation_decision_handler(frame)
        elif self._inbound_fallback is not None:
            await self._inbound_fallback(frame)

    async def handle_event(self, event: RealtimeEvent) -> None:
        if self._closed:
            return
        if not is_output_deliverable(self._conversation, event):
            return
        if isinstance(event, RealtimeCapabilityFailed) and event.capability == "semantic_input":
            await self._send_frame(VoiceSessionFailureFrame(
                code="semantic_input_rejected", phase="input", retryable=True,
                session_disposition="close", safe_message=event.error,
            ))
            await self._transport.close()
            return
        if isinstance(event, ConfirmationRequested):
            await self._send_frame(
                ConfirmationRequestedFrame(
                    confirmation_id=event.confirmation_id,
                    action_digest=event.action_digest,
                    summary=event.summary,
                    required_channel=event.required_channel.value,
                    expires_at=event.expires_at,
                    generation=event.context.generation,
                )
            )
            return
        if isinstance(event, AssistantYieldRequested):
            interrupted_generation = (
                self._response_generation_by_id.get(event.context.response_id,
                    next((generation for generation, playback in self._playback_by_generation.items()
                          if playback.speech_id == f"response:{event.context.response_id}"), None))
                if event.context.response_id is not None
                else self._interrupted_generation(event.context.generation)
            )
            if (interrupted_generation is not None and event.context.response_id is not None
                    and not self._response_is_current(interrupted_generation, event.context.response_id)):
                return
            if interrupted_generation is not None:
                playback = self._playback_by_generation.get(interrupted_generation)
                await self._request_output_stop(interrupted_generation,
                    playback.speech_id if playback else None)
            return
        if isinstance(event, ItemProjected):
            waiter = self._projection_waiters.pop(event.item_id, None)
            if waiter is not None and not waiter.done():
                waiter.set_result(event)
            return
        if isinstance(event, InputTranscriptDelta):
            await self._send_frame(
                UserTranscriptFrame(
                    text=event.text,
                    generation=event.context.generation,
                    is_final=False,
                    turn_id=event.context.turn_id,
                    transcript_revision=event.transcript_revision,
                )
            )
            return
        if isinstance(event, InputTranscriptCompleted):
            await self._send_frame(
                UserTranscriptFrame(
                    text=event.text,
                    generation=event.context.generation,
                    is_final=True,
                    turn_id=event.context.turn_id,
                    transcript_revision=event.transcript_revision,
                )
            )
            self._advance_generation(event.context.generation)
            return
        if isinstance(event, ResponseStarted):
            if self._begin_playback(event.context.generation, f"response:{event.response_id}",
                    context=replace(event.context, response_id=event.response_id)) is None:
                return
            self._response_text[event.response_id] = ""
            self._response_spoken[event.response_id] = ""
            self._active_response_id = event.response_id
            self._active_response_context = event.context
            self._response_generation_by_id[event.response_id] = (
                event.context.generation
            )
            return
        if isinstance(event, DisplayContentDelta):
            if not self._response_is_current(event.context.generation, event.response_id):
                return
            text = self._response_text.get(event.response_id, "") + event.delta
            self._response_text[event.response_id] = text
            await self._send_frame(
                AssistantTextFrame(text=text, generation=event.context.generation)
            )
            return
        if isinstance(event, SpokenContentDelta):
            playback = self._begin_playback(event.context.generation, f"response:{event.response_id}",
                context=replace(event.context, response_id=event.response_id))
            if playback is None:
                return
            spoken = self._response_spoken.get(event.response_id, "") + event.delta
            self._response_spoken[event.response_id] = spoken
            await self._send_frame(
                AssistantSpeechTextFrame(
                    text=spoken,
                    generation=event.context.generation,
                )
            )
            playback.intended_text = spoken
            return
        if isinstance(event, SpeechTextAlignment):
            playback = self._playback_by_generation.get(event.context.generation)
            if playback and playback.speech_id == event.speech_id:
                start_us = event.audio_start_us
                if start_us is None:
                    start_us = playback.text_boundaries[-1][0] if playback.text_boundaries else 0
                playback.text_boundaries.append((event.audio_end_us, event.text_end))
                await self._send_frame(AssistantTextAlignmentFrame(
                    generation=event.context.generation, speech_id=event.speech_id,
                    text=playback.intended_text[:event.text_end],
                    audio_start_us=start_us, audio_end_us=event.audio_end_us,
                ))
            return
        if isinstance(event, AudioDelta):
            await self._send_audio(
                source=event,
                generation=event.context.generation,
                speech_id=event.speech_id or f"response:{event.response_id}",
                frame=event.frame,
                sequence=event.response_sequence,
            )
            return
        if isinstance(event, SpeechAudioDelta):
            await self._send_audio(
                source=event,
                generation=event.context.generation,
                speech_id=event.speech_id,
                frame=event.frame,
                sequence=event.segment_index + 1,
            )
            return
        if isinstance(event, SpeechAudioCompleted):
            await self._send_terminal_audio(event.context.generation, event.speech_id)
            return
        if isinstance(event, ResponseCompleted):
            if f"response:{event.response_id}" in self._retired_speech_ids:
                self._clear_response_draft(event.response_id)
                self._response_generation_by_id.pop(event.response_id, None)
                return
            playback = self._playback_by_generation.get(event.context.generation)
            if playback is not None and playback.speech_id != f"response:{event.response_id}":
                await self._send_terminal_audio(event.context.generation, f"response:{event.response_id}")
                self._clear_response_draft(event.response_id)
                self._response_generation_by_id.pop(event.response_id, None)
                return
            if playback and playback.intended_text and playback.audio_end_us > 0 and not playback.text_boundaries:
                # A provider without word timings still has one real utterance
                # span. Display that span on the client playback clock.
                playback.text_boundaries.append((playback.audio_end_us, len(playback.intended_text)))
                await self._send_frame(AssistantTextAlignmentFrame(
                    generation=event.context.generation, speech_id=playback.speech_id,
                    text=playback.intended_text, audio_start_us=0, audio_end_us=playback.audio_end_us,
                ))
            await self._send_terminal_audio(event.context.generation, f"response:{event.response_id}")
            await self._send_frame(
                AssistantResponseCompletedFrame(generation=event.context.generation)
            )
            self._clear_response_draft(event.response_id)
            self._response_generation_by_id.pop(event.response_id, None)
            return
        if isinstance(event, ResponseFailed):
            if not self._response_is_current(event.context.generation, event.response_id):
                self._clear_response_draft(event.response_id)
                self._response_generation_by_id.pop(event.response_id, None)
                return
            if not self._response_text.get(event.response_id):
                await self._send_frame(
                    AssistantTextFrame(
                        text="刚才没有及时响应，请再说一次。",
                        generation=event.context.generation,
                    )
                )
            await self._request_output_stop(event.context.generation, f"response:{event.response_id}", "failed",
                target_context=replace(event.context, response_id=event.response_id))
            self._clear_response_draft(event.response_id)
            self._response_generation_by_id.pop(event.response_id, None)
            return
        if isinstance(event, ResponseCancelled):
            cancelled_generation = self._response_generation_by_id.get(
                event.response_id,
                event.context.generation,
            )
            if not self._response_is_current(cancelled_generation, event.response_id):
                self._clear_response_draft(event.response_id)
                self._response_generation_by_id.pop(event.response_id, None)
                return
            if cancelled_generation not in self._locally_cancelled_generations:
                await self._request_output_stop(cancelled_generation, f"response:{event.response_id}",
                    target_context=replace(event.context, response_id=event.response_id))
            self._locally_cancelled_generations.discard(cancelled_generation)
            self._clear_response_draft(event.response_id)
            self._response_generation_by_id.pop(event.response_id, None)

    async def handle_detached(self) -> None:
        """Settle live response work before semantic v2 recovery."""

        for stop in self._output_stops.values():
            if not stop.ready.done():
                self._fail_stop_handoff(stop, "transport_detached")
        if self._stop_output_failed:
            await self._notify_stop_failure("transport_detached")
            return
        response_id = self._active_response_id
        response_context = self._active_response_context
        if response_id is None or response_context is None:
            return
        try:
            await self._conversation.send(
                CancelResponse(
                    command_id=f"transport-detached:{response_id}",
                    idempotency_key=f"transport-detached:{response_id}",
                    context=replace(response_context, response_id=response_id),
                    response_id=response_id,
                    reason="transport_detached",
                )
            )
        except ValueError as error:
            if (
                "not active" not in str(error)
                and "identity is not active" not in str(error)
            ):
                raise
        finally:
            self._clear_response_draft(response_id)

    async def _append_v2_audio(self, frame: InputAudioFrame) -> None:
        audio_format = self._input_format
        if audio_format is None:
            raise ValueError("input audio frame arrived before its epoch")
        pcm = base64.b64decode(frame.pcm16_base64, validate=True)
        expected_bytes = frame.sample_count * 2 * audio_format.channels
        if len(pcm) != expected_bytes:
            raise ValueError("input audio payload does not match declared sample count")
        result = self._input_timeline.accept(frame)
        if result is None:
            return
        if isinstance(result, AudioGap):
            await self._send_frame(result)
            return
        assert isinstance(result, InputAudioAck)
        duration_us = round(frame.sample_count * 1_000_000 / audio_format.sample_rate_hz)
        timestamp_us = round(frame.start_sample * 1_000_000 / audio_format.sample_rate_hz)
        audio = AudioFrame(
            stream_id=(
                f"browser:{self._base_context.voice_session_id}:{frame.input_epoch}"
            ),
            sequence=frame.sequence,
            timestamp_us=timestamp_us,
            duration_us=duration_us,
            encoding=AudioEncoding.PCM_S16LE,
            sample_rate_hz=audio_format.sample_rate_hz,
            channels=audio_format.channels,
            data=pcm,
        )
        await self._conversation.send(
            AppendAudio(
                command_id=f"audio:{frame.input_epoch}:{frame.sequence}",
                idempotency_key=f"audio:{frame.input_epoch}:{frame.sequence}",
                context=self._turn_context(self._generation),
                frame=audio,
            )
        )
        await self._send_frame(result)

    async def _append_user_text(self, text: str) -> None:
        normalized = text.strip()
        if not normalized:
            return
        await self._cancel_active_response(reason="text_barge_in", command_prefix="text-barge-in")
        context = self._turn_context(self._generation)
        item_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        projected = loop.create_future()
        self._projection_waiters[item_id] = projected
        try:
            await self._conversation.send(
                AppendItem(
                    command_id=f"append:{item_id}",
                    idempotency_key=f"append:{item_id}",
                    context=context,
                    draft=ConversationItemDraft(
                        item_id=item_id,
                        context=context,
                        kind=ConversationItemKind.USER_INPUT,
                        status=ConversationItemStatus.COMPLETED,
                        producer="realtime-websocket-transport",
                        content=(TextContent(normalized),),
                    ),
                )
            )
            projection = await projected
            response_id = str(uuid.uuid4())
            await self._conversation.send(
                RequestResponse(
                    command_id=f"respond:{response_id}",
                    idempotency_key=f"respond:{response_id}",
                    context=replace(context, response_id=response_id),
                    response_id=response_id,
                    minimum_thread_sequence=projection.thread_sequence,
                )
            )
            self._active_response_id = response_id
            self._active_response_context = replace(context, response_id=response_id)
            await self._send_frame(
                UserTranscriptFrame(
                    text=normalized,
                    generation=context.generation,
                    is_final=True,
                    turn_id=context.turn_id,
                )
            )
            self._advance_generation(context.generation)
        finally:
            self._projection_waiters.pop(item_id, None)

    async def _cancel_active_response(self, *, reason: str, command_prefix: str) -> None:
        response_id = self._active_response_id
        response_context = self._active_response_context
        if response_id is None or response_context is None:
            return
        generation = self._generation
        try:
            await self._conversation.send(
                CancelResponse(
                    command_id=f"{command_prefix}:{response_id}:{generation}",
                    idempotency_key=f"{command_prefix}:{response_id}:{generation}",
                    context=replace(response_context, response_id=response_id),
                    response_id=response_id,
                    reason=reason,
                )
            )
        except ValueError as error:
            if "not active" not in str(error) and "identity is not active" not in str(error):
                raise
        finally:
            if self._active_response_id == response_id:
                self._active_response_id = None
                self._active_response_context = None

    async def _send_audio(
        self,
        *,
        source: AudioDelta | SpeechAudioDelta,
        generation: int,
        speech_id: str,
        frame: AudioFrame,
        sequence: int,
    ) -> None:
        if generation in self._locally_cancelled_generations or speech_id in self._locally_cancelled_speech:
            return
        if not await self._wait_output_stops():
            return
        if not is_output_deliverable(self._conversation, source):
            return
        if self._closed or generation in self._locally_cancelled_generations or speech_id in self._locally_cancelled_speech:
            return
        playback = self._begin_playback(generation, speech_id,
            context=replace(source.context, response_id=source.response_id) if isinstance(source, AudioDelta) else source.context)
        if playback is None or playback.generation_complete:
            return
        if playback.sample_rate_hz is not None and playback.sample_rate_hz != frame.sample_rate_hz:
            raise ValueError("sample rate cannot change within one speech")
        playback.audio_end_us += frame.duration_us
        playback.audio_samples += len(frame.data) // (2 * frame.channels)
        playback.sample_rate_hz = frame.sample_rate_hz
        playback.next_sequence = max(playback.next_sequence, sequence + 1)
        await self._send_frame(
            AssistantAudioChunkFrame(
                pcm16_base64=base64.b64encode(frame.data).decode("ascii"),
                sample_rate_hz=frame.sample_rate_hz,
                generation=generation,
                speech_id=speech_id,
                sequence=sequence,
                # A provider segment boundary is not the end of the reply.
                is_final=False,
            )
        )

    async def _send_terminal_audio(self, generation: int, speech_id: str) -> None:
        if self._closed or speech_id in self._locally_cancelled_speech:
            return
        playback = self._playback_by_speech.get(speech_id)
        if playback is None or playback.generation != generation:
            return
        playback.generation_complete = True
        if (self._playback_by_generation.get(generation) is not playback
                or playback.sample_rate_hz is None or playback.terminal_audio_sent):
            return
        # Publish terminal state before an awaited send can expose its frame
        # and interleave the client's completion receipt.
        playback.terminal_audio_sent = True
        await self._send_frame(AssistantAudioChunkFrame(
            pcm16_base64="", sample_rate_hz=playback.sample_rate_hz,
            generation=generation, speech_id=playback.speech_id,
            sequence=playback.next_sequence, is_final=True,
        ))

    def _response_is_current(self, generation: int, response_id: str) -> bool:
        speech_id = f"response:{response_id}"
        if speech_id in self._retired_speech_ids:
            return False
        latest = self._latest_speech_by_generation.get(generation)
        return latest is None or latest == speech_id

    def output_stop_snapshot(self) -> tuple[OutputStopSnapshot, ...]:
        return tuple(OutputStopSnapshot(stop.request, stop.state, stop.reason)
                     for stop in self._output_stops.values())

    async def wait_for_output_failure(self) -> None:
        """Wake the owning endpoint even if graceful transport close stalls."""
        await self._output_failure.wait()

    async def _send_frame(self, frame: OutboundFrame) -> None:
        if not self._closed:
            await self._transport.send(frame)

    async def _request_output_stop(self, generation: int, speech_id: str | None,
                                   reason: Literal["interrupted", "failed", "cancelled"] = "interrupted", *,
                                   target_context: InteractionContext | None = None) -> None:
        if self._closed:
            return
        if not self._precise_output_stop or speech_id is None:
            self._locally_cancelled_generations.add(generation)
            try:
                await asyncio.wait_for(self._send_frame(
                    AssistantSpeechCancelledFrame(generation=generation, reason=reason)),
                    timeout=self._output_stop_timeout_s)
            except Exception:
                logger.warning("Legacy output stop command could not reach client", exc_info=True)
                self._stop_output_failed = True
                await self._notify_stop_failure("stop_request_send_failed")
            return
        self._locally_cancelled_speech.add(speech_id)
        key = (self.output_epoch, generation, speech_id)
        if key in self._stop_by_target:
            return
        if len(self._output_stops) >= 512:
            self._stop_output_failed = True
            await self._notify_stop_failure("stop_operation_budget")
            return
        loop = asyncio.get_running_loop()
        request = AssistantSpeechCancelledFrame(generation=generation, reason=reason,
            output_epoch=self.output_epoch, speech_id=speech_id, stop_command_id=str(uuid.uuid4()))
        assert request.stop_command_id is not None
        playback = self._playback_by_speech.get(speech_id)
        stop = _OutputStop(request=request, ready=loop.create_future(),
            target_context=playback.context if playback is not None else target_context)
        self._output_stops[request.stop_command_id] = stop
        self._stop_by_target[key] = request.stop_command_id
        stop.deadline = loop.call_later(self._output_stop_timeout_s, self._expire_output_stop, stop)
        self._observe_output_stop(stop, "requested")
        try:
            await asyncio.wait_for(self._send_frame(request), timeout=self._output_stop_timeout_s)
        except asyncio.CancelledError:
            if not self._closed:
                self._fail_stop_handoff(stop, "stop_request_send_cancelled")
                self._schedule_stop_failure("stop_request_send_cancelled")
            raise
        except Exception:
            logger.warning("Output stop command could not reach client", exc_info=True)
            self._fail_stop_handoff(stop, "stop_request_send_failed")
            await self._notify_stop_failure("stop_request_send_failed")

    def _expire_output_stop(self, stop: _OutputStop) -> None:
        if stop.state != "STOP_REQUESTED":
            return
        self._settle_stop_unknown(stop, "receipt_deadline")
        self._schedule_stop_failure("receipt_deadline")

    def _schedule_stop_failure(self, reason: str) -> None:
        if self._failure_notification_started or self._stop_tasks:
            return
        task = asyncio.create_task(self._notify_stop_failure(reason))
        self._stop_tasks.add(task)
        task.add_done_callback(self._stop_task_done)

    def _stop_task_done(self, task: asyncio.Task[None]) -> None:
        self._stop_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Output stop failure notification failed", exc_info=task.exception())

    def _settle_stop_unknown(self, stop: _OutputStop, reason: str) -> None:
        self._fail_stop_handoff(stop, reason)

    def _fail_stop_handoff(self, stop: _OutputStop, reason: str) -> None:
        # A received queue-stop acknowledgement remains a historical fact;
        # failure revokes the separate permission to deliver subsequent audio.
        if stop.state == "STOP_REQUESTED":
            stop.state = "STOP_UNKNOWN"
        if stop.reason is None:
            stop.reason = reason
        self._stop_output_failed = True
        if stop.deadline is not None:
            stop.deadline.cancel()
        if not stop.ready.done():
            stop.ready.set_result(False)
            self._observe_output_stop(stop, "handoff_failed")

    def _observe_output_stop(self, stop: _OutputStop, phase: Literal["requested", "receipt", "handoff_ready", "handoff_failed"]) -> None:
        if self._diagnostic_observer is None:
            return
        if phase == "requested":
            occurred_at, monotonic_ns = stop.requested_at, stop.requested_ns
        elif phase == "receipt":
            assert stop.received_at is not None and stop.received_ns is not None
            occurred_at, monotonic_ns = stop.received_at, stop.received_ns
        else:
            occurred_at, monotonic_ns = datetime.now(UTC), time.monotonic_ns()
        observation = OutputStopObservation(request=stop.request, target_context=stop.target_context,
            phase=phase, state=stop.state, reason=stop.reason, receipt_outcome=stop.receipt_outcome,
            played_position_samples=stop.played_position_samples, requested_at=stop.requested_at,
            received_at=stop.received_at, occurred_at=occurred_at, requested_ns=stop.requested_ns,
            received_ns=stop.received_ns, monotonic_ns=monotonic_ns, timeout_ms=self._output_stop_timeout_s * 1000)
        try:
            self._diagnostic_observer(observation)
        except (Exception, asyncio.CancelledError):
            # A synchronous diagnostic callback cannot cancel the control path.
            # Cancellation of the owning task still propagates at transport awaits.
            logger.warning("Output stop observation could not be recorded", exc_info=True)

    async def _notify_stop_failure(self, reason: str) -> None:
        if self._failure_notification_started:
            return
        self._failure_notification_started = True
        self._closed = True
        try:
            # One failure notice may cross the closed latch; ordinary frames
            # all use _send_frame and cannot start another send after closure.
            await asyncio.wait_for(self._transport.send(VoiceSessionFailureFrame(
                code="output_stop_unconfirmed", phase="output", retryable=True,
                session_disposition="close", safe_message="无法确认音频已经停止，请重新打开页面后开始会话。")),
                timeout=_OUTPUT_FAILURE_IO_TIMEOUT_S)
        except Exception:
            logger.warning("Stop failure could not reach client: %s", reason, exc_info=True)
        finally:
            try:
                await asyncio.wait_for(self._transport.close(), timeout=_OUTPUT_FAILURE_IO_TIMEOUT_S)
            except Exception:
                logger.warning("Stop failure transport close did not finish: %s", reason, exc_info=True)
            finally:
                # Endpoint pumps must be cancelled by their owner even when
                # cancelling a graceful close didn't wake transport.receive.
                self._output_failure.set()

    async def _wait_output_stops(self) -> bool:
        while True:
            if self._closed or self._stop_output_failed:
                return False
            stops = tuple(self._output_stops.values())
            for stop in stops:
                if not stop.ready.done() and stop.request.output_epoch != self.output_epoch:
                    self._fail_stop_handoff(stop, "output_epoch_changed")
                    self._schedule_stop_failure("output_epoch_changed")
                if not await asyncio.shield(stop.ready):
                    return False
            if self._closed or self._stop_output_failed:
                return False
            if all(stop.ready.done() for stop in self._output_stops.values()):
                return True

    async def _report_output_stop(self, result: OutputStopResult) -> None:
        stop = self._output_stops.get(result.stop_command_id)
        if stop is None or stop.state != "STOP_REQUESTED" or result.output_epoch != self.output_epoch:
            return
        request = stop.request
        if (result.output_epoch, result.speech_id, result.generation) != (
                request.output_epoch, request.speech_id, request.generation):
            return
        stop.received_at, stop.received_ns = datetime.now(UTC), time.monotonic_ns()
        stop.receipt_outcome = result.outcome
        stop.played_position_samples = result.played_position_samples
        if result.outcome != "queue_stopped":
            self._observe_output_stop(stop, "receipt")
            self._settle_stop_unknown(stop, result.outcome)
            await self._notify_stop_failure(result.outcome)
            return
        stop.state = "STOP_CONFIRMED"
        self._observe_output_stop(stop, "receipt")
        if stop.deadline is not None:
            stop.deadline.cancel()
        assert result.played_position_samples is not None
        try:
            await asyncio.wait_for(self._report_playback_v2(PlaybackProgressV2(
                output_epoch=result.output_epoch, speech_id=result.speech_id, generation=result.generation,
                phase="stopped", played_position_samples=result.played_position_samples)),
                timeout=self._output_stop_timeout_s)
        except asyncio.CancelledError:
            self._fail_stop_handoff(stop, "playback_projection_cancelled")
            if not self._closed:
                self._schedule_stop_failure("playback_projection_cancelled")
            raise
        except TimeoutError:
            self._fail_stop_handoff(stop, "playback_projection_deadline")
            await self._notify_stop_failure("playback_projection_deadline")
            raise
        except Exception:
            self._fail_stop_handoff(stop, "playback_projection_failed")
            await self._notify_stop_failure("playback_projection_failed")
            raise
        if stop.ready.done():
            return
        if self._closed or stop.request.output_epoch != self.output_epoch:
            self._fail_stop_handoff(stop, "session_closed" if self._closed else "output_epoch_changed")
            if not self._closed:
                self._schedule_stop_failure("output_epoch_changed")
            return
        if not stop.ready.done():
            stop.ready.set_result(True)
            self._observe_output_stop(stop, "handoff_ready")

    def begin_close(self) -> None:
        """Declare normal shutdown before cancellation reaches pending projections."""
        self._closed = True
        self._output_failure.set()
        for stop in self._output_stops.values():
            if stop.deadline is not None:
                stop.deadline.cancel()
            if not stop.ready.done():
                self._fail_stop_handoff(stop, "session_closed")

    async def close(self) -> None:
        self.begin_close()
        tasks = tuple(self._stop_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _begin_playback(self, generation: int, speech_id: str, *, context: InteractionContext) -> _PlaybackState | None:
        if speech_id in self._retired_speech_ids:
            return None
        existing = self._playback_by_speech.get(speech_id)
        if existing is not None:
            if existing.generation != generation:
                raise ValueError("speech identity was reused by another generation")
            return existing if self._playback_by_generation.get(generation) is existing else None
        playback = _PlaybackState(speech_id=speech_id, generation=generation, context=context)
        self._playback_by_speech[speech_id] = playback
        self._playback_by_generation[generation] = playback
        self._latest_speech_by_generation[generation] = speech_id
        return playback

    def _retire_playback(self, playback: _PlaybackState) -> None:
        self._retired_speech_ids.add(playback.speech_id)
        self._playback_by_speech.pop(playback.speech_id, None)
        if self._playback_by_generation.get(playback.generation) is playback:
            self._playback_by_generation.pop(playback.generation, None)

    async def _report_playback(self, frame: PlaybackProgressFrame) -> None:
        playback = self._playback_by_generation.get(frame.generation)
        if playback is None:
            return
        if frame.started and not frame.finished and not frame.stopped:
            await self._conversation.send(
                ReportPlaybackProgress(
                    command_id=f"playback:{frame.generation}:{playback.speech_id}:started",
                    idempotency_key=f"playback:{frame.generation}:{playback.speech_id}:started",
                    context=playback.context,
                    speech_id=playback.speech_id,
                    delivered_text_end=0,
                    played_audio_end_us=0,
                    precision=PlaybackPrecision.SEGMENT,
                    completed=False,
                    started=True,
                )
            )
            return
        if not frame.finished and not frame.stopped and frame.played_audio_end_us is None:
            return
        if frame.finished:
            played_audio_end_us = playback.audio_end_us
            delivered_text_end = len(playback.intended_text)
            precision = PlaybackPrecision.SEGMENT
        else:
            played_audio_end_us = min(
                frame.played_audio_end_us or 0,
                playback.audio_end_us,
            )
            delivered_text_end = max(
                (text_end for audio_end, text_end in playback.text_boundaries
                 if audio_end <= played_audio_end_us), default=0,
            )
            precision = (
                PlaybackPrecision.ESTIMATED
                if frame.played_audio_end_us is not None
                else PlaybackPrecision.SEGMENT
            )
        delivered_text_end = max(playback.delivered_text_end, delivered_text_end)
        playback.delivered_text_end = delivered_text_end
        played_audio_end_us = max(playback.played_audio_end_us, played_audio_end_us)
        playback.played_audio_end_us = played_audio_end_us
        await self._conversation.send(
            ReportPlaybackProgress(
                command_id=f"playback:{frame.generation}:{playback.speech_id}:{'done' if frame.finished else 'stop' if frame.stopped else f'progress:{played_audio_end_us}'}",
                idempotency_key=(
                    f"playback:{frame.generation}:{playback.speech_id}:{'done' if frame.finished else 'stop' if frame.stopped else f'progress:{played_audio_end_us}'}"
                ),
                context=playback.context,
                speech_id=playback.speech_id,
                delivered_text_end=delivered_text_end,
                played_audio_end_us=played_audio_end_us,
                precision=precision,
                completed=frame.finished,
                stopped=frame.stopped,
            )
        )
        if frame.finished or frame.stopped:
            self._retire_playback(playback)

    async def _report_playback_v2(self, frame: PlaybackProgressV2) -> None:
        if frame.output_epoch != self.output_epoch:
            return
        playback = self._playback_by_speech.get(frame.speech_id)
        if playback is None or playback.generation != frame.generation:
            return
        sample_rate_hz = playback.sample_rate_hz
        if sample_rate_hz is None:
            return
        played_audio_end_us = min(
            round(frame.played_position_samples * 1_000_000 / sample_rate_hz),
            playback.audio_end_us,
        )
        delivered_text_end = max(
            (text_end for audio_end, text_end in playback.text_boundaries
             if audio_end <= played_audio_end_us), default=0,
        )
        completed = (frame.phase == "finished" and playback.generation_complete
                     and frame.played_position_samples >= playback.audio_samples)
        if completed:
            played_audio_end_us = playback.audio_end_us
            delivered_text_end = len(playback.intended_text)
        delivered_text_end = max(playback.delivered_text_end, delivered_text_end)
        playback.delivered_text_end = delivered_text_end
        played_audio_end_us = max(playback.played_audio_end_us, played_audio_end_us)
        playback.played_audio_end_us = played_audio_end_us
        await self._conversation.send(
            ReportPlaybackProgress(
                command_id=(
                    f"playback-v2:{frame.output_epoch}:{frame.speech_id}:{frame.phase}:{frame.played_position_samples}:{delivered_text_end}:{played_audio_end_us}:{int(completed)}"
                ),
                idempotency_key=(
                    f"playback-v2:{frame.output_epoch}:{frame.speech_id}:{frame.phase}:{frame.played_position_samples}:{delivered_text_end}:{played_audio_end_us}:{int(completed)}"
                ),
                context=playback.context,
                speech_id=frame.speech_id,
                delivered_text_end=delivered_text_end,
                played_audio_end_us=played_audio_end_us,
                precision=PlaybackPrecision.SEGMENT,
                completed=completed,
                started=frame.phase == "started",
                stopped=frame.phase == "stopped",
            )
        )
        if completed or frame.phase == "stopped":
            self._retire_playback(playback)

    def _turn_context(self, generation: int) -> InteractionContext:
        return replace(
            self._base_context,
            turn_id=f"turn-{generation}",
            generation=generation,
            response_id=None,
        )

    def _advance_generation(self, completed_generation: int) -> None:
        self._generation = max(self._generation, completed_generation + 1)

    def _interrupted_generation(self, incoming_generation: int) -> int | None:
        """Resolve the assistant generation interrupted by a new user turn."""

        active = self._active_response_context
        if active is not None and active.generation < incoming_generation:
            return active.generation
        candidates = (
            generation
            for generation in self._playback_by_generation
            if generation < incoming_generation
        )
        return max(candidates, default=None)

    def _clear_response_draft(self, response_id: str) -> None:
        self._response_text.pop(response_id, None)
        self._response_spoken.pop(response_id, None)
        if self._active_response_id == response_id:
            self._active_response_id = None
            self._active_response_context = None
