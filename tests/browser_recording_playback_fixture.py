"""Loopback fixture connecting the real browser renderer to recording evidence.

Only providers and microphone input are controlled. No playback receipt is seeded.
This module is started only by the explicitly opted-in owned-schema fixture.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection
from websockets.http11 import Request, Response

from server.application.runtime import ApplicationRuntime
from server.core.interaction_context import InteractionContext
from server.observability.session_connection import SessionConnectionObserver
from server.observability.telemetry import TelemetryIdentity
from server.realtime import (
    AppendSpeechText,
    CancelSpeech,
    CommitSpeech,
    InMemoryRealtimeConversation,
    StartSpeech,
)
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.protocol import AudioEncoding, AudioFrame
from server.realtime.protocol.events import (
    RealtimeEvent,
    SpeechAudioCompleted,
    SpeechAudioDelta,
    SpeechPlaybackProgress,
)
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.realtime.transport.output_stop import OutputStopObservation
from server.transport.frame_parsing import parse_inbound_frame
from server.transport.frames import InboundFrame, OutboundFrame


class RecordingRendererFixture:
    def __init__(self, runtime: ApplicationRuntime, context: InteractionContext, *, scenario: str = "normal") -> None:
        if scenario not in {"normal", "stop", "missing", "disconnect"}:
            raise ValueError("unknown recording renderer scenario")
        self.scenario = scenario
        self.chunk_samples = 3200 if scenario == "normal" else 32000
        self.stop_requested = False
        self.stop_observations: list[dict] = []
        self.control_socket: ServerConnection | None = None
        self.runtime = runtime
        self.context = context
        self.active = False
        self.ready = False
        self.started = False
        self.closed = False
        self.connections = 0
        self.error: str | None = None
        self.receipts: list[dict] = []
        self.canonical: list[dict] = []
        self.sent: list[dict] = []
        self.bridge: RealtimeWebSocketFrameBridge | None = None
        self.events: AsyncIterator[RealtimeEvent] | None = None
        self.conversation: InMemoryRealtimeConversation | None = None
        self.observer: RealtimeTelemetryObserver | None = None
        self.pump: asyncio.Task[None] | None = None

    async def http(self, connection: ServerConnection, request: Request) -> Response | None:
        path = urlsplit(request.path).path
        if path == "/start":
            if not self.ready or self.started or self.closed:
                return connection.respond(409, "scenario not ready")
            self.started = True
            try:
                await self._start()
            except Exception as error:
                self.error = str(error)
                raise
        elif path == "/stop":
            if not self.ready or not self.started or self.stop_requested or self.conversation is None:
                return connection.respond(409, "scenario not ready")
            self.stop_requested = True
            await self.conversation.send(CancelSpeech(command_id="cancel", idempotency_key="cancel",
                context=replace(self.context, generation=self.context.generation + 1, turn_id="fixture-new-input"),
                speech_id="fixture-speech", reason="cancelled"))
        elif path == "/disconnect":
            if not self.stop_requested or self.control_socket is None:
                return connection.respond(409, "scenario not ready")
            await self.control_socket.close(code=1000, reason="fixture fault disconnect")
        elif path == "/late":
            if not self.stop_requested or self.bridge is None:
                return connection.respond(409, "scenario not ready")
            await self.bridge.handle_event(SpeechAudioDelta(event_id="late-audio", context=self.context,
                conversation_sequence=7, occurred_at=datetime.now(UTC), speech_id="fixture-speech", segment_index=2,
                frame=AudioFrame("provider-stream", 2, self.chunk_samples * 2 * 1_000_000 // 16000, 100_000,
                    AudioEncoding.PCM_S16LE, 16000, 1, b"\x02\x00" * 1600)))
        elif path != "/evidence":
            return None
        response = connection.respond(200, json.dumps({
            "connections": self.connections, "ready": self.ready, "started": self.started, "closed": self.closed,
            "error": self.error, "sent": self.sent, "receipts": self.receipts,
            "canonical": self.canonical, "scenario": self.scenario, "stop_observations": self.stop_observations,
        }))
        response.headers["Content-Type"] = "application/json"
        return response

    async def _start(self) -> None:
        ctx = self.context
        bridge, events, observer, conversation = self.bridge, self.events, self.observer, self.conversation
        if bridge is None or events is None or observer is None or conversation is None:
            raise RuntimeError("renderer connection not initialized")
        for command in (
            StartSpeech(command_id="start", idempotency_key="start", context=ctx, speech_id="fixture-speech"),
            AppendSpeechText(command_id="text", idempotency_key="text", context=ctx,
                             speech_id="fixture-speech", text_sequence=1, delta="测试真实播放回执。"),
            CommitSpeech(command_id="commit", idempotency_key="commit", context=ctx, speech_id="fixture-speech"),
        ):
            await conversation.send(command)
            event = await anext(events)
            observer.observe_event(event)
            await bridge.handle_event(event)

        async def drain():
            async for event in events:
                observer.observe_event(event)
                if isinstance(event, SpeechPlaybackProgress):
                    self.canonical.append({
                        "output_epoch": event.output_epoch, "speech_id": event.speech_id,
                        "generation": event.context.generation,
                        "played_position_samples": event.played_position_samples,
                        "sample_rate_hz": event.sample_rate_hz,
                        "completed": event.completed, "stopped": event.stopped,
                    })
                await bridge.handle_event(event)
        self.pump = asyncio.create_task(drain())
        # Two distinguishable contiguous chunks, deliberately using a provider
        # stream name. Bridge normalization must retain the speech-local clock.
        duration_us = self.chunk_samples * 1_000_000 // 16000
        for index, amplitude in enumerate((1000, -1000)):
            await bridge.handle_event(SpeechAudioDelta(
                event_id=f"audio-{index}", context=ctx, conversation_sequence=4 + index,
                occurred_at=datetime.now(UTC), speech_id="fixture-speech", segment_index=index,
                frame=AudioFrame("provider-stream", index, index * duration_us, duration_us,
                                 AudioEncoding.PCM_S16LE, 16000, 1,
                                 amplitude.to_bytes(2, "little", signed=True) * self.chunk_samples),
            ))
        if self.scenario == "normal":
            await bridge.handle_event(SpeechAudioCompleted(
                event_id="audio-complete", context=ctx, conversation_sequence=6,
                occurred_at=datetime.now(UTC), speech_id="fixture-speech",
            ))

    async def handle(self, socket: ServerConnection) -> None:
        # React development initialization may discard a connection before
        # the scenario starts. Only that empty, fully settled owner may be
        # replaced; a started scenario can never be rebound on reconnect.
        if self.active or self.started or self.error is not None:
            await socket.close(code=1013, reason="fixture already owned")
            return
        self.active = True
        self.closed = False
        self.connections += 1
        self.control_socket = socket
        conversation = InMemoryRealtimeConversation(context=self.context, speech_deliveries=self.runtime.speech_deliveries)
        self.conversation = conversation
        recorder = self.runtime.open_recording(self.context)
        if recorder is None:
            await conversation.close()
            raise RuntimeError("fixture recording unavailable")
        self.events = conversation.events()
        self.observer = RealtimeTelemetryObserver(self.runtime.telemetry.bind(TelemetryIdentity(
            tenant_id=self.context.tenant_id, user_id=self.context.user_id,
            device_id=self.context.device_id, voice_session_id=self.context.voice_session_id,
            thread_id=self.context.thread_id,
        )))
        fixture = self
        connection_observer = SessionConnectionObserver(self.runtime.telemetry.bind(TelemetryIdentity(
            tenant_id=self.context.tenant_id, user_id=self.context.user_id,
            device_id=self.context.device_id, voice_session_id=self.context.voice_session_id,
            thread_id=self.context.thread_id,
        )))

        def observe_stop(event: object) -> None:
            connection_observer(event)
            if isinstance(event, OutputStopObservation):
                self.stop_observations.append({"phase": event.phase, "state": event.state,
                    "reason": event.reason, "stop_command_id": event.request.stop_command_id,
                    "played_position_samples": event.played_position_samples})

        class Transport:
            # handle() owns the sole incoming socket iterator.
            async def receive(self) -> AsyncIterator[InboundFrame]:
                if False:
                    yield  # type: ignore[misc]

            async def close(self) -> None:
                await socket.close()

            async def send(self, frame: OutboundFrame) -> None:
                await socket.send(frame.model_dump_json())
                fixture.sent.append(frame.model_dump())

        self.bridge = RealtimeWebSocketFrameBridge(context=self.context, conversation=conversation,
            transport=Transport(), recording=recorder, output_epoch="fixture-renderer-output",
            precise_output_stop=True, diagnostic_observer=observe_stop, output_stop_timeout_ms=500)
        try:
            hello = json.loads(await socket.recv())
            if hello.get("type") != "session_hello":
                raise RuntimeError("fixture session hello required")
            await socket.send(json.dumps({"type": "session_ack", "session_id": self.context.voice_session_id,
                "resumed": False, "protocol_version": 2, "resume_token": "fixture",
                "output_epoch": self.bridge.output_epoch}))
            await socket.send(json.dumps({"type": "session_capabilities", "server_asr": False,
                "server_tts": True, "assistant_text_streaming": True, "user_transcript_streaming": False}))
            self.ready = True
            async for raw in socket:
                value = json.loads(raw)
                if value.get("type") in {"playback_progress_v2", "output_stop_result"}:
                    self.receipts.append(value)
                    frame = parse_inbound_frame(raw)
                    if frame is None:
                        raise RuntimeError("invalid renderer receipt")
                    await self.bridge.handle_inbound(frame)
        except Exception as error:
            self.error = str(error)
            raise
        finally:
            self.ready = False
            try:
                if self.pump is not None:
                    self.pump.cancel()
                    result = (await asyncio.gather(self.pump, return_exceptions=True))[0]
                    if isinstance(result, Exception):
                        self.error = str(result)
                await self.bridge.handle_detached()
                await self.bridge.close()
            except BaseException as error:
                self.error = str(error) or type(error).__name__
                raise
            finally:
                try:
                    await conversation.close()
                    await self.runtime.telemetry.flush()
                    for observation in self.stop_observations:
                        fact = await self.runtime.speech_deliveries.get_output_stop(self.context, observation["stop_command_id"])
                        if fact is not None:
                            observation["saved_state"] = fact.state
                            observation["saved_position_samples"] = fact.played_position_samples
                    if not recorder.settled:
                        raise RuntimeError("renderer recording did not settle")
                    self.closed = True
                except BaseException as error:
                    self.error = str(error) or type(error).__name__
                    raise
                finally:
                    self.active = False
