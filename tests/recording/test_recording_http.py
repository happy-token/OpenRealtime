from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.error
import urllib.request

import pytest

from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.control_plane.http import start
from server.endpoint_session.registry import EndpointSessionRegistry
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_recording_query import recorded


def request(url, headers=None):
    try:
        response = urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}))
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


@pytest.mark.asyncio
async def test_actual_runtime_recordings_http_returns_scoped_catalog_and_verified_wav():
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
        for headers in [{"Host": "attacker.example"}, {"Origin": "https://attacker.example"}, {"Origin": "null"}]:
            assert (await asyncio.to_thread(request, base, headers))[0] == 403
            assert (await asyncio.to_thread(request, f"{base}/{artifact}/audio", headers))[0] == 403
        assert (await asyncio.to_thread(request, base, {"Origin": "http://localhost:3010"}))[0] == 200
        foreign = base.replace(context().voice_session_id, "foreign")
        assert (await asyncio.to_thread(request, f"{foreign}/{artifact}/audio"))[0] == 404
        assert (await asyncio.to_thread(request, f"{base}/%2e%2e/audio"))[0] == 400
    finally:
        if server:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
        await runtime.close()
