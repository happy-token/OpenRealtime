"""Cascaded implementation of the stateful Realtime Conversation seam."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, is_dataclass, replace
from datetime import UTC, datetime
from typing import cast

logger = logging.getLogger(__name__)

from server.conversation_journal import (
    AssistantContent,
    ConversationItem,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.playback import CurrentSentencePermit
from server.core.turn_content import TurnContent
from server.realtime.capabilities import (
    AppendTtsText,
    AsrTranscriptDelta,
    BrainCapabilityProvider,
    BrainCapabilitySession,
    BrainDelegationRequested,
    BrainResponseCompleted,
    BrainResponseFailed,
    BrainResponseStarted,
    BrainTextDelta,
    BrainToolRequested,
    CancelBrainResponse,
    CancelTts,
    CascadedCapabilityFailed,
    CascadedInputPipeline,
    CommitTts,
    RequestBrainResponse,
    SpeechRenderer,
    StartTts,
    SubmitBrainToolResult,
    TtsAudioFrame,
    TtsCancelled,
    TtsCapabilityProvider,
    TtsCapabilitySession,
    TtsCompleted,
    TtsFailed,
    TtsTextAlignment,
    UserTurnCommitted,
    resolve_spoken_content,
)
from server.realtime.capabilities import (
    AssistantYieldRequested as CapabilityAssistantYieldRequested,
)
from server.realtime.capabilities import (
    DialogueStateChanged as CapabilityDialogueStateChanged,
)
from server.realtime.capabilities.asr import AsrCapabilityProvider
from server.realtime.capabilities.turn_manager import (
    SemanticInputRejected,
    TurnManagerCapabilityProvider,
)
from server.realtime.capabilities.vad import VadCapabilityProvider
from server.realtime.errors import ContextVisibilityError
from server.realtime.plugins import AudioPluginGraph
from server.realtime.profile import EngineKind, PluginKind, ResolvedRealtimeProfile
from server.realtime.protocol.commands import (
    AppendAudio,
    AppendSpeechText,
    CancelResponse,
    CancelSpeech,
    CommitSpeech,
    DeliverItem,
    DeliveryMode,
    InterruptedContextPolicy,
    ProjectCommittedItem,
    RealtimeCommand,
    RecordOutputStop,
    ReportPlaybackProgress,
    RequestResponse,
    SpeechContextPolicy,
    StartSpeech,
)
from server.realtime.protocol.engine import VERSIONED_OUTPUT_EVENTS
from server.realtime.protocol.events import (
    AgentDelegationRequestProposed,
    AssistantYieldRequested,
    AudioDelta,
    AudioPluginDiagnostic,
    DialogueStateChanged,
    DisplayContentDelta,
    InputTranscriptCompleted,
    InputTranscriptDelta,
    ItemDeliveryCancelled,
    ItemDeliveryCompleted,
    ItemDeliveryFailed,
    ItemDeliveryQueued,
    ItemDeliveryStarted,
    ItemDisplayPresented,
    ItemProjected,
    RealtimeCapabilityFailed,
    RealtimeEvent,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechAudioCompleted,
    SpeechAudioDelta,
    SpeechPlaybackProgress,
    SpeechStarted,
    SpeechTextAccepted,
    SpeechTextAlignment,
    SpeechTextCommitted,
    SpokenContentDelta,
    ToolRequested,
)
from server.realtime.provider_latency import ProviderLatencyObserver, TimedTtsSession
from server.realtime.scope import conversation_scope
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryRecord,
    SpeechDeliveryStatus,
    SpeechDeliveryStore,
    SpeechLifecycle,
    project_assistant_context,
)
from server.voice_session.context import (
    FullConversationContextProjector,
    ModelContextProjector,
    SummarySourceChangedError,
    digest_source_items,
)

_CLOSED = object()
_PLAYBACK_COMPLETION_WATCHDOG_S = 30.0
class CascadedCapabilityError(RuntimeError):
    pass


class _FirstResponseTextDeadlineExceeded(RuntimeError):
    pass


class CascadedRealtimeEngine:
    def __init__(
        self,
        *,
        vad: VadCapabilityProvider,
        asr: AsrCapabilityProvider,
        turn_manager: TurnManagerCapabilityProvider,
        brain: BrainCapabilityProvider,
        speech_renderer: SpeechRenderer,
        tts: TtsCapabilityProvider,
        event_queue_size: int = 64,
        response_timeout_s: float = 30,
        response_first_text_timeout_s: float = 5,
        response_cancel_timeout_s: float = 0.8,
        pseudonymization_key: str | None = None,
        speech_deliveries: SpeechDeliveryStore | None = None,
        context_projector_factory: Callable[[], ModelContextProjector] | None = None,
        provider_timing: ProviderLatencyObserver | None = None,
    ) -> None:
        if event_queue_size < 1:
            raise ValueError("event_queue_size must be positive")
        if response_timeout_s <= 0:
            raise ValueError("response_timeout_s must be positive")
        if response_first_text_timeout_s <= 0:
            raise ValueError("response_first_text_timeout_s must be positive")
        if response_cancel_timeout_s <= 0:
            raise ValueError("response_cancel_timeout_s must be positive")
        self._vad = vad
        self._asr = asr
        self._turn_manager = turn_manager
        self._brain = brain
        self._speech_renderer = speech_renderer
        self._tts = tts
        self._event_queue_size = event_queue_size
        self._response_timeout_s = response_timeout_s
        self._response_first_text_timeout_s = response_first_text_timeout_s
        self._response_cancel_timeout_s = response_cancel_timeout_s
        self._pseudonymization_key = pseudonymization_key
        self._speech_deliveries = speech_deliveries
        self._context_projector_factory = (
            context_projector_factory or FullConversationContextProjector
        )
        self._provider_timing = provider_timing

    async def open(
        self,
        *,
        context: InteractionContext,
        profile: ResolvedRealtimeProfile | None,
    ) -> CascadedRealtimeConversation:
        if profile is not None and profile.engine_kind is not EngineKind.CASCADED:
            raise ValueError("CascadedRealtimeEngine requires a cascaded profile")
        vad = _profile_provider(profile, PluginKind.VAD, self._vad)
        asr = _profile_provider(profile, PluginKind.ASR, self._asr)
        turn_manager = _profile_provider(
            profile, PluginKind.TURN_MANAGER, self._turn_manager
        )
        brain_provider = _profile_provider(profile, PluginKind.BRAIN, self._brain)
        speech_renderer = _profile_binding(
            profile, PluginKind.SPEECH_RENDERER, self._speech_renderer
        )
        tts_provider = _profile_provider(profile, PluginKind.TTS, self._tts)
        audio_graph = None
        if profile is not None and any(
            plugin.selection.slot
            in {
                PluginKind.AUDIO_PROCESSOR,
                PluginKind.AUDIO_ANALYZER,
                PluginKind.AUDIO_SINK,
            }
            for plugin in profile.plugins
        ):
            if not self._pseudonymization_key:
                raise ValueError(
                    "pseudonymization_key is required when a profile selects audio plugins"
                )
            audio_graph = await AudioPluginGraph.open(
                profile=profile,
                interaction_context=context,
                pseudonymization_key=self._pseudonymization_key,
                event_queue_size=self._event_queue_size,
            )
        opened = await asyncio.gather(
            CascadedInputPipeline.open(
                context=context,
                vad=vad,
                asr=asr,
                turn_manager=turn_manager,
                event_queue_size=self._event_queue_size,
                provider_timing=self._provider_timing,
            ),
            brain_provider.open(context=context),
            tts_provider.open(context=context),
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
                *((audio_graph.close(),) if audio_graph is not None else ()),
                return_exceptions=True,
            )
            raise failure
        input_pipeline, brain, tts = opened
        input_pipeline = cast(CascadedInputPipeline, input_pipeline)
        brain = cast(BrainCapabilitySession, brain)
        tts = cast(TtsCapabilitySession, tts)
        if self._provider_timing is not None:
            tts = TimedTtsSession(tts, self._provider_timing, context)
        speech_deliveries = self._speech_deliveries or InMemorySpeechDeliveryStore()
        return CascadedRealtimeConversation(
            context=context,
            input_pipeline=input_pipeline,
            brain=brain,
            speech_renderer=speech_renderer,
            tts=tts,
            audio_graph=audio_graph,
            speech_lifecycle=SpeechLifecycle(speech_deliveries),
            speech_deliveries=speech_deliveries,
            event_queue_size=self._event_queue_size,
            response_timeout_s=self._response_timeout_s,
            response_first_text_timeout_s=self._response_first_text_timeout_s,
            response_cancel_timeout_s=self._response_cancel_timeout_s,
            context_projector=self._context_projector_factory(),
        )


class CascadedRealtimeConversation:
    def __init__(
        self,
        *,
        context: InteractionContext,
        input_pipeline: CascadedInputPipeline,
        brain: BrainCapabilitySession,
        speech_renderer: SpeechRenderer,
        tts: TtsCapabilitySession,
        audio_graph: AudioPluginGraph | None,
        speech_lifecycle: SpeechLifecycle,
        speech_deliveries: SpeechDeliveryStore,
        event_queue_size: int,
        response_timeout_s: float,
        response_first_text_timeout_s: float,
        response_cancel_timeout_s: float,
        context_projector: ModelContextProjector,
    ) -> None:
        self._context = context
        self._input_pipeline = input_pipeline
        self._brain = brain
        self._speech_renderer = speech_renderer
        self._tts = tts
        self._audio_graph = audio_graph
        self._speech_lifecycle = speech_lifecycle
        self._speech_deliveries = speech_deliveries
        self._response_timeout_s = response_timeout_s
        self._response_first_text_timeout_s = response_first_text_timeout_s
        self._response_cancel_timeout_s = response_cancel_timeout_s
        self._context_projector = context_projector
        self._events: asyncio.Queue[RealtimeEvent | object] = asyncio.Queue(
            maxsize=event_queue_size
        )
        self._commands_by_idempotency_key: dict[str, RealtimeCommand] = {}
        self._sequence = 0
        self._projected_items: dict[int, ConversationItem] = {}
        self._input_pipeline.set_prefetch_turn_builder(self._turn_for_prefetch)
        self._projected_sequence_by_item_id: dict[str, int] = {}
        self._last_projected_thread_sequence = 0
        self._response_sequence_by_id: dict[str, int] = {}
        self._response_task: asyncio.Task[None] | None = None
        self._detached_response_tasks: set[asyncio.Task[None]] = set()
        self._active_response_id: str | None = None
        self._terminal_response_ids: set[str] = set()
        self._cancel_reason_by_response_id: dict[str, str] = {}
        self._response_admitted_by_id: dict[str, asyncio.Event] = {}
        self._tts_task_by_response_id: dict[str, asyncio.Task[None]] = {}
        self._pending_deliveries: deque[DeliverItem] = deque()
        self._delivery_by_response_id: dict[str, DeliverItem] = {}
        self._direct_delivery_command: DeliverItem | None = None
        self._direct_delivery_cancel_reason: str | None = None
        self._external_speech_id: str | None = None
        self._external_tts_task: asyncio.Task[None] | None = None
        self._model_speech_ids: set[str] = set()
        self._unsettled_model_speech_ids: set[str] = set()
        self._playback_started_model_speech_ids: set[str] = set()
        self._model_speech_with_audio_ids: set[str] = set()
        self._response_by_model_speech_id: dict[str, tuple[str, InteractionContext]] = {}
        self._settled_input_response_ids: set[str] = set()
        self._playback_watchdog_tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False
        self._input_task = asyncio.create_task(
            self._pump_input(),
            name=f"cascaded-input-{context.voice_session_id}",
        )
        self._plugin_task = (
            asyncio.create_task(
                self._pump_audio_plugins(),
                name=f"cascaded-audio-plugins-{context.voice_session_id}",
            )
            if audio_graph is not None
            else None
        )

    async def send(self, command: RealtimeCommand) -> None:
        if self._closed:
            raise RuntimeError("realtime conversation is closed")
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        previous = self._commands_by_idempotency_key.get(command.idempotency_key)
        if previous is not None:
            if previous != command:
                raise ValueError("idempotency key was reused with different command content")
            return
        if isinstance(command, AppendAudio):
            frame = (
                await self._audio_graph.process(command.frame)
                if self._audio_graph is not None
                else command.frame
            )
            await self._input_pipeline.append_audio(frame, context=command.context)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, StartSpeech):
            await self._start_external_speech(command)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, AppendSpeechText):
            self._require_external_speech(command.speech_id)
            accepted = await self._speech_lifecycle.append(
                command,
                sequence=self._next_sequence,
            )
            await self._emit(accepted)
            await self._tts.send(
                AppendTtsText(
                    speech_id=command.speech_id,
                    text_sequence=command.text_sequence,
                    delta=command.delta,
                )
            )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, CommitSpeech):
            self._require_external_speech(command.speech_id)
            committed = await self._speech_lifecycle.commit(
                command,
                sequence=self._next_sequence,
            )
            await self._emit(committed)
            await self._tts.send(CommitTts(speech_id=command.speech_id))
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, CancelSpeech):
            self._require_external_speech(command.speech_id)
            tts_task = self._external_tts_task
            await self._input_pipeline.invalidate_response(command.speech_id, context=command.context, reason=command.reason)
            await self._tts.send(
                CancelTts(speech_id=command.speech_id, reason=command.reason)
            )
            if tts_task is not None:
                await tts_task
            cancelled = await self._speech_lifecycle.cancel(
                command,
                sequence=self._next_sequence,
            )
            await self._emit(cancelled)
            if command.reason != "barge_in_floor_claim":
                await self._input_pipeline.response_completed(
                    command.speech_id,
                    context=command.context,
                )
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, RecordOutputStop):
            await self._speech_lifecycle.record_output_stop(command.fact)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, ReportPlaybackProgress):
            progress = (
                await self._report_model_playback(command)
                if command.speech_id in self._model_speech_ids
                else await self._speech_lifecycle.report(
                    command,
                    sequence=self._next_sequence,
                )
            )
            if progress is not None:
                # The speech route owns this lease. External speech may retain
                # a source item's response_id in its original context.
                response_id = (command.speech_id.removeprefix("response:")
                    if command.speech_id in self._model_speech_ids else command.speech_id)
                await self._input_pipeline.assistant_playback(command, response_id=response_id)
                await self._emit(progress)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, ProjectCommittedItem):
            await self._project(command)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, DeliverItem):
            await self._queue_delivery(command)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, RequestResponse):
            await self._request_response(command)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, CancelResponse):
            await self._cancel_response(command)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        raise TypeError(f"unsupported cascaded realtime command: {type(command).__name__}")

    async def _report_model_playback(
        self,
        command: ReportPlaybackProgress,
    ) -> SpeechPlaybackProgress | None:
        existing = await self._speech_deliveries.get(command.speech_id)
        if existing is not None and existing.status in {
            SpeechDeliveryStatus.COMPLETED,
            SpeechDeliveryStatus.FAILED,
            SpeechDeliveryStatus.UNCERTAIN,
        }:
            # A queued browser playback event can arrive after speech has settled.
            return None
        if existing is None or existing.status not in {
            SpeechDeliveryStatus.ACTIVE,
            SpeechDeliveryStatus.INTERRUPTED,
        }:
            raise ValueError("speech delivery does not accept playback progress")
        record = await self._speech_deliveries.report_progress(
            command.speech_id,
            delivered_text_end=command.delivered_text_end,
            played_audio_end_us=command.played_audio_end_us,
            precision=command.precision,
            completed=command.completed,
        )
        response = self._response_by_model_speech_id.get(command.speech_id)
        if response is None and record.context.response_id is not None:
            # Cancellation removes the routing map, not the persisted playback
            # identity. Late renderer facts still refine the interrupted record.
            response = (record.context.response_id, record.context)
        if response is not None:
            response_id, response_context = response
            await self._input_pipeline.assistant_spoken_text(
                record.delivered_speech_transcript,
                context=replace(response_context, response_id=response_id),
                playback_started=(command.started or command.played_audio_end_us > 0
                                  or command.delivered_text_end > 0),
            )
        if command.completed:
            self._unsettled_model_speech_ids.discard(command.speech_id)
            response = self._response_by_model_speech_id.get(command.speech_id)
            if response is not None:
                response_id, context = response
                settlement_error = await self._settle_input_response(
                    response_id,
                    context=context,
                )
                if settlement_error is not None:
                    raise RuntimeError(settlement_error)
            self._playback_started_model_speech_ids.discard(command.speech_id)
            self._model_speech_with_audio_ids.discard(command.speech_id)
            self._response_by_model_speech_id.pop(command.speech_id, None)
            self._cancel_playback_watchdog(command.speech_id)
        elif record.status is SpeechDeliveryStatus.ACTIVE:
            self._playback_started_model_speech_ids.add(command.speech_id)
        else:
            self._response_by_model_speech_id.pop(command.speech_id, None)
        await self._refresh_projected_delivery(record)
        return SpeechPlaybackProgress(
            event_id=str(uuid.uuid4()),
            context=command.context,
            conversation_sequence=self._next_sequence(),
            occurred_at=datetime.now(UTC),
            speech_id=command.speech_id,
            delivered_text_end=command.delivered_text_end,
            delivered_speech_transcript=record.delivered_speech_transcript,
            played_audio_end_us=command.played_audio_end_us,
            precision=command.precision,
            completed=command.completed,
            started=command.started,
            stopped=command.stopped,
        )

    async def _start_external_speech(self, command: StartSpeech) -> None:
        if self._response_task is not None or self._external_speech_id is not None:
            raise ValueError("realtime conversation already has active output")
        started = await self._speech_lifecycle.start(
            command,
            sequence=self._next_sequence,
        )
        try:
            await self._input_pipeline.response_started(
                command.speech_id,
                context=command.context,
            )
            await self._tts.send(
                StartTts(speech_id=command.speech_id, context=command.context)
            )
        except Exception:
            await self._speech_lifecycle.fail(
                command.speech_id,
                reason="tts_start_failed",
            )
            raise
        self._external_speech_id = command.speech_id
        self._external_tts_task = asyncio.create_task(
            self._pump_external_tts(command),
            name=f"cascaded-external-speech-{command.speech_id}",
        )
        await self._emit(started)

    def _require_external_speech(self, speech_id: str) -> None:
        if self._external_speech_id != speech_id:
            raise ValueError("speech output is not active")

    async def _pump_external_tts(self, command: StartSpeech) -> None:
        segment_index = 0
        try:
            async for event in self._tts.events():
                if event.speech_id != command.speech_id:
                    continue
                if isinstance(event, TtsTextAlignment):
                    await self._emit(SpeechTextAlignment(
                        event_id=str(uuid.uuid4()), context=command.context,
                        conversation_sequence=self._next_sequence(), occurred_at=datetime.now(UTC),
                        speech_id=command.speech_id, audio_end_us=event.audio_end_us, text_end=event.text_end,
                        audio_start_us=event.audio_start_us, text_end_precision=event.text_end_precision,
                        sentence=event.sentence,
                    ))
                elif isinstance(event, TtsAudioFrame):
                    await self._emit(
                        SpeechAudioDelta(
                            event_id=str(uuid.uuid4()),
                            context=command.context,
                            conversation_sequence=self._next_sequence(),
                            occurred_at=datetime.now(UTC),
                            speech_id=command.speech_id,
                            frame=event.frame,
                            segment_index=segment_index,
                            is_final_for_segment=event.is_final_for_segment,
                        )
                    )
                    if event.is_final_for_segment:
                        segment_index += 1
                elif isinstance(event, TtsCompleted):
                    await self._emit(
                        SpeechAudioCompleted(
                            event_id=str(uuid.uuid4()),
                            context=command.context,
                            conversation_sequence=self._next_sequence(),
                            occurred_at=datetime.now(UTC),
                            speech_id=command.speech_id,
                        )
                    )
                    return
                elif isinstance(event, TtsCancelled):
                    return
                elif isinstance(event, TtsFailed):
                    await self._speech_lifecycle.fail(
                        command.speech_id,
                        reason=event.error,
                    )
                    await self._emit(
                        RealtimeCapabilityFailed(
                            event_id=str(uuid.uuid4()),
                            context=command.context,
                            conversation_sequence=self._next_sequence(),
                            occurred_at=datetime.now(UTC),
                            capability="tts",
                            error=event.error,
                        )
                    )
                    return
        finally:
            self._external_speech_id = None
            self._external_tts_task = None
            await self._dispatch_next_delivery()

    async def _project(self, command: ProjectCommittedItem) -> None:
        item = command.item
        if item.kind is ConversationItemKind.ASSISTANT_OUTPUT:
            delivery = await self._speech_deliveries.latest_for_item(item.item_id)
            if delivery is not None:
                item = replace(item, content=project_assistant_context(item, delivery))
        if item.sequence > self._last_projected_thread_sequence + 1:
            raise ContextVisibilityError(
                f"cannot project thread sequence {item.sequence} before "
                f"{self._last_projected_thread_sequence + 1}"
            )
        self._projected_items[item.sequence] = item
        self._projected_sequence_by_item_id[item.item_id] = item.sequence
        self._last_projected_thread_sequence = max(
            self._last_projected_thread_sequence, item.sequence
        )
        await self._input_pipeline.observe_conversation_item(item)
        await self._emit(
            ItemProjected(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                item_id=item.item_id,
                thread_sequence=item.sequence,
                thread_version=item.thread_version,
            )
        )
        if item.kind is ConversationItemKind.TOOL_RESULT:
            response_id = item.context.response_id
            call_id = item.context.call_id
            if response_id is None or call_id is None:
                raise ValueError(
                    "tool result projection requires response_id and call_id context"
                )
            model_output = "\n".join(
                part.text for part in item.content if isinstance(part, TextContent)
            )
            if not model_output:
                raise ValueError("tool result projection requires model-visible text")
            # A cancelled response may finish persisting its tool outcome after
            # a user barge-in.  Keep that durable fact in projected history,
            # but never resume a Brain response that no longer owns the turn.
            if response_id != self._active_response_id:
                return
            error_code = item.provider_metadata.get("error_code")
            await self._brain.send(
                SubmitBrainToolResult(
                    response_id=response_id,
                    call_id=call_id,
                    success=item.status is ConversationItemStatus.COMPLETED,
                    model_output=model_output,
                    error_code=(error_code if isinstance(error_code, str) else None),
                )
            )

    async def _queue_delivery(self, command: DeliverItem) -> None:
        thread_sequence = self._projected_sequence_by_item_id.get(command.item_id)
        if thread_sequence is None:
            raise ContextVisibilityError(
                f"item {command.item_id!r} has not been projected"
            )
        await self._emit(
            ItemDeliveryQueued(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                delivery_id=command.delivery_id,
                item_id=command.item_id,
                minimum_thread_sequence=thread_sequence,
                mode=command.mode,
                timing=command.timing,
                priority=command.priority,
            )
        )
        self._pending_deliveries.append(command)
        await self._dispatch_next_delivery()

    async def _dispatch_next_delivery(self) -> None:
        if (
            self._closed
            or self._response_task is not None
            or self._external_speech_id is not None
            or not self._pending_deliveries
        ):
            return
        command = self._pending_deliveries.popleft()
        thread_sequence = self._projected_sequence_by_item_id[command.item_id]
        await self._emit(
            ItemDeliveryStarted(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                delivery_id=command.delivery_id,
                item_id=command.item_id,
                minimum_thread_sequence=thread_sequence,
                mode=command.mode,
            )
        )
        if command.mode is DeliveryMode.MODEL_RESPONSE:
            response_id = f"delivery:{command.delivery_id}"
            self._delivery_by_response_id[response_id] = command
            await self._request_response(
                RequestResponse(
                    command_id=f"response:{command.command_id}",
                    idempotency_key=f"response:{command.idempotency_key}",
                    context=replace(command.context, response_id=response_id),
                    response_id=response_id,
                    minimum_thread_sequence=thread_sequence,
                    output_item_id=command.output_item_id,
                )
            )
            return
        if command.mode is DeliveryMode.SPEECH:
            self._direct_delivery_command = command
            self._response_task = asyncio.create_task(
                self._run_direct_speech_delivery(command),
                name=f"cascaded-delivery-{command.delivery_id}",
            )
            return
        if command.mode is DeliveryMode.DISPLAY_ONLY:
            await self._present_item_display(command)
        await self._complete_delivery(command)
        await self._dispatch_next_delivery()

    async def _present_item_display(self, command: DeliverItem) -> None:
        item = self._item_by_id(command.item_id)
        markdown = item.display.markdown if item.display is not None else "\n".join(
            part.text for part in item.content if isinstance(part, TextContent)
        )
        if not markdown:
            raise ValueError(f"item {item.item_id!r} has no display representation")
        await self._emit(
            ItemDisplayPresented(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                delivery_id=command.delivery_id,
                item_id=command.item_id,
                markdown=markdown,
            )
        )

    async def _run_direct_speech_delivery(self, command: DeliverItem) -> None:
        response_id = f"delivery:{command.delivery_id}"
        context = replace(command.context, response_id=response_id)
        speech_id = f"response:{response_id}"
        tts_task: asyncio.Task[None] | None = None
        try:
            item = self._item_by_id(command.item_id)
            spoken = await resolve_spoken_content(
                AssistantContent(
                    semantic=item.content,
                    display=item.display,
                    spoken=item.spoken,
                ),
                renderer=self._speech_renderer,
            )
            await self._input_pipeline.response_started(
                response_id,
                context=command.context,
            )
            await self._emit_response(
                ResponseStarted,
                context=context,
                response_id=response_id,
            )
            await self._emit_response(
                SpokenContentDelta,
                context=context,
                response_id=response_id,
                delta=spoken.text,
            )
            await self._speech_deliveries.start(
                SpeechDeliveryRecord(
                    speech_id=speech_id,
                    context=context,
                    source_item_id=command.item_id,
                    context_policy=SpeechContextPolicy.AUTO,
                    interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
                )
            )
            self._model_speech_ids.add(speech_id)
            self._unsettled_model_speech_ids.add(speech_id)
            await self._speech_deliveries.append_text(speech_id, spoken.text)
            await self._speech_deliveries.commit_text(speech_id)
            await self._tts.send(StartTts(speech_id=speech_id, context=command.context))
            tts_task = asyncio.create_task(
                self._pump_tts(
                    RequestResponse(
                        command_id=f"speech:{command.command_id}",
                        idempotency_key=f"speech:{command.idempotency_key}",
                        context=command.context,
                        response_id=response_id,
                        minimum_thread_sequence=self._projected_sequence_by_item_id[
                            command.item_id
                        ],
                    ),
                    speech_id=speech_id,
                )
            )
            await self._tts.send(
                AppendTtsText(speech_id=speech_id, text_sequence=1, delta=spoken.text)
            )
            await self._tts.send(CommitTts(speech_id=speech_id))
            await tts_task
            settlement_error = await self._settle_input_response(
                response_id,
                context=command.context,
            )
            if settlement_error is not None:
                raise CascadedCapabilityError(settlement_error)
            await self._emit_response(
                ResponseCompleted,
                context=context,
                response_id=response_id,
            )
            await self._complete_delivery(command)
        except asyncio.CancelledError:
            if tts_task is not None and not tts_task.done():
                tts_task.cancel()
                await asyncio.gather(tts_task, return_exceptions=True)
            reason = self._direct_delivery_cancel_reason or "cancelled"
            try:
                await self._tts.send(CancelTts(speech_id=speech_id, reason=reason))
            except ValueError:
                pass
            await self._cancel_model_speech(speech_id, reason=reason)
            await self._emit_response(
                ResponseCancelled,
                context=context,
                response_id=response_id,
                reason=reason,
            )
            await self._cancel_delivery(command, reason=reason)
        except Exception as error:  # noqa: BLE001 - provider failure becomes protocol event
            if tts_task is not None and not tts_task.done():
                tts_task.cancel()
                await asyncio.gather(tts_task, return_exceptions=True)
            failure = str(error)
            if isinstance(error, CascadedCapabilityError):
                await self._emit_capability_failure(
                    context=command.context,
                    capability="tts",
                    error=failure,
                )
            await self._fail_model_speech(speech_id, reason=failure)
            settlement_error = await self._settle_input_response(
                response_id,
                context=command.context,
            )
            if settlement_error is not None:
                failure = f"{failure}; {settlement_error}"
            await self._emit_response(
                ResponseFailed,
                context=context,
                response_id=response_id,
                error=failure,
            )
            await self._fail_delivery(command, error=failure)
        finally:
            self._response_task = None
            self._direct_delivery_command = None
            self._direct_delivery_cancel_reason = None
            await self._dispatch_next_delivery()

    def _item_by_id(self, item_id: str) -> ConversationItem:
        sequence = self._projected_sequence_by_item_id[item_id]
        return self._projected_items[sequence]

    async def _complete_delivery(self, command: DeliverItem) -> None:
        await self._emit(
            ItemDeliveryCompleted(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                delivery_id=command.delivery_id,
                item_id=command.item_id,
                mode=command.mode,
            )
        )

    async def _fail_delivery(self, command: DeliverItem, *, error: str) -> None:
        await self._emit(
            ItemDeliveryFailed(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                delivery_id=command.delivery_id,
                item_id=command.item_id,
                mode=command.mode,
                error=error,
            )
        )

    async def _cancel_delivery(self, command: DeliverItem, *, reason: str) -> None:
        await self._emit(
            ItemDeliveryCancelled(
                event_id=str(uuid.uuid4()),
                context=command.context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                delivery_id=command.delivery_id,
                item_id=command.item_id,
                mode=command.mode,
                reason=reason,
            )
        )

    async def _request_response(self, command: RequestResponse) -> None:
        if command.minimum_thread_sequence > self._last_projected_thread_sequence:
            raise ContextVisibilityError(
                "response requires thread sequence "
                f"{command.minimum_thread_sequence}, but engine has projected through "
                f"{self._last_projected_thread_sequence}"
            )
        if self._response_task is not None and not self._response_task.done():
            raise ValueError("Cascaded Realtime Conversation already has an active response")
        if self._external_speech_id is not None:
            raise ValueError("Cascaded Realtime Conversation already has active speech")
        turn = await self._turn_from_projection(
            command.minimum_thread_sequence,
            generation=command.context.generation,
        )
        self._active_response_id = command.response_id
        self._response_admitted_by_id[command.response_id] = asyncio.Event()
        ready = asyncio.Event()
        self._response_task = asyncio.create_task(
            self._start_response(command, turn, ready=ready),
            name=f"cascaded-response-{command.response_id}",
        )
        # Preparing can immediately trigger a yield for deferred speech. The
        # cancellation target and task must exist before publishing it.
        try:
            await self._input_pipeline.response_started(command.response_id, context=command.context, preparing=True)
        except BaseException:
            # Preparing failed before Brain admission. Do not release a request
            # the caller was told had failed; clean up the already visible task.
            task = self._response_task
            if task is not None:
                self._cancel_reason_by_response_id[command.response_id] = "preparing_failed"
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if self._response_task is task:
                    self._response_task = None
                if self._active_response_id == command.response_id:
                    self._active_response_id = None
                self._response_admitted_by_id.pop(command.response_id, None)
                self._cancel_reason_by_response_id.pop(command.response_id, None)
            raise
        finally:
            ready.set()

    async def _cancel_response(self, command: CancelResponse) -> None:
        direct_delivery = self._direct_delivery_command
        if (
            direct_delivery is not None
            and command.response_id == f"delivery:{direct_delivery.delivery_id}"
            and self._response_task is not None
            and not self._response_task.done()
        ):
            self._direct_delivery_cancel_reason = command.reason
            task = self._response_task
            await self._input_pipeline.invalidate_response(command.response_id, context=command.context, reason=command.reason)
            completed_before_cancel = task.done()
            if not completed_before_cancel:
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if completed_before_cancel:
                await self._cancel_model_speech(f"response:{command.response_id}", reason=command.reason)
                await self._notify_cancelled_playback(command, response_context=direct_delivery.context)
            return
        if (
            self._active_response_id != command.response_id
            or self._response_task is None
            or self._response_task.done()
        ):
            raise ValueError("response identity is not active")
        task = self._response_task
        admission = self._response_admitted_by_id[command.response_id]
        self._cancel_reason_by_response_id[command.response_id] = command.reason
        await self._input_pipeline.invalidate_response(command.response_id, context=command.context, reason=command.reason)
        await admission.wait()
        if task.done():
            # Completion during permission revocation must never select a new task.
            self._cancel_reason_by_response_id.pop(command.response_id, None)
            speech_id = f"response:{command.response_id}"
            response = self._response_by_model_speech_id.get(speech_id)
            response_context = response[1] if response is not None else command.context
            await self._cancel_model_speech(speech_id, reason=command.reason)
            await self._notify_cancelled_playback(command, response_context=response_context)
            return
        task.cancel()
        done, pending = await asyncio.wait(
            {task},
            timeout=self._response_cancel_timeout_s,
        )
        if done:
            await asyncio.gather(*done, return_exceptions=True)
            return

        logger.warning(
            "Response cancellation exceeded %.0fms for %s; detaching cleanup",
            self._response_cancel_timeout_s * 1000,
            command.response_id,
        )
        self._detached_response_tasks.update(pending)
        for detached in pending:
            detached.add_done_callback(self._observe_detached_response_task)
        if self._response_task is task:
            self._response_task = None
        if self._active_response_id == command.response_id:
            self._active_response_id = None
        self._response_admitted_by_id.pop(command.response_id, None)
        self._cancel_reason_by_response_id.pop(command.response_id, None)
        speech_id = f"response:{command.response_id}"
        await self._cancel_model_speech(speech_id, reason=command.reason)
        if command.reason != "barge_in_floor_claim":
            await self._settle_input_response(
                command.response_id,
                context=command.context,
            )
        await self._emit_capability_failure(
            context=command.context,
            capability="response_cancel_cleanup",
            error=(
                "response cleanup exceeded its cancellation deadline and "
                "was detached"
            ),
        )
        await self._emit_response(
            ResponseCancelled,
            context=replace(command.context, response_id=command.response_id),
            response_id=command.response_id,
            reason=command.reason,
        )
        await self._dispatch_next_delivery()

    async def _notify_cancelled_playback(
        self, command: CancelResponse, *, response_context: InteractionContext,
    ) -> None:
        if command.reason == "barge_in_floor_claim":
            return  # The input pump already published this stop fact.
        await self._emit(AssistantYieldRequested(
            event_id=str(uuid.uuid4()), context=replace(response_context, response_id=command.response_id),
            conversation_sequence=self._next_sequence(), occurred_at=datetime.now(UTC),
            reason=command.reason,
        ))

    def _observe_detached_response_task(self, task: asyncio.Task[None]) -> None:
        self._detached_response_tasks.discard(task)
        try:
            task.exception()
        except asyncio.CancelledError:
            pass

    def _prior_model_items(self, before_sequence: int) -> tuple[ConversationItem, ...]:
        superseded_turns = {
            item.provider_metadata.get("continuation_of_turn_id")
            for item in self._projected_items.values() if item.sequence <= before_sequence
        }
        items = []
        for sequence in sorted(self._projected_items):
            if sequence >= before_sequence:
                continue
            item = self._projected_items[sequence]
            if ((item.context.turn_id in superseded_turns and item.kind is ConversationItemKind.USER_INPUT)
                or item.kind is ConversationItemKind.ASSISTANT_OUTPUT and not item.content):
                # Keep contiguous source identities for validated compression,
                # while omitting superseded/empty content from the model view.
                item = replace(item, visibility=item.visibility - {ConversationVisibility.MODEL})
            items.append(item)
        return tuple(items)

    def _response_projection_snapshot(self, minimum_thread_sequence: int) -> tuple[tuple[ConversationItem, ...], ConversationItem]:
        for sequence in range(minimum_thread_sequence, 0, -1):
            item = self._projected_items.get(sequence)
            if (item is not None and item.kind in {ConversationItemKind.USER_INPUT,
                ConversationItemKind.TOOL_RESULT, ConversationItemKind.DELEGATION_RESULT}
                and ConversationVisibility.MODEL in item.visibility
                and any(isinstance(part, TextContent) and part.text for part in item.content)):
                return self._prior_model_items(sequence), item
        raise ValueError("projected context has no model-visible text input")

    async def _project_stable_context(self, snapshot: Callable[[], tuple[tuple[ConversationItem, ...], ConversationItem | None]]) -> tuple[str | None, str, ConversationItem | None]:
        for _ in range(3):
            items, current = snapshot()
            source = (*items, current) if current is not None else items
            source_digest = digest_source_items(source)
            try:
                projected = await self._context_projector.project_text(items)
            except SummarySourceChangedError:
                latest, latest_current = snapshot()
                if digest_source_items((*latest, latest_current) if latest_current is not None else latest) != source_digest:
                    continue
                raise
            latest, latest_current = snapshot()
            if digest_source_items((*latest, latest_current) if latest_current is not None else latest) == source_digest:
                # The speculative key covers only prior context. The current
                # input already has text/relation keys and does not exist in
                # Journal until commit; including it would make every hit miss.
                return projected, digest_source_items(items), current
        raise ContextVisibilityError("model-visible playback context changed during projection; retry budget exhausted")

    async def _turn_for_prefetch(self, text: str, generation: int) -> TurnContent:
        context, digest, _ = await self._project_stable_context(lambda: (
            self._prior_model_items(max(self._projected_items, default=0) + 1), None))
        return TurnContent(text=text, generation=generation,
            conversation_context=context, context_projection_digest=digest)

    async def _turn_from_projection(self, minimum_thread_sequence: int, *, generation: int) -> TurnContent:
        context, digest, item = await self._project_stable_context(lambda: self._response_projection_snapshot(minimum_thread_sequence))
        assert item is not None
        return TurnContent(text="\n".join(part.text for part in item.content if isinstance(part, TextContent)),
            generation=generation, input_relation_unresolved=item.provider_metadata.get("input_relation") == "unresolved",
            conversation_context=context, context_projection_digest=digest)

    async def _start_response(self, command: RequestResponse, turn: TurnContent, *, ready: asyncio.Event) -> None:
        self._response_admitted_by_id[command.response_id].set()
        failure: str | None = None
        cancelled_reason: str | None = None
        brain_requested = False
        deadline = asyncio.timeout(self._response_timeout_s)
        try:
            async with deadline:
                await ready.wait()
                if not self._input_pipeline.response_delivery_allowed(command.response_id):
                    raise asyncio.CancelledError
                items, source_item = self._response_projection_snapshot(command.minimum_thread_sequence)
                if (digest_source_items(items) != turn.context_projection_digest
                    or "\n".join(part.text for part in source_item.content if isinstance(part, TextContent)) != turn.text
                    or (source_item.provider_metadata.get("input_relation") == "unresolved") != turn.input_relation_unresolved):
                    turn = await self._turn_from_projection(command.minimum_thread_sequence, generation=command.context.generation)
                if not self._input_pipeline.response_delivery_allowed(command.response_id):
                    raise asyncio.CancelledError
                brain_requested = True
                await self._brain.send(
                    RequestBrainResponse(
                        response_id=command.response_id,
                        turn=turn,
                        context=command.context,
                    )
                )
                failure = await self._route_response(command)
        except _FirstResponseTextDeadlineExceeded:
            failure = (
                "first response text deadline exceeded after "
                f"{self._response_first_text_timeout_s:.3f}s"
            )
            await self._brain.send(
                CancelBrainResponse(
                    response_id=command.response_id,
                    reason="response_first_text_deadline_exceeded",
                )
            )
            await self._emit_capability_failure(
                context=command.context,
                capability="response_first_text_deadline",
                error=failure,
            )
            failure = await self._record_response_failure(command, failure)
        except TimeoutError as error:
            if deadline.expired():
                failure = (
                    "response deadline exceeded after "
                    f"{self._response_timeout_s:.3f}s"
                )
                await self._brain.send(
                    CancelBrainResponse(
                        response_id=command.response_id,
                        reason="response_deadline_exceeded",
                    )
                )
                tts_task = self._tts_task_by_response_id.pop(command.response_id, None)
                if tts_task is not None:
                    await self._tts.send(
                        CancelTts(
                            speech_id=f"response:{command.response_id}",
                            reason="response_deadline_exceeded",
                        )
                    )
                    await asyncio.gather(tts_task, return_exceptions=True)
                await self._emit_capability_failure(
                    context=command.context,
                    capability="response_deadline",
                    error=failure,
                )
            else:
                failure = str(error)
            failure = await self._record_response_failure(command, failure)
        except asyncio.CancelledError:
            cancelled_reason = self._cancel_reason_by_response_id.pop(
                command.response_id,
                "cancelled",
            )
            if brain_requested:
                await self._brain.send(
                    CancelBrainResponse(
                        response_id=command.response_id,
                        reason=cancelled_reason,
                    )
                )
            tts_task = self._tts_task_by_response_id.pop(command.response_id, None)
            if tts_task is not None:
                await self._tts.send(
                    CancelTts(
                        speech_id=f"response:{command.response_id}",
                        reason=cancelled_reason,
                    )
                )
                await tts_task
            await self._cancel_model_speech(
                f"response:{command.response_id}",
                reason=cancelled_reason,
            )
            if cancelled_reason != "barge_in_floor_claim":
                settlement_error = await self._settle_input_response(
                    command.response_id,
                    context=command.context,
                )
                if settlement_error is not None:
                    cancelled_reason = f"{cancelled_reason}; {settlement_error}"
        except Exception as error:  # noqa: BLE001 - provider failure becomes protocol event
            failure = await self._record_response_failure(command, str(error))
        finally:
            if cancelled_reason is not None:
                await self._emit_response(
                    ResponseCancelled,
                    context=replace(command.context, response_id=command.response_id),
                    response_id=command.response_id,
                    reason=cancelled_reason,
                )
            current = asyncio.current_task()
            if self._response_task is current:
                self._response_task = None
            if self._active_response_id == command.response_id:
                self._active_response_id = None
            self._response_admitted_by_id.pop(command.response_id, None)
            delivery = self._delivery_by_response_id.pop(command.response_id, None)
            if delivery is not None:
                if cancelled_reason is not None:
                    await self._cancel_delivery(delivery, reason=cancelled_reason)
                elif failure is None:
                    await self._complete_delivery(delivery)
                else:
                    await self._fail_delivery(delivery, error=failure)
            await self._dispatch_next_delivery()

    async def _record_response_failure(
        self,
        command: RequestResponse,
        failure: str,
    ) -> str:
        speech_id = f"response:{command.response_id}"
        tts_task = self._tts_task_by_response_id.pop(command.response_id, None)
        if tts_task is not None:
            try:
                await self._tts.send(
                    CancelTts(
                        speech_id=speech_id,
                        reason="response_failed",
                    )
                )
            except Exception as cleanup_error:  # noqa: BLE001 - preserve root failure
                failure = f"{failure}; TTS cleanup failed: {cleanup_error}"
            await asyncio.gather(tts_task, return_exceptions=True)
        await self._fail_model_speech(
            speech_id,
            reason=failure,
        )
        self._playback_started_model_speech_ids.discard(speech_id)
        self._model_speech_with_audio_ids.discard(speech_id)
        self._response_by_model_speech_id.pop(speech_id, None)
        self._cancel_playback_watchdog(speech_id)
        settlement_error = await self._settle_input_response(
            command.response_id,
            context=command.context,
        )
        if settlement_error is not None:
            failure = f"{failure}; {settlement_error}"
        await self._emit_response(
            ResponseFailed,
            context=replace(command.context, response_id=command.response_id),
            response_id=command.response_id,
            error=failure,
        )
        return failure

    async def _route_response(self, command: RequestResponse) -> str | None:
        response_context = replace(command.context, response_id=command.response_id)
        speech_id = f"response:{command.response_id}"
        text_sequence = 0
        tts_task: asyncio.Task[None] | None = None
        brain_events = self._brain.events().__aiter__()
        first_text_deadline = (
            asyncio.get_running_loop().time() + self._response_first_text_timeout_s
        )
        waiting_for_tool = False
        while True:
            try:
                if text_sequence == 0 and not waiting_for_tool:
                    remaining = first_text_deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise _FirstResponseTextDeadlineExceeded
                    event = await asyncio.wait_for(anext(brain_events), timeout=remaining)
                else:
                    event = await anext(brain_events)
            except StopAsyncIteration:
                break
            except TimeoutError as error:
                raise _FirstResponseTextDeadlineExceeded from error
            if event.response_id != command.response_id:
                continue
            if not isinstance(event, (BrainResponseCompleted, BrainResponseFailed)) and not self._input_pipeline.response_delivery_allowed(command.response_id):
                continue
            if isinstance(event, BrainResponseStarted):
                await self._input_pipeline.response_started(command.response_id, context=command.context)
                await self._start_model_speech(
                    command,
                    context=response_context,
                    speech_id=speech_id,
                )
                await self._emit_response(
                    ResponseStarted,
                    context=response_context,
                    response_id=command.response_id,
                )
            elif isinstance(event, BrainTextDelta):
                if tts_task is None:
                    await self._tts.send(
                        StartTts(speech_id=speech_id, context=command.context)
                    )
                    tts_task = asyncio.create_task(
                        self._pump_tts(command, speech_id=speech_id),
                        name=f"cascaded-tts-{speech_id}",
                    )
                    self._tts_task_by_response_id[command.response_id] = tts_task
                text_sequence += 1
                await self._speech_deliveries.append_text(speech_id, event.delta)
                await self._emit_response(
                    DisplayContentDelta,
                    context=response_context,
                    response_id=command.response_id,
                    delta=event.delta,
                )
                await self._emit_response(
                    SpokenContentDelta,
                    context=response_context,
                    response_id=command.response_id,
                    delta=event.delta,
                )
                await self._tts.send(
                    AppendTtsText(
                        speech_id=speech_id,
                        text_sequence=text_sequence,
                        delta=event.delta,
                    )
                )
            elif isinstance(event, BrainToolRequested):
                waiting_for_tool = True
                await self._emit_response(
                    ToolRequested,
                    context=replace(
                        response_context,
                        call_id=event.call_id,
                    ),
                    response_id=command.response_id,
                    call_id=event.call_id,
                    tool_name=event.tool_name,
                    tool_version=event.tool_version,
                    arguments=event.arguments,
                    latency=event.latency,
                )
            elif isinstance(event, BrainDelegationRequested):
                await self._emit_response(
                    AgentDelegationRequestProposed,
                    context=response_context,
                    response_id=command.response_id,
                    delegation_request_id=event.delegation_request_id,
                    instruction=event.instruction,
                    agent_name=event.agent_name,
                )
            elif isinstance(event, BrainResponseCompleted):
                await self._speech_deliveries.commit_text(speech_id)
                await self._tts.send(CommitTts(speech_id=speech_id))
                if tts_task is None:
                    raise RuntimeError("Brain completed before starting the response")
                try:
                    await tts_task
                except Exception as error:  # noqa: BLE001 - capability error becomes event
                    failure = str(error)
                    await self._emit_capability_failure(
                        context=command.context,
                        capability="tts",
                        error=failure,
                    )
                    await self._fail_model_speech(speech_id, reason=failure)
                    settlement_error = await self._settle_input_response(
                        command.response_id,
                        context=command.context,
                    )
                    if settlement_error is not None:
                        failure = f"{failure}; {settlement_error}"
                    await self._emit_response(
                        ResponseFailed,
                        context=response_context,
                        response_id=command.response_id,
                        error=failure,
                    )
                    return failure
                self._tts_task_by_response_id.pop(command.response_id, None)
                settlement_error = None
                if speech_id in self._model_speech_with_audio_ids:
                    self._arm_playback_watchdog(speech_id)
                else:
                    settlement_error = await self._settle_input_response(
                        command.response_id,
                        context=command.context,
                    )
                if settlement_error is not None:
                    await self._emit_response(
                        ResponseFailed,
                        context=response_context,
                        response_id=command.response_id,
                        error=settlement_error,
                    )
                    return settlement_error
                await self._emit_response(
                    ResponseCompleted,
                    context=response_context,
                    response_id=command.response_id,
                )
                return None
            elif isinstance(event, BrainResponseFailed):
                if tts_task is not None:
                    tts_task.cancel()
                    await asyncio.gather(tts_task, return_exceptions=True)
                    self._tts_task_by_response_id.pop(command.response_id, None)
                    await self._tts.send(
                        CancelTts(speech_id=speech_id, reason="brain_response_failed")
                    )
                failure = event.error
                await self._emit_capability_failure(
                    context=command.context,
                    capability="brain",
                    error=failure,
                )
                await self._fail_model_speech(speech_id, reason=failure)
                settlement_error = await self._settle_input_response(
                    command.response_id,
                    context=command.context,
                )
                if settlement_error is not None:
                    failure = f"{failure}; {settlement_error}"
                await self._emit_response(
                    ResponseFailed,
                    context=response_context,
                    response_id=command.response_id,
                    error=failure,
                )
                return failure
        if tts_task is not None:
            tts_task.cancel()
            await asyncio.gather(tts_task, return_exceptions=True)
            await self._tts.send(
                CancelTts(speech_id=speech_id, reason="brain_event_stream_ended")
            )
            self._tts_task_by_response_id.pop(command.response_id, None)
        failure = "Brain event stream ended before a terminal response event"
        await self._emit_capability_failure(
            context=command.context,
            capability="brain",
            error=failure,
        )
        await self._fail_model_speech(speech_id, reason=failure)
        settlement_error = await self._settle_input_response(
            command.response_id,
            context=command.context,
        )
        if settlement_error is not None:
            failure = f"{failure}; {settlement_error}"
        await self._emit_response(
            ResponseFailed,
            context=response_context,
            response_id=command.response_id,
            error=failure,
        )
        return failure

    async def _start_model_speech(
        self,
        command: RequestResponse,
        *,
        context: InteractionContext,
        speech_id: str,
    ) -> None:
        await self._speech_deliveries.start(
            SpeechDeliveryRecord(
                speech_id=speech_id,
                context=context,
                source_item_id=command.output_item_id,
                context_policy=SpeechContextPolicy.AUTO,
                interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
            )
        )
        self._model_speech_ids.add(speech_id)
        self._unsettled_model_speech_ids.add(speech_id)
        self._response_by_model_speech_id[speech_id] = (
            command.response_id,
            command.context,
        )

    async def _fail_model_speech(self, speech_id: str, *, reason: str) -> None:
        if speech_id not in self._unsettled_model_speech_ids:
            return
        await self._speech_deliveries.fail(speech_id, reason=reason)
        self._unsettled_model_speech_ids.remove(speech_id)
        self._cancel_playback_watchdog(speech_id)

    async def _cancel_model_speech(self, speech_id: str, *, reason: str) -> None:
        if speech_id not in self._unsettled_model_speech_ids:
            return
        record = await self._speech_deliveries.cancel(speech_id, reason=reason)
        self._unsettled_model_speech_ids.remove(speech_id)
        self._playback_started_model_speech_ids.discard(speech_id)
        self._model_speech_with_audio_ids.discard(speech_id)
        self._response_by_model_speech_id.pop(speech_id, None)
        self._cancel_playback_watchdog(speech_id)
        await self._refresh_projected_delivery(record)

    async def _refresh_projected_delivery(
        self,
        delivery: SpeechDeliveryRecord,
    ) -> None:
        item_id = delivery.source_item_id
        if item_id is None:
            return
        sequence = self._projected_sequence_by_item_id.get(item_id)
        if sequence is None:
            return
        item = self._projected_items.get(sequence)
        if item is None or item.kind is not ConversationItemKind.ASSISTANT_OUTPUT:
            return
        self._projected_items[sequence] = replace(
            item,
            content=project_assistant_context(item, delivery),
        )
        await self._input_pipeline.observe_conversation_item(
            self._projected_items[sequence]
        )

    async def _settle_input_response(
        self,
        response_id: str,
        *,
        context: InteractionContext,
    ) -> str | None:
        if response_id in self._settled_input_response_ids:
            return None
        try:
            await self._input_pipeline.response_completed(
                response_id,
                context=context,
            )
        except Exception as error:  # noqa: BLE001 - returned as response failure detail
            return f"turn manager settlement failed: {error}"
        self._settled_input_response_ids.add(response_id)
        return None

    async def _pump_tts(self, command: RequestResponse, *, speech_id: str) -> None:
        segment_index = 0
        async for event in self._tts.events():
            if event.speech_id != speech_id:
                continue
            if isinstance(event, (TtsTextAlignment, TtsAudioFrame)) and not self._input_pipeline.response_delivery_allowed(command.response_id):
                continue
            if isinstance(event, TtsTextAlignment):
                await self._emit(SpeechTextAlignment(
                    event_id=str(uuid.uuid4()), context=replace(command.context, response_id=command.response_id),
                    conversation_sequence=self._next_sequence(), occurred_at=datetime.now(UTC),
                    speech_id=speech_id, audio_end_us=event.audio_end_us, text_end=event.text_end,
                    audio_start_us=event.audio_start_us, text_end_precision=event.text_end_precision,
                    sentence=event.sentence,
                ))
            elif isinstance(event, TtsAudioFrame):
                if event.frame.data:
                    self._model_speech_with_audio_ids.add(speech_id)
                await self._emit_response(
                    AudioDelta,
                    context=replace(command.context, response_id=command.response_id),
                    response_id=command.response_id,
                    frame=event.frame,
                    segment_index=segment_index,
                    speech_id=speech_id,
                    is_final_for_segment=event.is_final_for_segment,
                )
                if event.is_final_for_segment:
                    segment_index += 1
            elif isinstance(event, TtsCancelled):
                if event.cleanup_timed_out:
                    await self._emit_capability_failure(
                        context=command.context,
                        capability="tts_cancel_cleanup",
                        error=(
                            "TTS provider cleanup exceeded its cancellation "
                            "deadline and was detached"
                        ),
                    )
                return
            elif isinstance(event, TtsCompleted):
                return
            elif isinstance(event, TtsFailed):
                raise CascadedCapabilityError(event.error)

    def _arm_playback_watchdog(self, speech_id: str) -> None:
        if speech_id in self._playback_watchdog_tasks:
            return

        async def settle_if_client_disappears() -> None:
            try:
                await asyncio.sleep(_PLAYBACK_COMPLETION_WATCHDOG_S)
                response = self._response_by_model_speech_id.get(speech_id)
                if response is None or speech_id not in self._unsettled_model_speech_ids:
                    return
                response_id, context = response
                await self._settle_input_response(response_id, context=context)
            finally:
                self._playback_watchdog_tasks.pop(speech_id, None)

        self._playback_watchdog_tasks[speech_id] = asyncio.create_task(
            settle_if_client_disappears(),
            name=f"cascaded-playback-watchdog-{speech_id}",
        )

    def _cancel_playback_watchdog(self, speech_id: str) -> None:
        task = self._playback_watchdog_tasks.pop(speech_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _emit_response(self, event_type, **fields: object) -> None:
        response_id = fields.get("response_id")
        if not isinstance(response_id, str):
            raise TypeError("response event must carry response_id")
        if event_type is ResponseStarted:
            revision = self._input_pipeline.response_revision(response_id)
            if revision is not None:
                fields.update(input_id=revision.input_id, input_version=revision.input_version,
                              reply_version=revision.reply_version,
                              supersedes_response_id=revision.supersedes_response_id)
        is_terminal = event_type in {
            ResponseCompleted,
            ResponseCancelled,
            ResponseFailed,
        }
        if is_terminal and response_id in self._terminal_response_ids:
            return
        response_sequence = self._response_sequence_by_id.get(response_id, 0) + 1
        self._response_sequence_by_id[response_id] = response_sequence
        await self._emit(
            event_type(
                event_id=str(uuid.uuid4()),
                conversation_sequence=self._next_sequence(),
                response_sequence=response_sequence,
                occurred_at=datetime.now(UTC),
                **fields,
            )
        )
        if is_terminal:
            self._terminal_response_ids.add(response_id)

    async def _emit_capability_failure(
        self,
        *,
        context: InteractionContext,
        capability: str,
        error: str,
    ) -> None:
        await self._emit(
            RealtimeCapabilityFailed(
                event_id=str(uuid.uuid4()),
                context=context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                capability=capability,
                error=error,
            )
        )

    async def _pump_input(self) -> None:
        async for event in self._input_pipeline.events():
            if isinstance(event, AsrTranscriptDelta):
                await self._emit(
                    InputTranscriptDelta(
                        event_id=str(uuid.uuid4()),
                        context=event.context,
                        conversation_sequence=self._next_sequence(),
                        occurred_at=datetime.now(UTC),
                        text=event.accumulated_text,
                        delta=event.delta,
                        transcript_revision=event.revision,
                        replaces_previous=event.replaces_previous,
                        audio_timestamp_us=event.audio_timestamp_us,
                    )
                )
            elif isinstance(event, CapabilityDialogueStateChanged):
                await self._emit(
                    DialogueStateChanged(
                        event_id=str(uuid.uuid4()),
                        context=event.context,
                        conversation_sequence=self._next_sequence(),
                        occurred_at=event.occurred_at,
                        from_state=event.from_state,
                        to_state=event.to_state,
                        transition=event.transition,
                    )
                )
            elif isinstance(event, UserTurnCommitted):
                await self._emit(
                    InputTranscriptCompleted(
                        event_id=str(uuid.uuid4()),
                        context=event.context,
                        conversation_sequence=self._next_sequence(),
                        occurred_at=event.committed_at,
                        text=event.text,
                        transcript_revision=event.transcript_revision,
                        provider_endpoint_observed=event.provider_endpoint_observed,
                        continuation_of_turn_id=event.continuation_of_turn_id,
                        speech_ended_ns=event.speech_ended_ns,
                        input_id=event.input_id,
                        input_observation_id=event.input_observation_id,
                        input_version=event.input_version,
                        admission_reason=event.admission_reason,
                        endpoint_decision=event.endpoint_decision,
                        endpoint_source=event.endpoint_source,
                        input_relation=event.input_relation,
                        input_relation_source=event.input_relation_source,
                        related_turn_id=event.related_turn_id,
                        supersedes_unplayed_reply=event.supersedes_unplayed_reply,
                    )
                )
            elif isinstance(event, CapabilityAssistantYieldRequested):
                target_response = event.context.response_id
                if (
                    target_response is not None
                    and self._active_response_id is not None
                    and target_response != self._active_response_id
                ):
                    # A queued cancellation for A must never cancel replacement B.
                    if event.revokes_sentence_permit_id is not None:
                        await self._emit(AssistantYieldRequested(
                            event_id=str(uuid.uuid4()), context=event.context,
                            conversation_sequence=self._next_sequence(), occurred_at=datetime.now(UTC),
                            reason=event.reason, revokes_sentence_permit_id=event.revokes_sentence_permit_id))
                    await self._input_pipeline.assistant_yielded(context=event.context)
                    continue
                await self._emit(
                    AssistantYieldRequested(
                        event_id=str(uuid.uuid4()),
                        context=event.context,
                        conversation_sequence=self._next_sequence(),
                        occurred_at=datetime.now(UTC),
                        reason=event.reason,
                        speech_started_ns=event.speech_started_ns,
                        sentence_permit=event.sentence_permit,
                        revokes_sentence_permit_id=event.revokes_sentence_permit_id,
                    )
                )
                if self._active_response_id is not None:
                    await self._cancel_response(
                        CancelResponse(
                            command_id=f"yield:{self._active_response_id}",
                            idempotency_key=f"yield:{self._active_response_id}",
                            context=replace(
                                event.context,
                                response_id=self._active_response_id,
                            ),
                            response_id=self._active_response_id,
                            reason=event.reason,
                        )
                    )
                elif self._external_speech_id is not None and target_response in {None, self._external_speech_id}:
                    speech_id = self._external_speech_id
                    await self.send(
                        CancelSpeech(
                            command_id=f"yield:{speech_id}",
                            idempotency_key=f"yield:{speech_id}",
                            context=event.context,
                            speech_id=speech_id,
                            reason=event.reason,
                        )
                    )
                elif (
                    self._direct_delivery_command is not None
                    and self._response_task is not None
                    and target_response in {None, f"delivery:{self._direct_delivery_command.delivery_id}"}
                ):
                    self._direct_delivery_cancel_reason = event.reason
                    task = self._response_task
                    task.cancel()
                    await task
                else:
                    # Brain/TTS generation may already be complete while its
                    # audio is still buffered in the browser.  Playback is a
                    # separate lifecycle: a floor claim must still interrupt
                    # that delivery and truncate future model context to what
                    # the client confirms it actually played.
                    unsettled_speech_id = (f"response:{target_response}" if target_response is not None
                                           else next(iter(self._unsettled_model_speech_ids), None))
                    if unsettled_speech_id in self._unsettled_model_speech_ids:
                        assert unsettled_speech_id is not None
                        await self._cancel_model_speech(
                            unsettled_speech_id,
                            reason=event.reason,
                        )
                await self._input_pipeline.assistant_yielded(context=event.context)
            elif isinstance(event, CascadedCapabilityFailed):
                await self._emit(
                    RealtimeCapabilityFailed(
                        event_id=str(uuid.uuid4()),
                        context=event.context,
                        conversation_sequence=self._next_sequence(),
                        occurred_at=datetime.now(UTC),
                        capability=event.capability,
                        error=event.error,
                    )
                )
            elif isinstance(event, SemanticInputRejected):
                message = (
                    "未能确认这段语音的意图，会话已结束，请重新开始后重试。"
                    if event.reason == "unresolved_overlap_deadline" else
                    "日志保存失败，会话已结束，请重新开始后重试。"
                    if event.reason == "input_evidence_unavailable" else
                    "本轮输入已停止处理，请缩短内容或分段后重新开始会话。"
                )
                await self._emit(RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()), context=event.context,
                    conversation_sequence=self._next_sequence(), occurred_at=datetime.now(UTC),
                    capability="semantic_input",
                    error=(message
                           + ("输入证据已保存。" if event.evidence_saved else "输入证据未确认保存。")
                           + f" [{event.reason}]"),
                ))

    async def _pump_audio_plugins(self) -> None:
        assert self._audio_graph is not None
        async for event in self._audio_graph.events():
            payload = asdict(event) if is_dataclass(event) else {"event": repr(event)}
            payload.pop("context", None)
            plugin_id = payload.pop("plugin_id", "unknown")
            await self._emit(
                AudioPluginDiagnostic(
                    event_id=str(uuid.uuid4()),
                    context=event.context,
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    plugin_id=str(plugin_id),
                    diagnostic_type=type(event).__name__,
                    details=payload,
                )
            )

    async def _emit(self, event: RealtimeEvent) -> None:
        if self.output_delivery_allowed(event):
            await self._events.put(event)

    def sentence_playback_permit_current(self, permit: CurrentSentencePermit) -> bool:
        return not self._closed and self._input_pipeline.sentence_playback_permit_current(permit)

    def output_delivery_allowed(self, event: RealtimeEvent) -> bool:
        if not isinstance(event, VERSIONED_OUTPUT_EVENTS):
            return True  # Cancellation/failure/completion facts must still drain.
        response_id: str | None
        if isinstance(event, (SpeechStarted, SpeechTextAccepted, SpeechTextCommitted, SpeechAudioDelta)) or isinstance(event, SpeechTextAlignment) and event.speech_id not in self._model_speech_ids:
            response_id = event.speech_id
        else:
            response_id = (event.context.response_id or getattr(event, "response_id", None)
                           or getattr(event, "speech_id", None))
        return response_id is None or self._input_pipeline.response_delivery_allowed(response_id)

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            typed_event = cast(RealtimeEvent, event)
            if self.output_delivery_allowed(typed_event):
                yield typed_event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._input_task.cancel()
        tasks = [self._input_task]
        if self._plugin_task is not None:
            self._plugin_task.cancel()
            tasks.append(self._plugin_task)
        if self._response_task is not None:
            self._response_task.cancel()
            tasks.append(self._response_task)
        for task in self._detached_response_tasks:
            task.cancel()
            tasks.append(task)
        self._detached_response_tasks.clear()
        if self._external_tts_task is not None:
            self._external_tts_task.cancel()
            tasks.append(self._external_tts_task)
        for task in self._playback_watchdog_tasks.values():
            task.cancel()
            tasks.append(task)
        self._playback_watchdog_tasks.clear()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._speech_lifecycle.close()
        for speech_id in tuple(self._unsettled_model_speech_ids):
            await self._speech_deliveries.mark_uncertain(
                speech_id,
                reason="conversation_closed_before_playback_terminal",
            )
        self._unsettled_model_speech_ids.clear()
        await asyncio.gather(
            self._input_pipeline.close(),
            self._brain.close(),
            self._tts.close(),
            *( (self._audio_graph.close(),) if self._audio_graph is not None else () ),
        )
        await self._events.put(_CLOSED)


def _profile_binding(
    profile: ResolvedRealtimeProfile | None,
    kind: PluginKind,
    fallback: object,
):
    if profile is None:
        return fallback
    selected = [plugin.binding for plugin in profile.plugins if plugin.selection.slot is kind]
    if len(selected) > 1:
        raise ValueError(f"Realtime Profile selects more than one {kind.value} plugin")
    return selected[0] if selected else fallback


class _ConfiguredCapabilityProvider:
    def __init__(self, binding: object, config: dict[str, object]) -> None:
        self._binding = binding
        self._config = config

    async def open(self, *, context: InteractionContext):
        open_session = getattr(self._binding, "open", None)
        if open_session is None:
            raise TypeError("selected capability binding does not expose open()")
        if "config" in inspect.signature(open_session).parameters:
            return await open_session(context=context, config=self._config)
        if self._config:
            raise TypeError(
                "selected capability binding does not accept its profile configuration"
            )
        return await open_session(context=context)


def _profile_provider(
    profile: ResolvedRealtimeProfile | None,
    kind: PluginKind,
    fallback: object,
):
    if profile is None:
        return fallback
    selected = [plugin for plugin in profile.plugins if plugin.selection.slot is kind]
    if len(selected) > 1:
        raise ValueError(f"Realtime Profile selects more than one {kind.value} plugin")
    if not selected:
        return fallback
    plugin = selected[0]
    return _ConfiguredCapabilityProvider(plugin.binding, plugin.selection.config)
