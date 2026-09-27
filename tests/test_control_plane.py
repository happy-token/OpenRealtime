import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator

from server.avatar_assets.http_api import AvatarAssetHttpResponse
from server.control_plane import http as control_plane_http
from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.endpoint_session.registry import EndpointSessionRegistry
from server.observability.telemetry import (
    DiagnosticsWindow,
    InMemoryTelemetryStore,
    RuntimeTelemetry,
    TelemetryIdentity,
    TelemetryKind,
    TelemetryOutcome,
)
from server.transport.frames import InboundFrame, OutboundFrame, SessionHelloFrame


class FakeTransport:
    def __init__(self, frames: list[InboundFrame]) -> None:
        self._frames = frames
        self.sent: list[OutboundFrame] = []

    async def receive(self) -> AsyncIterator[InboundFrame]:
        for frame in self._frames:
            yield frame

    async def send(self, frame: OutboundFrame) -> None:
        self.sent.append(frame)

    async def close(self) -> None:
        pass


class RecordingRuntime:
    def __init__(self, session: InMemoryEndpointSession) -> None:
        self.session = session

    async def run(self) -> None:
        async for _ in self.session.receive():
            pass


class FailingDiagnostics:
    async def overview(self, window: DiagnosticsWindow):
        del window
        raise RuntimeError("database password must not be exposed")

    async def list_sessions(self, window: DiagnosticsWindow, *, limit: int = 50):
        del window, limit
        raise RuntimeError("unavailable")

    async def session_detail(self, voice_session_id: str):
        del voice_session_id
        raise RuntimeError("unavailable")


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _get_bytes(url: str) -> tuple[int, bytes, str]:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status, response.read(), response.headers["Content-Type"]
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers["Content-Type"]


def _get_with_headers(url: str, headers: dict[str, str]) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _post(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _post_bytes(url: str, body: bytes, content_type: str) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        method="POST",
        data=body,
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, response.read(), response.headers["Content-Type"]
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers["Content-Type"]


def _post_provider_probe(url: str, body: bytes, timestamp: str, signature: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="POST", data=body, headers={
        "Content-Type": "application/json",
        "X-Provider-Probe-Timestamp": timestamp,
        "X-Provider-Probe-Signature": signature,
    })
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _delete(url: str, payload: object) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        method="DELETE",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


async def test_healthz_reports_ok() -> None:
    registry = EndpointSessionRegistry()
    server = control_plane_http.start(registry, port=0)
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(_get, f"http://127.0.0.1:{port}/healthz")
        assert status == 200
        assert body == {"status": "ok"}
    finally:
        server.shutdown()


async def test_avatar_asset_endpoint_forwards_exact_loopback_request() -> None:
    calls: list[tuple[str, str, str, dict[str, str], bytes]] = []

    async def handle(
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        body: bytes,
    ) -> AvatarAssetHttpResponse:
        calls.append((method, path, query, headers, body))
        return AvatarAssetHttpResponse(201, b'{"candidate_id":"candidate-1"}')

    registry = EndpointSessionRegistry()
    server = control_plane_http.start(
        registry,
        avatar_asset_handler=handle,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body, content_type = await asyncio.to_thread(
            _post_bytes,
            f"http://127.0.0.1:{port}/avatar-assets/candidates/upload?source_id=upload-1",
            b"video-bytes",
            "video/mp4",
        )
        assert status == 201
        assert body == b'{"candidate_id":"candidate-1"}'
        assert content_type == "application/json; charset=utf-8"
        assert calls == [
            (
                "POST",
                "/avatar-assets/candidates/upload",
                "source_id=upload-1",
                calls[0][3],
                b"video-bytes",
            )
        ]
        assert calls[0][3]["content-type"] == "video/mp4"
    finally:
        server.shutdown()


async def test_avatar_asset_endpoint_rejects_non_loopback_host() -> None:
    calls = 0

    async def handle(*args, **kwargs) -> AvatarAssetHttpResponse:
        nonlocal calls
        del args, kwargs
        calls += 1
        return AvatarAssetHttpResponse.json(200, {"ok": True})

    server = control_plane_http.start(
        EndpointSessionRegistry(),
        avatar_asset_handler=handle,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _get_with_headers,
            f"http://127.0.0.1:{port}/avatar-assets/actions",
            {"Host": "attacker.example:8766"},
        )
        assert status == 403
        assert body == {"error": "avatar asset request is not from loopback"}
        assert calls == 0
    finally:
        server.shutdown()


async def test_avatar_asset_endpoint_rejects_non_loopback_origin() -> None:
    calls = 0

    async def handle(*args, **kwargs) -> AvatarAssetHttpResponse:
        nonlocal calls
        del args, kwargs
        calls += 1
        return AvatarAssetHttpResponse.json(200, {"ok": True})

    server = control_plane_http.start(
        EndpointSessionRegistry(),
        avatar_asset_handler=handle,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _get_with_headers,
            f"http://127.0.0.1:{port}/avatar-assets/actions",
            {"Origin": "https://attacker.example"},
        )
        assert status == 403
        assert body == {"error": "avatar asset request is not from loopback"}
        assert calls == 0
    finally:
        server.shutdown()


async def test_avatar_asset_timeout_cancels_the_in_flight_coroutine(monkeypatch) -> None:
    blocker = asyncio.Event()
    cancelled = asyncio.Event()

    async def handle(*args, **kwargs) -> AvatarAssetHttpResponse:
        del args, kwargs
        try:
            await blocker.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return AvatarAssetHttpResponse.json(200, {"ok": True})

    monkeypatch.setattr(control_plane_http, "_AVATAR_ASSET_TIMEOUT_S", 0.01)
    server = control_plane_http.start(
        EndpointSessionRegistry(),
        avatar_asset_handler=handle,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _get,
            f"http://127.0.0.1:{port}/avatar-assets/actions",
        )
        assert status == 504
        assert body == {"error": "control-plane request timed out"}
        await asyncio.wait_for(cancelled.wait(), timeout=0.5)
    finally:
        blocker.set()
        await asyncio.to_thread(server.shutdown)


async def test_avatar_asset_shutdown_drains_and_cancels_in_flight_requests() -> None:
    started = asyncio.Event()
    blocker = asyncio.Event()
    cancelled = asyncio.Event()

    async def handle(*args, **kwargs) -> AvatarAssetHttpResponse:
        del args, kwargs
        started.set()
        try:
            await blocker.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return AvatarAssetHttpResponse.json(200, {"ok": True})

    server = control_plane_http.start(
        EndpointSessionRegistry(),
        avatar_asset_handler=handle,
        port=0,
    )
    port = server.server_address[1]
    request = asyncio.create_task(
        asyncio.to_thread(
            _get,
            f"http://127.0.0.1:{port}/avatar-assets/actions",
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=0.5)
        server.stop_accepting_avatar_requests()
        await asyncio.to_thread(server.shutdown)
        remaining = await server.drain_avatar_requests(deadline_s=0.01)
        assert remaining == 0
        await asyncio.wait_for(cancelled.wait(), timeout=0.5)
        await asyncio.wait_for(request, timeout=0.5)
    finally:
        blocker.set()
        if not request.done():
            await request
        server.server_close()


async def test_voice_preview_endpoint_returns_generated_audio() -> None:
    calls: list[tuple[str, str, int, str]] = []

    async def preview(provider: str, voice: str, speech_rate: int, dialect: str) -> tuple[bytes, str]:
        calls.append((provider, voice, speech_rate, dialect))
        return b"RIFF-test", "audio/wav"

    registry = EndpointSessionRegistry()
    server = control_plane_http.start(registry, voice_previewer=preview, port=0)
    port = server.server_address[1]
    try:
        status, body, content_type = await asyncio.to_thread(
            _get_bytes,
            f"http://127.0.0.1:{port}/tts/preview?provider=bailian&voice=voice-1&speech_rate=20&dialect=sichuan",
        )
        assert status == 200
        assert body == b"RIFF-test"
        assert content_type == "audio/wav"
        assert calls == [("bailian", "voice-1", 20, "sichuan")]
    finally:
        server.shutdown()


async def test_provider_contract_probe_requires_signed_local_request(monkeypatch) -> None:
    from server.speech import provider_contract_probe

    secret = b"x" * 32
    monkeypatch.setenv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(secret).decode().rstrip("="))
    monkeypatch.setenv("DOUBAO_API_KEY", "platform-fixture-key")

    async def fake_probe(payload):
        if payload["capability"] == "asr":
            assert payload["fixtureTtsKey"] == "platform-fixture-key"
        else:
            assert payload == {"capability": "tts", "provider": "doubao", "apiKey": "private-key"}
        return {"ok": True, "message": "双流式文本与音频已验证"}

    monkeypatch.setattr(provider_contract_probe, "execute_probe", fake_probe)
    server = control_plane_http.start(EndpointSessionRegistry(), port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}/provider-contract-test"
    body = b'{"capability":"tts","provider":"doubao","apiKey":"private-key"}'
    try:
        status, _ = await asyncio.to_thread(_post_provider_probe, url, body, "0", "bad")
        assert status == 403
        timestamp = str(int(time.time()))
        message = b"provider-contract-probe-v1\x00" + timestamp.encode() + b"\x00" + body
        signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
        status, result = await asyncio.to_thread(_post_provider_probe, url, body, timestamp, signature)
        assert status == 200
        assert result == {"ok": True, "message": "双流式文本与音频已验证"}
        asr_body = b'{"capability":"asr","provider":"doubao","apiKey":"private-key","fixtureTtsKey":"untrusted"}'
        signature = hmac.new(secret, b"provider-contract-probe-v1\x00" + timestamp.encode() + b"\x00" + asr_body,
                             hashlib.sha256).hexdigest()
        status, _ = await asyncio.to_thread(_post_provider_probe, url, asr_body, timestamp, signature)
        assert status == 200
    finally:
        server.shutdown()


async def test_sessions_endpoint_lists_and_closes_a_tracked_session() -> None:
    registry = EndpointSessionRegistry(grace_period_s=5.0)
    transport = FakeTransport([SessionHelloFrame()])
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)
    session_id = sessions[0].session_id

    server = control_plane_http.start(registry, port=0)
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(_get, f"http://127.0.0.1:{port}/sessions")
        assert status == 200
        assert len(body) == 1
        assert body[0]["session_id"] == session_id
        assert body[0]["detached"] is True
        assert body[0]["has_client_hello"] is True

        status, body = await asyncio.to_thread(
            _post, f"http://127.0.0.1:{port}/sessions/{session_id}/close"
        )
        assert status == 200
        assert body == {"session_id": session_id, "closed": True}

        status, body = await asyncio.to_thread(_get, f"http://127.0.0.1:{port}/sessions")
        assert status == 200
        assert body == []
    finally:
        server.shutdown()


async def test_close_unknown_session_returns_404() -> None:
    registry = EndpointSessionRegistry()
    server = control_plane_http.start(registry, port=0)
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _post, f"http://127.0.0.1:{port}/sessions/does-not-exist/close"
        )
        assert status == 404
        assert "error" in body
    finally:
        server.shutdown()


async def test_observability_endpoints_expose_overview_sessions_and_timeline() -> None:
    registry = EndpointSessionRegistry()
    store = InMemoryTelemetryStore()
    telemetry = RuntimeTelemetry(store)
    await telemetry.start()
    session = telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-observed",
            thread_id="voice-observed",
        )
    )
    session.record(
        "tts.time_to_first_audio",
        generation=1,
        kind=TelemetryKind.SPAN,
        duration_ms=180,
        outcome=TelemetryOutcome.OK,
    )
    session.turn_terminal(1, outcome=TelemetryOutcome.OK, duration_ms=900)
    await telemetry.flush()
    server = control_plane_http.start(registry, diagnostics=store, port=0)
    port = server.server_address[1]
    try:
        status, overview = await asyncio.to_thread(
            _get,
            f"http://127.0.0.1:{port}/observability/overview?minutes=60",
        )
        assert status == 200
        assert overview["turn_count"] == 1
        assert overview["metrics"][0]["name"] == "tts.time_to_first_audio"

        status, sessions = await asyncio.to_thread(
            _get,
            f"http://127.0.0.1:{port}/observability/sessions?minutes=60",
        )
        assert status == 200
        assert sessions[0]["voice_session_id"] == "voice-observed"

        status, detail = await asyncio.to_thread(
            _get,
            f"http://127.0.0.1:{port}/observability/sessions/voice-observed",
        )
        assert status == 200
        assert [event["name"] for event in detail["events"]] == [
            "tts.time_to_first_audio",
            "turn.total",
        ]
    finally:
        server.shutdown()
    await telemetry.close()


async def test_session_conversation_endpoint_exposes_admin_replay_items() -> None:
    async def read_conversation(session_id: str) -> list[dict]:
        assert session_id == "voice-replay"
        return [{
            "item_id": "user-1",
            "role": "user",
            "text": "你好",
            "generation": 1,
            "status": "committed",
            "occurred_at": "2026-08-12T12:00:00+00:00",
        }]

    server = control_plane_http.start(
        EndpointSessionRegistry(),
        session_conversation_reader=read_conversation,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _get,
            f"http://127.0.0.1:{port}/observability/sessions/voice-replay/conversation",
        )
        assert status == 200
        assert body[0]["text"] == "你好"
        assert body[0]["generation"] == 1
    finally:
        server.shutdown()


async def test_batch_delete_observability_sessions_calls_history_retention() -> None:
    calls: list[list[str]] = []

    async def delete_history(session_ids: list[str]) -> dict:
        calls.append(session_ids)
        return {"requested": len(session_ids), "deleted_sessions": len(session_ids), "deleted_threads": 1}

    server = control_plane_http.start(
        EndpointSessionRegistry(),
        session_history_deleter=delete_history,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _delete,
            f"http://127.0.0.1:{port}/observability/sessions",
            {"session_ids": ["voice-1", "voice-2"]},
        )

        assert status == 200
        assert body == {"requested": 2, "deleted_sessions": 2, "deleted_threads": 1}
        assert calls == [["voice-1", "voice-2"]]
    finally:
        server.shutdown()


async def test_batch_delete_rejects_invalid_or_duplicate_session_ids() -> None:
    async def delete_history(session_ids: list[str]) -> dict:
        raise AssertionError(f"must not be called: {session_ids}")

    server = control_plane_http.start(
        EndpointSessionRegistry(),
        session_history_deleter=delete_history,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _delete,
            f"http://127.0.0.1:{port}/observability/sessions",
            {"session_ids": ["voice-1", "voice-1"]},
        )
        assert status == 400
        assert body == {"error": "session ids must be unique"}

        status, body = await asyncio.to_thread(
            _delete,
            f"http://127.0.0.1:{port}/observability/sessions",
            {"session_ids": ["../voice-1"]},
        )
        assert status == 400
        assert body == {"error": "invalid session id"}
    finally:
        server.shutdown()


async def test_batch_delete_rejects_active_sessions() -> None:
    registry = EndpointSessionRegistry(grace_period_s=5.0)
    transport = FakeTransport([SessionHelloFrame()])
    sessions: list[InMemoryEndpointSession] = []

    def build_runtime(session: InMemoryEndpointSession) -> RecordingRuntime:
        sessions.append(session)
        return RecordingRuntime(session)

    await registry.handle_connection(transport, build_runtime)

    async def delete_history(session_ids: list[str]) -> dict:
        raise AssertionError(f"must not delete active sessions: {session_ids}")

    server = control_plane_http.start(
        registry,
        session_history_deleter=delete_history,
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _delete,
            f"http://127.0.0.1:{port}/observability/sessions",
            {"session_ids": [sessions[0].session_id]},
        )

        assert status == 409
        assert body == {
            "error": "active sessions cannot be deleted",
            "session_ids": [sessions[0].session_id],
        }
    finally:
        server.shutdown()
        await registry.close_session(sessions[0].session_id)


async def test_observability_failure_returns_generic_json_500() -> None:
    registry = EndpointSessionRegistry()
    server = control_plane_http.start(
        registry,
        diagnostics=FailingDiagnostics(),
        port=0,
    )
    port = server.server_address[1]
    try:
        status, body = await asyncio.to_thread(
            _get,
            f"http://127.0.0.1:{port}/observability/overview",
        )

        assert status == 500
        assert body == {"error": "control-plane request failed"}
        assert "password" not in str(body)
    finally:
        server.shutdown()
