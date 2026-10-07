"""Opt-in isolated real HTTP/Runtime/WAV fixture; never a running user service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.application.runtime import (
    ApplicationRuntimeConfig,
    build_application_runtime,
)
from server.control_plane.http import start
from server.core.interaction_context import InteractionContext
from server.endpoint_session.registry import EndpointSessionRegistry
from server.persistence.postgres import apply_migrations
from server.realtime.protocol import AudioEncoding, AudioFrame

COOKIE = "recording-test-only-cookie-token-0000000000000"
SESSION = "recording-browser-session"


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
                }
            ),
            flush=True,
        )
        await stopped.wait()
    finally:
        try:
            try:
                if server is not None:
                    await asyncio.to_thread(server.shutdown)
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
