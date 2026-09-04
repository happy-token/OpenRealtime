"""Native end-to-end model implementation of the Realtime Engine seam."""

from __future__ import annotations

import array
import asyncio
import base64
import json
import uuid
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from server.conversation_journal import (
    ArtifactReferenceContent,
    ConversationItem,
    ConversationItemKind,
    ConversationVisibility,
    StructuredContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime.capabilities import (
    AppendTtsText,
    CancelTts,
    CommitTts,
    StartTts,
    TtsAudioFrame,
    TtsCancelled,
    TtsCapabilityProvider,
    TtsCapabilitySession,
    TtsCompleted,
    TtsFailed,
)
from server.realtime.native.provider import (
    NativeRealtimeProvider,
    NativeRealtimeProviderSession,
)
from server.realtime.profile import EngineKind, ResolvedRealtimeProfile
from server.realtime.protocol import (
    AppendAudio,
    AppendSpeechText,
    AudioDelta,
    AudioEncoding,
    AudioFrame,
    CancelResponse,
    CancelSpeech,
    CommitSpeech,
    DeliverItem,
    DeliveryMode,
    DialogueStateChanged,
    DisplayContentDelta,
    InputTranscriptCompleted,
    InterruptedContextPolicy,
    ItemDeliveryCancelled,
    ItemDeliveryCompleted,
    ItemDeliveryFailed,
    ItemDeliveryQueued,
    ItemDeliveryStarted,
    ItemDisplayPresented,
    ItemProjected,
    ProjectCommittedItem,
    RealtimeCapabilityFailed,
    RealtimeCommand,
    RealtimeEvent,
    ReportPlaybackProgress,
    RequestResponse,
    ResponseCancelled,
    ResponseCompleted,
    ResponseFailed,
    ResponseStarted,
    SpeechAudioCompleted,
    SpeechAudioDelta,
    SpeechContextPolicy,
    SpeechPlaybackProgress,
    SpokenContentDelta,
    StartSpeech,
    ToolRequested,
)
from server.realtime.scope import conversation_scope
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryRecord,
    SpeechDeliveryStore,
    SpeechLifecycle,
)
from server.tools.policy_gateway import ToolOrigin
from server.tools.registry import ToolRegistry
from server.turn_policy.states import DialogueState

_CLOSED = object()


class NativeTtsError(RuntimeError):
    """Typed failure surfaced by the optional Native external TTS lane."""


class NativeRealtimeEngine:
    def __init__(
        self,
        *,
        provider: NativeRealtimeProvider,
        tts: TtsCapabilityProvider | None = None,
        speech_deliveries: SpeechDeliveryStore | None = None,
        tools: ToolRegistry | None = None,
        input_sample_rate_hz: int = 24_000,
        output_sample_rate_hz: int = 24_000,
    ) -> None:
        if min(input_sample_rate_hz, output_sample_rate_hz) <= 0:
            raise ValueError("native sample rates must be positive")
        self._provider = provider
        self._tts = tts
        self._speech_deliveries = speech_deliveries or InMemorySpeechDeliveryStore()
        self._tools = tools or ToolRegistry()
        self._input_sample_rate_hz = input_sample_rate_hz
        self._output_sample_rate_hz = output_sample_rate_hz

    async def open(
        self,
        *,
        context: InteractionContext,
        profile: object,
    ) -> NativeRealtimeConversation:
        if (
            isinstance(profile, ResolvedRealtimeProfile)
            and profile.engine_kind is not EngineKind.NATIVE
        ):
            raise ValueError("Native Realtime Engine requires a native profile")
        provider = await self._provider.open(context=context, profile=profile)
        try:
            tts = await self._tts.open(context=context) if self._tts is not None else None
        except Exception:
            await provider.close()
            raise
        return NativeRealtimeConversation(
            context=context,
            provider=provider,
            tts=tts,
            speech_deliveries=self._speech_deliveries,
            tools=self._tools,
            input_sample_rate_hz=self._input_sample_rate_hz,
            output_sample_rate_hz=self._output_sample_rate_hz,
        )


class NativeRealtimeConversation:
    def __init__(
        self,
        *,
        context: InteractionContext,
        provider: NativeRealtimeProviderSession,
        tts: TtsCapabilitySession | None,
        speech_deliveries: SpeechDeliveryStore,
        tools: ToolRegistry,
        input_sample_rate_hz: int,
        output_sample_rate_hz: int,
    ) -> None:
        self._context = context
        self._provider = provider
        self._tts = tts
        self._speech_deliveries = speech_deliveries
        self._tools = tools
        self._speech_lifecycle = SpeechLifecycle(speech_deliveries)
        self._input_sample_rate_hz = input_sample_rate_hz
        self._output_sample_rate_hz = output_sample_rate_hz
        self._events: asyncio.Queue[RealtimeEvent | object] = asyncio.Queue(maxsize=128)
        self._commands_by_idempotency_key: dict[str, RealtimeCommand] = {}
        self._last_projected_thread_sequence = 0
        self._projected_item_by_id: dict[str, ConversationItem] = {}
        self._projected_sequence_by_item_id: dict[str, int] = {}
        self._sequence = 0
        self._response_sequence_by_id: dict[str, int] = {}
        self._response_command_by_id: dict[str, RequestResponse] = {}
        self._native_output_item_ids: set[str] = set()
        self._started_response_ids: set[str] = set()
        self._pending_tool_calls_by_response_id: dict[str, set[str]] = {}
        self._tool_cycle_response_ids: set[str] = set()
        self._provider_turn_done_response_ids: set[str] = set()
        self._local_response_by_provider_id: dict[str, str] = {}
        self._provider_response_by_local_id: dict[str, str] = {}
        self._pending_cancel_by_response_id: dict[str, CancelResponse] = {}
        self._provider_item_by_speech_id: dict[str, str] = {}
        self._played_audio_end_by_speech_id: dict[str, int] = {}
        self._audio_sequence_by_response_id: dict[str, int] = {}
        self._audio_timestamp_by_response_id: dict[str, int] = {}
        self._display_source_by_response_id: dict[str, str] = {}
        self._started_speech_ids: set[str] = set()
        self._unsettled_speech_ids: set[str] = set()
        self._external_speech_id: str | None = None
        self._external_tts_task: asyncio.Task[None] | None = None
        self._pending_deliveries: deque[DeliverItem] = deque()
        self._delivery_by_response_id: dict[str, DeliverItem] = {}
        self._direct_delivery_task: asyncio.Task[None] | None = None
        self._direct_response_command: RequestResponse | None = None
        self._direct_cancel_reason: str | None = None
        self._last_input_context = context
        self._input_context_by_provider_item_id: dict[str, InteractionContext] = {}
        self._input_transcript_revision = 0
        self._dialogue_state = DialogueState.IDLE
        self._provider_input_active = False
        self._closed = False
        self._provider_task = asyncio.create_task(
            self._pump_provider_events(),
            name=f"native-realtime-provider-{context.voice_session_id}",
        )

    async def send(self, command: RealtimeCommand) -> None:
        if self._closed:
            raise RuntimeError("native realtime conversation is closed")
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        previous = self._commands_by_idempotency_key.get(command.idempotency_key)
        if previous is not None:
            if previous != command:
                raise ValueError("idempotency key was reused with different command content")
            return
        if isinstance(command, AppendAudio):
            self._last_input_context = command.context
            provider_audio = _resample_input_audio(
                command.frame,
                target_sample_rate_hz=self._input_sample_rate_hz,
            )
            await self._provider.send(
                {
                    "type": "input_audio_buffer.append",
                    "event_id": command.command_id,
                    "audio": base64.b64encode(provider_audio).decode("ascii"),
                }
            )
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
            await self._events.put(accepted)
            assert self._tts is not None
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
            await self._events.put(committed)
            assert self._tts is not None
            await self._tts.send(CommitTts(speech_id=command.speech_id))
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, CancelSpeech):
            self._require_external_speech(command.speech_id)
            assert self._tts is not None
            tts_task = self._external_tts_task
            await self._tts.send(
                CancelTts(speech_id=command.speech_id, reason=command.reason)
            )
            if tts_task is not None:
                await tts_task
            cancelled = await self._speech_lifecycle.cancel(
                command,
                sequence=self._next_sequence,
            )
            await self._events.put(cancelled)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, ProjectCommittedItem):
            await self._project(command)
            self._commands_by_idempotency_key[command.idempotency_key] = command
            return
        if isinstance(command, ReportPlaybackProgress):
            await self._report_playback(command)
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
        raise TypeError(f"unsupported native realtime command: {type(command).__name__}")

    async def _request_response(self, command: RequestResponse) -> None:
        if self._external_speech_id is not None:
            raise ValueError("native realtime conversation already has active output")
        if self._direct_delivery_task is not None:
            raise ValueError("native realtime conversation already has active output")
        if command.minimum_thread_sequence > self._last_projected_thread_sequence:
            raise ValueError(
                "response requires thread sequence "
                f"{command.minimum_thread_sequence}, but native engine has projected through "
                f"{self._last_projected_thread_sequence}"
            )
        if command.response_id in self._response_command_by_id:
            raise ValueError("native response identity is already active")
        self._response_command_by_id[command.response_id] = command
        if command.output_item_id is not None:
            self._native_output_item_ids.add(command.output_item_id)
        await self._send_provider_response(
            command,
            event_id=command.command_id,
        )

    async def _send_provider_response(
        self,
        command: RequestResponse,
        *,
        event_id: str,
    ) -> None:
        await self._provider.send(
            {
                "type": "response.create",
                "event_id": event_id,
                "response": {
                    "conversation": "auto",
                    "metadata": {
                        "voiceagent_response_id": command.response_id,
                        "voiceagent_output_item_id": command.output_item_id or "",
                    },
                },
            }
        )

    async def _start_external_speech(self, command: StartSpeech) -> None:
        if self._tts is None:
            raise RuntimeError(
                "native realtime profile has no TTS capability for external speech"
            )
        if (
            self._external_speech_id is not None
            or self._response_command_by_id
            or self._direct_delivery_task is not None
        ):
            raise ValueError("native realtime conversation already has active output")
        started = await self._speech_lifecycle.start(
            command,
            sequence=self._next_sequence,
        )
        try:
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
            name=f"native-external-speech-{command.speech_id}",
        )
        await self._events.put(started)

    def _require_external_speech(self, speech_id: str) -> None:
        if self._external_speech_id != speech_id:
            raise ValueError("speech output is not active")

    async def _pump_external_tts(self, command: StartSpeech) -> None:
        assert self._tts is not None
        segment_index = 0
        try:
            async for event in self._tts.events():
                if event.speech_id != command.speech_id:
                    continue
                if isinstance(event, TtsAudioFrame):
                    await self._events.put(
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
                    await self._events.put(
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
                    await self._events.put(
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

    async def _cancel_response(self, command: CancelResponse) -> None:
        direct = self._direct_response_command
        if direct is not None and direct.response_id == command.response_id:
            if self._tts is None or self._direct_delivery_task is None:
                raise ValueError("native response identity is not active")
            self._direct_cancel_reason = command.reason
            await self._tts.send(
                CancelTts(
                    speech_id=f"response:{command.response_id}",
                    reason=command.reason,
                )
            )
            await self._direct_delivery_task
            return
        if command.response_id not in self._response_command_by_id:
            raise ValueError("native response identity is not active")
        provider_response_id = self._provider_response_by_local_id.get(
            command.response_id
        )
        if provider_response_id is None:
            self._pending_cancel_by_response_id[command.response_id] = command
            return
        speech_id = f"response:{command.response_id}"
        provider_item_id = self._provider_item_by_speech_id.get(speech_id)
        played_audio_end_us = self._played_audio_end_by_speech_id.get(speech_id, 0)
        if provider_item_id is not None and played_audio_end_us > 0:
            await self._provider.send(
                {
                    "type": "conversation.item.truncate",
                    "event_id": f"{command.command_id}:truncate",
                    "item_id": provider_item_id,
                    "content_index": 0,
                    "audio_end_ms": played_audio_end_us // 1_000,
                }
            )
        await self._provider.send(
            {
                "type": "response.cancel",
                "event_id": command.command_id,
                "response_id": provider_response_id,
            }
        )

    async def _report_playback(self, command: ReportPlaybackProgress) -> None:
        if command.speech_id not in self._started_speech_ids:
            progress = await self._speech_lifecycle.report(
                command,
                sequence=self._next_sequence,
            )
            await self._events.put(progress)
            return
        if command.speech_id not in self._unsettled_speech_ids:
            raise ValueError("speech delivery is not active")
        record = await self._speech_deliveries.report_progress(
            command.speech_id,
            delivered_text_end=command.delivered_text_end,
            played_audio_end_us=command.played_audio_end_us,
            precision=command.precision,
            completed=command.completed,
        )
        self._played_audio_end_by_speech_id[command.speech_id] = (
            command.played_audio_end_us
        )
        if command.completed:
            self._unsettled_speech_ids.remove(command.speech_id)
        await self._events.put(
            SpeechPlaybackProgress(
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
            )
        )
    async def _maybe_continue_after_tools(
        self,
        response_id: str,
        *,
        event_id: str,
    ) -> None:
        pending_calls = self._pending_tool_calls_by_response_id.get(response_id)
        if (
            response_id not in self._tool_cycle_response_ids
            or response_id not in self._provider_turn_done_response_ids
            or pending_calls
        ):
            return
        command = self._response_command_by_id.get(response_id)
        if command is None:
            return
        self._tool_cycle_response_ids.remove(response_id)
        self._provider_turn_done_response_ids.remove(response_id)
        self._pending_tool_calls_by_response_id.pop(response_id, None)
        await self._send_provider_response(command, event_id=event_id)

    async def _project(self, command: ProjectCommittedItem) -> None:
        item = command.item
        if item.sequence > self._last_projected_thread_sequence + 1:
            raise ValueError(
                f"cannot project thread sequence {item.sequence} before "
                f"{self._last_projected_thread_sequence + 1}"
            )
        if (
            ConversationVisibility.MODEL in item.visibility
            and item.item_id not in self._native_output_item_ids
        ):
            provider_item = _provider_item(item)
            if provider_item is not None:
                await self._provider.send(
                    {
                        "type": "conversation.item.create",
                        "event_id": command.command_id,
                        "item": provider_item,
                    }
                )
        self._last_projected_thread_sequence = max(
            self._last_projected_thread_sequence,
            item.sequence,
        )
        self._projected_item_by_id[item.item_id] = item
        self._projected_sequence_by_item_id[item.item_id] = item.sequence
        await self._events.put(
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
            if response_id is not None and call_id is not None:
                pending_calls = self._pending_tool_calls_by_response_id.get(
                    response_id
                )
                if pending_calls is not None and call_id in pending_calls:
                    pending_calls.remove(call_id)
                    await self._maybe_continue_after_tools(
                        response_id,
                        event_id=f"continue:{command.command_id}",
                    )

    async def _queue_delivery(self, command: DeliverItem) -> None:
        thread_sequence = self._projected_sequence_by_item_id.get(command.item_id)
        if thread_sequence is None:
            raise ValueError(f"item {command.item_id!r} has not been projected")
        await self._events.put(
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
            or self._response_command_by_id
            or self._external_speech_id is not None
            or self._direct_delivery_task is not None
            or not self._pending_deliveries
        ):
            return
        command = self._pending_deliveries.popleft()
        thread_sequence = self._projected_sequence_by_item_id[command.item_id]
        await self._events.put(
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
            try:
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
            except Exception as error:
                self._delivery_by_response_id.pop(response_id, None)
                await self._emit_delivery_failed(command, error=str(error))
                await self._dispatch_next_delivery()
                raise
            return
        if command.mode is DeliveryMode.DISPLAY_ONLY:
            item = self._projected_item_by_id[command.item_id]
            markdown = (
                item.display.markdown
                if item.display is not None
                else "\n".join(
                    part.text for part in item.content if isinstance(part, TextContent)
                )
            )
            if not markdown:
                await self._emit_delivery_failed(
                    command,
                    error=f"item {item.item_id!r} has no display representation",
                )
            else:
                await self._events.put(
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
                await self._emit_delivery_completed(command)
        elif command.mode is DeliveryMode.SILENT:
            await self._emit_delivery_completed(command)
        else:
            response_id = f"delivery:{command.delivery_id}"
            response = RequestResponse(
                command_id=f"speech:{command.command_id}",
                idempotency_key=f"speech:{command.idempotency_key}",
                context=replace(command.context, response_id=response_id),
                response_id=response_id,
                minimum_thread_sequence=thread_sequence,
                output_item_id=command.output_item_id,
            )
            self._direct_response_command = response
            self._direct_delivery_task = asyncio.create_task(
                self._run_direct_speech_delivery(command, response),
                name=f"native-direct-speech-{command.delivery_id}",
            )
            return
        await self._dispatch_next_delivery()

    async def _run_direct_speech_delivery(
        self,
        delivery: DeliverItem,
        response: RequestResponse,
    ) -> None:
        speech_id = f"response:{response.response_id}"
        try:
            if self._tts is None:
                raise RuntimeError(
                    "native realtime profile has no TTS capability for direct speech"
                )
            item = self._projected_item_by_id[delivery.item_id]
            spoken_text = (
                item.spoken.text
                if item.spoken is not None
                else "\n".join(_content_text(part) for part in item.content)
            )
            if not spoken_text:
                raise ValueError(f"item {item.item_id!r} has no spoken representation")
            await self._emit_response(ResponseStarted, command=response)
            await self._emit_response(
                SpokenContentDelta,
                command=response,
                delta=spoken_text,
            )
            await self._speech_deliveries.start(
                SpeechDeliveryRecord(
                    speech_id=speech_id,
                    context=response.context,
                    source_item_id=delivery.item_id,
                    context_policy=SpeechContextPolicy.AUTO,
                    interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
                )
            )
            self._started_speech_ids.add(speech_id)
            self._unsettled_speech_ids.add(speech_id)
            await self._speech_deliveries.append_text(speech_id, spoken_text)
            await self._speech_deliveries.commit_text(speech_id)
            await self._tts.send(
                StartTts(speech_id=speech_id, context=delivery.context)
            )
            await self._tts.send(
                AppendTtsText(
                    speech_id=speech_id,
                    text_sequence=1,
                    delta=spoken_text,
                )
            )
            await self._tts.send(CommitTts(speech_id=speech_id))
            async for event in self._tts.events():
                if event.speech_id != speech_id:
                    continue
                if isinstance(event, TtsAudioFrame):
                    await self._emit_response(
                        AudioDelta,
                        command=response,
                        frame=event.frame,
                        segment_index=event.frame.sequence,
                        speech_id=speech_id,
                    )
                elif isinstance(event, TtsCompleted):
                    await self._emit_response(ResponseCompleted, command=response)
                    await self._emit_delivery_completed(delivery)
                    return
                elif isinstance(event, TtsCancelled):
                    reason = self._direct_cancel_reason or event.reason
                    if speech_id in self._unsettled_speech_ids:
                        await self._speech_deliveries.cancel(speech_id, reason=reason)
                        self._unsettled_speech_ids.remove(speech_id)
                    await self._emit_response(
                        ResponseCancelled,
                        command=response,
                        reason=reason,
                    )
                    await self._emit_delivery_cancelled(delivery, reason=reason)
                    return
                elif isinstance(event, TtsFailed):
                    raise NativeTtsError(event.error)
        except Exception as error:  # noqa: BLE001 - capability failure is public
            failure = str(error)
            if speech_id in self._unsettled_speech_ids:
                await self._speech_deliveries.fail(speech_id, reason=failure)
                self._unsettled_speech_ids.remove(speech_id)
            await self._events.put(
                RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()),
                    context=delivery.context,
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    capability="tts",
                    error=failure,
                )
            )
            await self._emit_response(
                ResponseFailed,
                command=response,
                error=failure,
            )
            await self._emit_delivery_failed(delivery, error=failure)
        finally:
            self._direct_delivery_task = None
            self._direct_response_command = None
            self._direct_cancel_reason = None
            await self._dispatch_next_delivery()

    async def _emit_delivery_completed(self, command: DeliverItem) -> None:
        await self._events.put(
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

    async def _emit_delivery_failed(
        self,
        command: DeliverItem,
        *,
        error: str,
    ) -> None:
        await self._events.put(
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

    async def _emit_delivery_cancelled(
        self,
        command: DeliverItem,
        *,
        reason: str,
    ) -> None:
        await self._events.put(
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

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    async def _pump_provider_events(self) -> None:
        try:
            async for event in self._provider.events():
                await self._handle_provider_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - provider failure is public
            await self._events.put(
                RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()),
                    context=self._context,
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    capability="native_provider",
                    error=f"{type(error).__name__}: {error}",
                )
            )
        else:
            if not self._closed:
                await self._events.put(
                    RealtimeCapabilityFailed(
                        event_id=str(uuid.uuid4()),
                        context=self._context,
                        conversation_sequence=self._next_sequence(),
                        occurred_at=datetime.now(UTC),
                        capability="native_provider",
                        error="provider event stream closed",
                    )
                )

    async def _handle_provider_event(self, event: Mapping[str, object]) -> None:
        event_type = event.get("type")
        if event_type == "input_audio_buffer.speech_started":
            self._provider_input_active = True
            self._input_context_by_provider_item_id[
                _required_string(event, "item_id")
            ] = self._last_input_context
            await self._transition_dialogue(
                DialogueState.DUAL
                if self._dialogue_state is DialogueState.SPEAK
                else DialogueState.LISTEN,
                transition="provider_speech_started",
                context=self._last_input_context,
            )
            return
        if event_type == "input_audio_buffer.speech_stopped":
            self._provider_input_active = False
            await self._transition_dialogue(
                DialogueState.SPEAK
                if self._dialogue_state is DialogueState.DUAL
                else DialogueState.WAIT,
                transition="provider_speech_stopped",
                context=self._last_input_context,
            )
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            item_id = _required_string(event, "item_id")
            self._input_transcript_revision += 1
            await self._events.put(
                InputTranscriptCompleted(
                    event_id=str(uuid.uuid4()),
                    context=self._input_context_by_provider_item_id.pop(
                        item_id,
                        self._last_input_context,
                    ),
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    text=_required_string(event, "transcript"),
                    transcript_revision=self._input_transcript_revision,
                    provider_endpoint_observed=True,
                )
            )
            return
        if event_type == "response.created":
            response = _mapping(event.get("response"))
            provider_response_id = _required_string(response, "id")
            local_response_id = _local_response_id(response)
            command = self._response_command_by_id.get(local_response_id)
            if command is None:
                raise ValueError("provider created an unknown native response")
            self._local_response_by_provider_id[provider_response_id] = local_response_id
            self._provider_response_by_local_id[local_response_id] = provider_response_id
            if local_response_id not in self._started_response_ids:
                self._started_response_ids.add(local_response_id)
                await self._transition_dialogue(
                    DialogueState.DUAL
                    if self._provider_input_active
                    else DialogueState.SPEAK,
                    transition="provider_response_started",
                    context=command.context,
                )
                await self._emit_response(
                    ResponseStarted,
                    command=command,
                )
            pending_cancel = self._pending_cancel_by_response_id.get(local_response_id)
            if pending_cancel is not None:
                await self._provider.send(
                    {
                        "type": "response.cancel",
                        "event_id": pending_cancel.command_id,
                        "response_id": provider_response_id,
                    }
                )
            return
        if event_type in {
            "response.output_text.delta",
            "response.output_audio_transcript.delta",
            "response.output_audio.delta",
        }:
            provider_response_id = _required_string(event, "response_id")
            local_response_id = self._local_response_by_provider_id.get(
                provider_response_id
            )
            if local_response_id is None:
                raise ValueError("provider streamed an unknown native response")
            command = self._response_command_by_id[local_response_id]
            if event_type == "response.output_text.delta":
                source = self._display_source_by_response_id.setdefault(
                    local_response_id,
                    "output_text",
                )
                if source == "output_text":
                    await self._emit_response(
                        DisplayContentDelta,
                        command=command,
                        delta=_required_string(event, "delta"),
                    )
            elif event_type == "response.output_audio_transcript.delta":
                delta = _required_string(event, "delta")
                await self._ensure_speech_delivery(command)
                await self._speech_deliveries.append_text(
                    f"response:{local_response_id}",
                    delta,
                )
                source = self._display_source_by_response_id.setdefault(
                    local_response_id,
                    "audio_transcript",
                )
                if source == "audio_transcript":
                    await self._emit_response(
                        DisplayContentDelta,
                        command=command,
                        delta=delta,
                    )
                await self._emit_response(
                    SpokenContentDelta,
                    command=command,
                    delta=delta,
                )
            else:
                await self._emit_audio_delta(command, event)
            return
        if event_type == "response.function_call_arguments.done":
            provider_response_id = _required_string(event, "response_id")
            local_response_id = self._local_response_by_provider_id.get(
                provider_response_id
            )
            if local_response_id is None:
                raise ValueError("provider requested a tool for an unknown response")
            command = self._response_command_by_id[local_response_id]
            call_id = _required_string(event, "call_id")
            self._tool_cycle_response_ids.add(local_response_id)
            self._pending_tool_calls_by_response_id.setdefault(
                local_response_id,
                set(),
            ).add(call_id)
            arguments = json.loads(_required_string(event, "arguments"))
            if not isinstance(arguments, dict):
                raise TypeError("native tool arguments must decode to an object")
            tool_name = _required_string(event, "name")
            tool = self._tools.get(tool_name)
            if tool is None:
                raise ValueError(
                    f"native provider requested unregistered tool {tool_name!r}"
                )
            response_sequence = (
                self._response_sequence_by_id.get(local_response_id, 0) + 1
            )
            self._response_sequence_by_id[local_response_id] = response_sequence
            await self._events.put(
                ToolRequested(
                    event_id=str(uuid.uuid4()),
                    context=replace(
                        command.context,
                        response_id=local_response_id,
                        call_id=call_id,
                    ),
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    response_id=local_response_id,
                    response_sequence=response_sequence,
                    call_id=call_id,
                    tool_name=tool.name,
                    tool_version=tool.version,
                    arguments=arguments,
                    latency=tool.latency,
                    origin=ToolOrigin.NATIVE_ENGINE,
                )
            )
            return
        if event_type == "response.done":
            await self._finish_response(_mapping(event.get("response")))
            return
        if event_type == "error":
            error = _mapping(event.get("error"))
            await self._events.put(
                RealtimeCapabilityFailed(
                    event_id=str(uuid.uuid4()),
                    context=self._context,
                    conversation_sequence=self._next_sequence(),
                    occurred_at=datetime.now(UTC),
                    capability="native_provider",
                    error=str(error.get("message") or "native provider error"),
                )
            )

    async def _emit_audio_delta(
        self,
        command: RequestResponse,
        event: Mapping[str, object],
    ) -> None:
        audio = base64.b64decode(_required_string(event, "delta"))
        if len(audio) % 2:
            raise ValueError("native provider returned misaligned PCM16 audio")
        await self._ensure_speech_delivery(command)
        response_id = command.response_id
        speech_id = f"response:{response_id}"
        provider_item_id = event.get("item_id")
        if isinstance(provider_item_id, str) and provider_item_id:
            self._provider_item_by_speech_id[speech_id] = provider_item_id
        audio_sequence = self._audio_sequence_by_response_id.get(response_id, 0)
        timestamp_us = self._audio_timestamp_by_response_id.get(response_id, 0)
        duration_us = round(
            len(audio) / 2 * 1_000_000 / self._output_sample_rate_hz
        )
        self._audio_sequence_by_response_id[response_id] = audio_sequence + 1
        self._audio_timestamp_by_response_id[response_id] = timestamp_us + duration_us
        await self._emit_response(
            AudioDelta,
            command=command,
            frame=AudioFrame(
                stream_id=f"native-output:{response_id}",
                sequence=audio_sequence,
                timestamp_us=timestamp_us,
                duration_us=duration_us,
                encoding=AudioEncoding.PCM_S16LE,
                sample_rate_hz=self._output_sample_rate_hz,
                channels=1,
                data=audio,
            ),
            segment_index=audio_sequence,
            speech_id=speech_id,
        )

    async def _ensure_speech_delivery(self, command: RequestResponse) -> None:
        speech_id = f"response:{command.response_id}"
        if speech_id in self._started_speech_ids:
            return
        await self._speech_deliveries.start(
            SpeechDeliveryRecord(
                speech_id=speech_id,
                context=replace(command.context, response_id=command.response_id),
                source_item_id=command.output_item_id,
                context_policy=SpeechContextPolicy.AUTO,
                interrupted_context_policy=InterruptedContextPolicy.DELIVERED_ONLY,
            )
        )
        self._started_speech_ids.add(speech_id)
        self._unsettled_speech_ids.add(speech_id)

    async def _finish_response(self, response: Mapping[str, object]) -> None:
        provider_response_id = _required_string(response, "id")
        local_response_id = self._local_response_by_provider_id.pop(
            provider_response_id,
            _local_response_id(response),
        )
        command = self._response_command_by_id.get(local_response_id)
        if command is None:
            raise ValueError("provider completed an unknown native response")
        delivery = self._delivery_by_response_id.get(local_response_id)
        speech_id = f"response:{local_response_id}"
        self._provider_response_by_local_id.pop(local_response_id, None)
        self._display_source_by_response_id.pop(local_response_id, None)
        self._pending_cancel_by_response_id.pop(local_response_id, None)
        status = str(response.get("status") or "failed")
        if (
            status == "completed"
            and local_response_id in self._tool_cycle_response_ids
        ):
            self._provider_turn_done_response_ids.add(local_response_id)
            await self._transition_dialogue(
                DialogueState.LISTEN
                if self._provider_input_active
                else DialogueState.WAIT,
                transition="provider_tool_turn_completed",
                context=command.context,
            )
            await self._maybe_continue_after_tools(
                local_response_id,
                event_id=f"continue:{provider_response_id}",
            )
            return
        self._response_command_by_id.pop(local_response_id, None)
        self._delivery_by_response_id.pop(local_response_id, None)
        self._started_response_ids.discard(local_response_id)
        self._tool_cycle_response_ids.discard(local_response_id)
        self._provider_turn_done_response_ids.discard(local_response_id)
        self._pending_tool_calls_by_response_id.pop(local_response_id, None)
        await self._transition_dialogue(
            DialogueState.LISTEN
            if self._provider_input_active
            else DialogueState.IDLE,
            transition=f"provider_response_{status}",
            context=command.context,
        )
        if status == "completed":
            if speech_id in self._started_speech_ids:
                record = await self._speech_deliveries.get(speech_id)
                if record is not None and record.intended_spoken_content:
                    await self._speech_deliveries.commit_text(speech_id)
            await self._emit_response(ResponseCompleted, command=command)
            if delivery is not None:
                await self._emit_delivery_completed(delivery)
        elif status == "cancelled":
            reason = _response_reason(response, "provider_cancelled")
            if speech_id in self._unsettled_speech_ids:
                await self._speech_deliveries.cancel(speech_id, reason=reason)
                self._unsettled_speech_ids.remove(speech_id)
            await self._emit_response(
                ResponseCancelled,
                command=command,
                reason=reason,
            )
            if delivery is not None:
                await self._emit_delivery_cancelled(delivery, reason=reason)
        else:
            error = _response_reason(response, f"provider_response_{status}")
            if speech_id in self._unsettled_speech_ids:
                await self._speech_deliveries.fail(speech_id, reason=error)
                self._unsettled_speech_ids.remove(speech_id)
            await self._emit_response(
                ResponseFailed,
                command=command,
                error=error,
            )
            if delivery is not None:
                await self._emit_delivery_failed(delivery, error=error)
        await self._dispatch_next_delivery()

    async def _transition_dialogue(
        self,
        to_state: DialogueState,
        *,
        transition: str,
        context: InteractionContext,
    ) -> None:
        from_state = self._dialogue_state
        if from_state is to_state:
            return
        self._dialogue_state = to_state
        await self._events.put(
            DialogueStateChanged(
                event_id=str(uuid.uuid4()),
                context=context,
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                from_state=from_state,
                to_state=to_state,
                transition=transition,
            )
        )

    async def _emit_response(
        self,
        event_type,
        *,
        command: RequestResponse,
        **fields: object,
    ) -> None:
        response_sequence = self._response_sequence_by_id.get(command.response_id, 0) + 1
        self._response_sequence_by_id[command.response_id] = response_sequence
        await self._events.put(
            event_type(
                event_id=str(uuid.uuid4()),
                context=replace(command.context, response_id=command.response_id),
                conversation_sequence=self._next_sequence(),
                occurred_at=datetime.now(UTC),
                response_id=command.response_id,
                response_sequence=response_sequence,
                **fields,
            )
        )

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            yield cast(RealtimeEvent, event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._provider.close()
        await self._provider_task
        for response_id, command in tuple(self._response_command_by_id.items()):
            await self._transition_dialogue(
                DialogueState.IDLE,
                transition="conversation_closed",
                context=command.context,
            )
            await self._emit_response(
                ResponseCancelled,
                command=command,
                reason="conversation_closed",
            )
            delivery = self._delivery_by_response_id.pop(response_id, None)
            if delivery is not None:
                await self._emit_delivery_cancelled(
                    delivery,
                    reason="conversation_closed",
                )
        self._response_command_by_id.clear()
        self._local_response_by_provider_id.clear()
        self._provider_response_by_local_id.clear()
        self._pending_tool_calls_by_response_id.clear()
        if self._tts is not None:
            await self._tts.close()
        if self._external_tts_task is not None:
            await self._external_tts_task
        if self._direct_delivery_task is not None:
            await self._direct_delivery_task
        await self._speech_lifecycle.close()
        for speech_id in tuple(self._unsettled_speech_ids):
            await self._speech_deliveries.mark_uncertain(
                speech_id,
                reason="native_conversation_closed_before_playback_terminal",
            )
        self._unsettled_speech_ids.clear()
        await self._events.put(_CLOSED)


def _provider_item(item: ConversationItem) -> dict[str, object] | None:
    text = "\n".join(_content_text(part) for part in item.content)
    if not text:
        return None
    if item.kind is ConversationItemKind.TOOL_RESULT and item.context.call_id:
        return {
            "id": item.item_id,
            "type": "function_call_output",
            "call_id": item.context.call_id,
            "output": text,
        }
    assistant = item.kind is ConversationItemKind.ASSISTANT_OUTPUT
    return {
        "id": item.item_id,
        "type": "message",
        "role": "assistant" if assistant else "user",
        "content": [
            {
                "type": "output_text" if assistant else "input_text",
                "text": text,
            }
        ],
    }


def _resample_input_audio(
    frame: AudioFrame,
    *,
    target_sample_rate_hz: int,
) -> bytes:
    if frame.encoding is not AudioEncoding.PCM_S16LE or frame.channels != 1:
        raise ValueError("native provider input requires mono PCM S16LE audio")
    if frame.sample_rate_hz == target_sample_rate_hz:
        return frame.data
    samples = array.array("h")
    samples.frombytes(frame.data)
    if not samples:
        return b""
    output_count = round(
        len(samples) * target_sample_rate_hz / frame.sample_rate_hz
    )
    ratio = frame.sample_rate_hz / target_sample_rate_hz
    output = array.array("h")
    for output_index in range(output_count):
        position = output_index * ratio
        lower = min(int(position), len(samples) - 1)
        upper = min(lower + 1, len(samples) - 1)
        fraction = position - lower
        value = round(samples[lower] * (1 - fraction) + samples[upper] * fraction)
        output.append(max(-32_768, min(32_767, value)))
    return output.tobytes()


def _content_text(
    content: TextContent | StructuredContent | ArtifactReferenceContent,
) -> str:
    if isinstance(content, TextContent):
        return content.text
    if isinstance(content, StructuredContent):
        return json.dumps(content.value, ensure_ascii=False, sort_keys=True)
    return f"[artifact:{content.artifact_id} {content.media_type}]"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("native provider event is missing an object")
    return cast(Mapping[str, object], value)


def _required_string(value: Mapping[str, object], key: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field:
        raise ValueError(f"native provider event is missing {key}")
    return field


def _local_response_id(response: Mapping[str, object]) -> str:
    metadata = _mapping(response.get("metadata"))
    return _required_string(metadata, "voiceagent_response_id")


def _response_reason(response: Mapping[str, object], fallback: str) -> str:
    details = response.get("status_details")
    if not isinstance(details, Mapping):
        return fallback
    reason = details.get("reason")
    return reason if isinstance(reason, str) and reason else fallback
