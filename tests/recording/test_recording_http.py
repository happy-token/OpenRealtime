from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

import pytest

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.control_plane.http import start
from server.endpoint_session.registry import EndpointSessionRegistry
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_query import recorded


def request(url, headers=None, data=None):
    try:
        response = urllib.request.urlopen(
            urllib.request.Request(url, headers=headers or {}, data=data)
        )
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


@pytest.mark.asyncio
async def test_actual_runtime_recordings_http_returns_scoped_catalog_and_verified_wav(monkeypatch):
    monkeypatch.setenv(
        "VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("="),
    )
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    server = None
    try:
        _, item = await recorded(runtime.journal, runtime.recordings.artifacts)
        artifact = item.content[0].value["artifact_id"]
        server = start(
            EndpointSessionRegistry(),
            port=0,
            session_recording_page_reader=runtime.recordings.read_page,
            session_recording_audio_reader=runtime.recordings.read_audio,
        )
        base = f"http://127.0.0.1:{server.server_address[1]}/observability/sessions/{context().voice_session_id}/recordings"
        status, _, body = await asyncio.to_thread(request, base + "?limit=1")
        assert status == 200
        row = json.loads(body)["items"][0]
        assert row["artifact_id"] == artifact and row["status"] == "available"
        status, headers, wav = await asyncio.to_thread(request, f"{base}/{artifact}/audio")
        assert status == 200 and wav[:4] == b"RIFF"
        assert headers["Content-Type"] == "audio/wav"
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Recording-Session"] == context().voice_session_id
        assert headers["X-Recording-Artifact"] == artifact
        assert headers["X-Recording-SHA256"] == hashlib.sha256(wav).hexdigest()
        for query in [
            "limit=201",
            "limit=0",
            "after_sequence=01",
            "after_sequence=9223372036854775808",
            "limit=1&limit=2",
        ]:
            assert (await asyncio.to_thread(request, base + "?" + query))[0] == 400
        proof_body = b'{"actor_id":"admin"}'
        assert (
            await asyncio.to_thread(
                request,
                base + "/preservation",
                proof(context().voice_session_id, proof_body),
                proof_body,
            )
        )[0] == 503
        for headers in [
            {"Host": "attacker.example"},
            {"Origin": "https://attacker.example"},
            {"Origin": "null"},
        ]:
            assert (await asyncio.to_thread(request, base, headers))[0] == 403
            assert (await asyncio.to_thread(request, f"{base}/{artifact}/audio", headers))[0] == 403
        assert (await asyncio.to_thread(request, base, {"Origin": "http://localhost:3010"}))[
            0
        ] == 200
        foreign = base.replace(context().voice_session_id, "foreign")
        assert (await asyncio.to_thread(request, f"{foreign}/{artifact}/audio"))[0] == 404
        assert (await asyncio.to_thread(request, f"{base}/%2e%2e/audio"))[0] == 400
    finally:
        if server:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
        await runtime.close()


def proof(session_id, body, timestamp=None):
    timestamp = str(timestamp if timestamp is not None else int(time.time()))
    key = hmac.new(
        b"k" * 32, b"openrealtime/session-recording-preservation/key/v1", hashlib.sha256
    ).digest()
    message = (
        b"session-recording-preservation-v1\x00"
        + timestamp.encode()
        + b"\x00"
        + session_id.encode()
        + b"\x00"
        + body
    )
    return {
        "X-Recording-Preservation-Timestamp": timestamp,
        "X-Recording-Preservation-Signature": hmac.new(key, message, hashlib.sha256).hexdigest(),
    }


@pytest.mark.asyncio
async def test_recording_preservation_http_requires_admin_transport_proof_and_scopes_mutation(
    monkeypatch,
):
    monkeypatch.setenv(
        "VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("="),
    )
    runtime = await build_application_runtime(ApplicationRuntimeConfig())

    async def preserve(sid, actor):
        return await runtime.preserve_session_recordings(sid, actor_id=actor)

    server = start(EndpointSessionRegistry(), port=0, session_recording_preserver=preserve)
    base = f"http://127.0.0.1:{server.server_address[1]}/observability/sessions/{context().voice_session_id}/recordings/preservation"
    body = b'{"actor_id":"admin"}'
    signed = proof(context().voice_session_id, body)
    try:
        await recorded(runtime.journal, runtime.recordings.artifacts)
        for headers in [
            {},
            {**signed, "Host": "evil.example"},
            {**signed, "Origin": "null"},
            {**signed, "Authorization": "Bearer read-grant"},
            proof("foreign", body),
            proof(context().voice_session_id, body, int(time.time()) - 61),
        ]:
            assert (await asyncio.to_thread(request, base, headers, body))[0] == 403
        assert (await asyncio.to_thread(request, base, signed, b'{"actor_id":"other"}'))[0] == 403
        assert not runtime.recordings.artifacts._preserved_sessions
        status, headers, payload = await asyncio.to_thread(request, base, signed, body)
        assert status == 200 and headers["Cache-Control"] == "no-store"
        state = json.loads(payload)
        assert state["preserved"] and state["preserved_segments"] == 1
        assert "tenant_id" not in state and "actor_id" not in state
        assert json.loads((await asyncio.to_thread(request, base, signed, body))[2]) == state
        for bad in [
            b'{"actor_id":null}',
            b'{"actor_id":false}',
            b'{"actor_id":""}',
            b'{"actor_id":"admin","unmark":true}',
            b"[]",
        ]:
            assert (
                await asyncio.to_thread(request, base, proof(context().voice_session_id, bad), bad)
            )[0] == 400
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await runtime.close()
