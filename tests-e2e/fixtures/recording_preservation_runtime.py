"""Opt-in isolated real HTTP/Runtime/WAV fixture; never a running user service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.application.runtime import (
    ApplicationRuntimeConfig,
    build_application_runtime,
)
from server.control_plane.http import start
from server.core.interaction_context import InteractionContext
from server.endpoint_session.registry import EndpointSessionRegistry
from server.observability.telemetry import TelemetryIdentity
from server.persistence.postgres import apply_migrations
from server.realtime import (
    AppendSpeechText,
    CommitSpeech,
    InMemoryRealtimeConversation,
    StartSpeech,
)
from server.realtime.observability import RealtimeTelemetryObserver
from server.realtime.protocol import AudioEncoding, AudioFrame
from server.realtime.protocol.events import SpeechAudioDelta
from server.realtime.transport import RealtimeWebSocketFrameBridge
from server.transport.frames import InboundFrame, OutboundFrame
from server.voice_session.protocol import PlaybackProgressV2

COOKIE = "recording-test-only-cookie-token-0000000000000"
SESSION = "recording-browser-session"


class FixtureTransport:
    """Controlled wire sink; no claim of physical device or browser renderer playback."""

    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []

    async def receive(self) -> AsyncIterator[InboundFrame]:
        if False:
            yield  # type: ignore[misc]

    async def send(self, frame: OutboundFrame) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        pass


async def seed_sent_receipt(runtime, ctx: InteractionContext) -> None:
    """Exercise real Bridge admission/normalization and canonical receipt/observer path."""
    recorder = runtime.open_recording(ctx)
    if recorder is None:
        raise RuntimeError("fixture recorder unavailable")
    conversation = InMemoryRealtimeConversation(context=ctx)
    events = conversation.events()
    transport = FixtureTransport()
    observer = RealtimeTelemetryObserver(
        runtime.telemetry.bind(
            TelemetryIdentity(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                device_id=ctx.device_id,
                voice_session_id=ctx.voice_session_id,
                thread_id=ctx.thread_id,
            )
        )
    )
    bridge = RealtimeWebSocketFrameBridge(
        context=ctx,
        conversation=conversation,
        transport=transport,
        recording=recorder,
        output_epoch="fixture-output",
    )
    try:
        for command in (
            StartSpeech(
                command_id="start", idempotency_key="start", context=ctx, speech_id="fixture-speech"
            ),
            AppendSpeechText(
                command_id="text",
                idempotency_key="text",
                context=ctx,
                speech_id="fixture-speech",
                text_sequence=1,
                delta="测试录音",
            ),
            CommitSpeech(
                command_id="commit",
                idempotency_key="commit",
                context=ctx,
                speech_id="fixture-speech",
            ),
        ):
            await conversation.send(command)
            event = await anext(events)
            observer.observe_event(event)
            await bridge.handle_event(event)
        await bridge.handle_event(
            SpeechAudioDelta(
                event_id="fixture-audio",
                context=ctx,
                conversation_sequence=4,
                occurred_at=datetime.now(UTC),
                speech_id="fixture-speech",
                segment_index=0,
                frame=AudioFrame(
                    "provider-stream",
                    0,
                    0,
                    100_000,
                    AudioEncoding.PCM_S16LE,
                    16000,
                    1,
                    b"\x01\x00" * 1600,
                ),
            )
        )
        await bridge.handle_inbound(
            PlaybackProgressV2(
                output_epoch=bridge.output_epoch,
                speech_id="fixture-speech",
                generation=ctx.generation,
                phase="playing",
                played_position_samples=800,
            )
        )
        observer.observe_event(await anext(events))
    finally:
        await bridge.close()
        await conversation.close()
    if not recorder.settled or len(transport.frames) < 1:
        raise RuntimeError("fixture sent recording did not settle")


async def main() -> None:
    import asyncpg

    schema = os.environ.get("VOICEAGENT_POSTGRES_SCHEMA", "")
    if os.environ.get("RUN_RECORDING_BROWSER_INTEGRATION") != "1" or not re.fullmatch(
        r"voiceagent_recording_browser_[a-f0-9]{32}", schema
    ):
        raise RuntimeError("isolated recording browser opt-in/schema required")
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stopped.set)
    pool = await asyncpg.create_pool("postgresql:///postgres?host=/tmp", min_size=1, max_size=2)
    runtime = None
    server = None
    owns_schema = False
    websocket_server = None
    try:
        async with pool.acquire() as conn:
            # CREATE without IF NOT EXISTS is the atomic ownership claim.
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            owns_schema = True
            await apply_migrations(conn, schema=schema)
            await conn.execute(
                f"INSERT INTO \"{schema}\".web_user_sessions (token_hash,issuer,subject,expires_at) VALUES($1,$2,$3,now()+interval '1 hour')",
                hashlib.sha256(COOKIE.encode()).hexdigest(),
                "recording-fixture",
                "recording-admin",
            )
            await conn.execute(
                f'INSERT INTO "{schema}".app_admin_accounts (issuer,subject,granted_by) VALUES($1,$2,$3)',
                "recording-fixture",
                "recording-admin",
                "isolated-test",
            )
        runtime = await build_application_runtime(ApplicationRuntimeConfig(state_backend="memory"))
        ctx = InteractionContext(
            tenant_id="recording-fixture-tenant",
            user_id="original-recording-owner",
            device_id="fixture-device",
            voice_session_id=SESSION,
            thread_id=SESSION,
            turn_id="fixture-turn",
            generation=0,
        )
        recorder = runtime.open_recording(ctx)
        if recorder is None:
            raise RuntimeError("fixture recorder unavailable")
        recorder.capture(
            "input",
            AudioFrame(
                "fixture-stream",
                0,
                0,
                100_000,
                AudioEncoding.PCM_S16LE,
                16000,
                1,
                b"\x01\x00" * 1600,
            ),
            context=ctx,
            epoch="fixture-input",
        )
        if not await recorder.close():
            raise RuntimeError("fixture recording did not settle")
        renderer_port = None
        if os.environ.get("RECORDING_BROWSER_RENDERER") == "1":
            from websockets.asyncio.server import serve

            from tests.browser_recording_playback_fixture import RecordingRendererFixture

            renderer = RecordingRendererFixture(runtime, ctx)
            websocket_server = await serve(renderer.handle, "127.0.0.1", 0, process_request=renderer.http)
            renderer_port = websocket_server.sockets[0].getsockname()[1]
        else:
            await seed_sent_receipt(runtime, ctx)
        await runtime.telemetry.flush()

        async def preserve(sid: str, actor: str) -> dict:
            return await runtime.preserve_session_recordings(sid, actor_id=actor)

        server = start(
            EndpointSessionRegistry(),
            port=0,
            session_recording_page_reader=runtime.recordings.read_page,
            session_recording_audio_reader=runtime.recordings.read_audio,
            session_recording_preserver=preserve,
        )
        print(
            json.dumps(
                {
                    "control_plane_url": f"http://127.0.0.1:{server.server_address[1]}",
                    "session_id": SESSION,
                    "renderer_port": renderer_port,
                }
            ),
            flush=True,
        )
        await stopped.wait()
    finally:
        try:
            try:
                try:
                    if websocket_server is not None:
                        websocket_server.close()
                        await websocket_server.wait_closed()
                finally:
                    if server is not None:
                        try:
                            await asyncio.to_thread(server.shutdown)
                        finally:
                            server.server_close()
            finally:
                if runtime is not None:
                    await runtime.close()
        finally:
            try:
                # Runtime is Memory-only: this schema is used exclusively for test login.
                if owns_schema:
                    async with pool.acquire() as conn:
                        await conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
            finally:
                await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
