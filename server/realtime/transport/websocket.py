"""Translate the existing browser WebSocket frames to the Realtime protocol."""

from __future__ import annotations

import asyncio
import base64
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

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
from server.realtime.protocol.events import SpeechTextAlignment
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
    PlaybackProgressV2,
)

InboundFallback = Callable[[InboundFrame], Awaitable[None]]
InputEpochStartedHandler = Callable[[InputEpochStarted], Awaitable[None]]
ConfirmationDecisionHandler = Callable[[ConfirmationDecisionFrame], Awaitable[None]]


@dataclass(slots=True)
class _PlaybackState:
    speech_id: str
    intended_text: str = ""
    audio_end_us: int = 0
    sample_rate_hz: int | None = None
    next_sequence: int = 0
    terminal_audio_sent: bool = False
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
    ) -> None:
        self._base_context = context
        self._conversation = conversation
        self._transport = transport
        self._inbound_fallback = inbound_fallback
        self._input_epoch_started = input_epoch_started
        self._confirmation_decision_handler = confirmation_decision_handler
        self._generation = max(1, context.generation)
        self._response_text: dict[str, str] = {}
        self._response_spoken: dict[str, str] = {}
        self._response_generation_by_id: dict[str, int] = {}
        self._active_response_id: str | None = None
        self._active_response_context: InteractionContext | None = None
        self._playback_by_generation: dict[int, _PlaybackState] = {}
        self._projection_waiters: dict[str, asyncio.Future[ItemProjected]] = {}
        self._locally_cancelled_generations: set[int] = set()
        self._input_timeline = InputEpochTimeline()
        self._input_format: AudioFormat | None = None
        self._voice_session_sequence = 0

    async def handle_inbound(self, frame: InboundFrame) -> None:
        if isinstance(frame, InputEpochStarted):
            self._input_timeline.start(frame)
            self._input_format = frame.format
            if self._input_epoch_started is None:
                self._voice_session_sequence += 1
                await self._transport.send(
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
        elif (
            isinstance(frame, ConfirmationDecisionFrame)
            and self._confirmation_decision_handler is not None
        ):
            await self._confirmation_decision_handler(frame)
        elif self._inbound_fallback is not None:
            await self._inbound_fallback(frame)

    async def handle_event(self, event: RealtimeEvent) -> None:
        if isinstance(event, ConfirmationRequested):
            await self._transport.send(
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
            interrupted_generation = self._interrupted_generation(
                event.context.generation
            )
            if interrupted_generation is not None:
                self._locally_cancelled_generations.add(interrupted_generation)
                await self._transport.send(
                    AssistantSpeechCancelledFrame(generation=interrupted_generation)
                )
            return
        if isinstance(event, ItemProjected):
            waiter = self._projection_waiters.pop(event.item_id, None)
            if waiter is not None and not waiter.done():
                waiter.set_result(event)
            return
        if isinstance(event, InputTranscriptDelta):
            await self._transport.send(
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
            await self._transport.send(
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
            self._response_text[event.response_id] = ""
            self._response_spoken[event.response_id] = ""
            self._active_response_id = event.response_id
            self._active_response_context = event.context
            self._response_generation_by_id[event.response_id] = (
                event.context.generation
            )
            return
        if isinstance(event, DisplayContentDelta):
            text = self._response_text.get(event.response_id, "") + event.delta
            self._response_text[event.response_id] = text
            await self._transport.send(
                AssistantTextFrame(text=text, generation=event.context.generation)
            )
            return
        if isinstance(event, SpokenContentDelta):
            spoken = self._response_spoken.get(event.response_id, "") + event.delta
            self._response_spoken[event.response_id] = spoken
            await self._transport.send(
                AssistantSpeechTextFrame(
                    text=spoken,
                    generation=event.context.generation,
                )
            )
            playback = self._playback_by_generation.get(event.context.generation)
            if playback is None:
                self._playback_by_generation[event.context.generation] = _PlaybackState(
                    speech_id=f"response:{event.response_id}",
                    intended_text=spoken,
                )
            else:
                playback.intended_text = spoken
            return
        if isinstance(event, SpeechTextAlignment):
            playback = self._playback_by_generation.get(event.context.generation)
            if playback and playback.speech_id == event.speech_id:
                start_us = event.audio_start_us
                if start_us is None:
                    start_us = playback.text_boundaries[-1][0] if playback.text_boundaries else 0
                playback.text_boundaries.append((event.audio_end_us, event.text_end))
                await self._transport.send(AssistantTextAlignmentFrame(
                    generation=event.context.generation, speech_id=event.speech_id,
                    text=playback.intended_text[:event.text_end],
                    audio_start_us=start_us, audio_end_us=event.audio_end_us,
                ))
            return
        if isinstance(event, AudioDelta):
            await self._send_audio(
                generation=event.context.generation,
                speech_id=event.speech_id or f"response:{event.response_id}",
                frame=event.frame,
                sequence=event.response_sequence,
                is_final=event.is_final_for_segment,
            )
            return
        if isinstance(event, SpeechAudioDelta):
            await self._send_audio(
                generation=event.context.generation,
                speech_id=event.speech_id,
                frame=event.frame,
                sequence=event.segment_index + 1,
                is_final=event.is_final_for_segment,
            )
            return
        if isinstance(event, ResponseCompleted):
            playback = self._playback_by_generation.get(event.context.generation)
            if playback and playback.intended_text and playback.audio_end_us > 0 and not playback.text_boundaries:
                # A provider without word timings still has one real utterance
                # span. Display that span on the client playback clock.
                playback.text_boundaries.append((playback.audio_end_us, len(playback.intended_text)))
                await self._transport.send(AssistantTextAlignmentFrame(
                    generation=event.context.generation, speech_id=playback.speech_id,
                    text=playback.intended_text, audio_start_us=0, audio_end_us=playback.audio_end_us,
                ))
            if (
                playback is not None
                and playback.sample_rate_hz is not None
                and not playback.terminal_audio_sent
            ):
                await self._transport.send(
                    AssistantAudioChunkFrame(
                        pcm16_base64="",
                        sample_rate_hz=playback.sample_rate_hz,
                        generation=event.context.generation,
                        speech_id=playback.speech_id,
                        sequence=playback.next_sequence,
                        is_final=True,
                    )
                )
                playback.terminal_audio_sent = True
            await self._transport.send(
                AssistantResponseCompletedFrame(generation=event.context.generation)
            )
            self._clear_response_draft(event.response_id)
            self._response_generation_by_id.pop(event.response_id, None)
            return
        if isinstance(event, ResponseFailed):
            if not self._response_text.get(event.response_id):
                await self._transport.send(
                    AssistantTextFrame(
                        text="刚才没有及时响应，请再说一次。",
                        generation=event.context.generation,
                    )
                )
            await self._transport.send(
                AssistantSpeechCancelledFrame(
                    generation=event.context.generation,
                    reason="failed",
                )
            )
            self._clear_response_draft(event.response_id)
            self._response_generation_by_id.pop(event.response_id, None)
            return
        if isinstance(event, ResponseCancelled):
            cancelled_generation = self._response_generation_by_id.get(
                event.response_id,
                event.context.generation,
            )
            if cancelled_generation not in self._locally_cancelled_generations:
                await self._transport.send(
                    AssistantSpeechCancelledFrame(generation=cancelled_generation)
                )
            self._locally_cancelled_generations.discard(cancelled_generation)
            self._clear_response_draft(event.response_id)
            self._response_generation_by_id.pop(event.response_id, None)

    async def handle_detached(self) -> None:
        """Settle live response work before semantic v2 recovery."""

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
            await self._transport.send(result)
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
        await self._transport.send(result)

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
            await self._transport.send(
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
        generation: int,
        speech_id: str,
        frame: AudioFrame,
        sequence: int,
        is_final: bool,
    ) -> None:
        playback = self._playback_by_generation.setdefault(
            generation,
            _PlaybackState(speech_id=speech_id),
        )
        playback.speech_id = speech_id
        playback.audio_end_us += frame.duration_us
        playback.sample_rate_hz = frame.sample_rate_hz
        playback.next_sequence = max(playback.next_sequence, sequence + 1)
        playback.terminal_audio_sent = playback.terminal_audio_sent or is_final
        await self._transport.send(
            AssistantAudioChunkFrame(
                pcm16_base64=base64.b64encode(frame.data).decode("ascii"),
                sample_rate_hz=frame.sample_rate_hz,
                generation=generation,
                speech_id=speech_id,
                sequence=sequence,
                is_final=is_final,
            )
        )

    async def _report_playback(self, frame: PlaybackProgressFrame) -> None:
        playback = self._playback_by_generation.get(frame.generation)
        if playback is None:
            return
        if frame.started and not frame.finished and not frame.stopped:
            await self._conversation.send(
                ReportPlaybackProgress(
                    command_id=f"playback:{frame.generation}:{playback.speech_id}:started",
                    idempotency_key=f"playback:{frame.generation}:{playback.speech_id}:started",
                    context=self._turn_context(frame.generation),
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
                context=self._turn_context(frame.generation),
                speech_id=playback.speech_id,
                delivered_text_end=delivered_text_end,
                played_audio_end_us=played_audio_end_us,
                precision=precision,
                completed=frame.finished,
                stopped=frame.stopped,
            )
        )
        if frame.finished or frame.stopped:
            self._playback_by_generation.pop(frame.generation, None)

    async def _report_playback_v2(self, frame: PlaybackProgressV2) -> None:
        playback = self._playback_by_generation.get(frame.generation)
        if playback is None or playback.speech_id != frame.speech_id:
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
        if frame.phase == "finished":
            played_audio_end_us = playback.audio_end_us
            delivered_text_end = len(playback.intended_text)
        delivered_text_end = max(playback.delivered_text_end, delivered_text_end)
        playback.delivered_text_end = delivered_text_end
        played_audio_end_us = max(playback.played_audio_end_us, played_audio_end_us)
        playback.played_audio_end_us = played_audio_end_us
        await self._conversation.send(
            ReportPlaybackProgress(
                command_id=(
                    f"playback-v2:{frame.output_epoch}:{frame.speech_id}:{frame.phase}:{frame.played_position_samples}"
                ),
                idempotency_key=(
                    f"playback-v2:{frame.output_epoch}:{frame.speech_id}:{frame.phase}:{frame.played_position_samples}"
                ),
                context=self._turn_context(frame.generation),
                speech_id=frame.speech_id,
                delivered_text_end=delivered_text_end,
                played_audio_end_us=played_audio_end_us,
                precision=PlaybackPrecision.SEGMENT,
                completed=frame.phase == "finished",
                started=frame.phase == "started",
                stopped=frame.phase == "stopped",
            )
        )
        if frame.phase in {"finished", "stopped"}:
            self._playback_by_generation.pop(frame.generation, None)

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
