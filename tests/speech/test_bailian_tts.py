"""Bailian duplex TTS adapter tests with a deterministic WebSocket double."""

from __future__ import annotations

import asyncio
import json

import pytest

from server.speech.plugins import bailian_tts
from server.speech.plugins.bailian_tts import (
    DEFAULT_MODEL,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_VOICE,
    BailianTtsEngine,
    BailianTtsError,
    _resolve_ws_url,
)


def _event(name: str, task_id: str = "task-1", **header_fields: str) -> str:
    return json.dumps(
        {
            "header": {"task_id": task_id, "event": name, **header_fields},
            "payload": {},
        }
    )


class FakeTtsConnection:
    def __init__(self, server_messages: list[str | bytes]) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._messages = iter(server_messages)

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        return next(self._messages)

    async def close(self) -> None:
        self.closed = True


class FinishAwareFakeTtsConnection(FakeTtsConnection):
    async def recv(self) -> str | bytes:
        message = next(self._messages)
        if isinstance(message, str) and json.loads(message)["header"]["event"] == "task-finished":
            while "finish-task" not in _sent_actions(self):
                await asyncio.sleep(0)
        return message


class FakeConnectAttempt:
    def __init__(self, connection: FakeTtsConnection) -> None:
        self._connection = connection

    def __await__(self):
        async def resolve():
            return self._connection

        return resolve().__await__()


class _AbortableTransport:
    def __init__(self) -> None:
        self.aborted = False

    def abort(self) -> None:
        self.aborted = True


class SlowCloseFakeTtsConnection(FakeTtsConnection):
    def __init__(self) -> None:
        super().__init__([])
        self.transport = _AbortableTransport()
        self.close_release = asyncio.Event()

    async def close(self) -> None:
        await self.close_release.wait()
        self.closed = True


def _fake_connect(connection: FakeTtsConnection, captured: dict):
    def connect(url: str, *, additional_headers: dict[str, str]):
        captured["url"] = url
        captured["headers"] = additional_headers
        captured["calls"] = captured.get("calls", 0) + 1
        return FakeConnectAttempt(connection)

    return connect


def _sent_messages(connection: FakeTtsConnection) -> list[dict]:
    return [json.loads(message) for message in connection.sent]


def _sent_actions(connection: FakeTtsConnection) -> list[str]:
    return [message["header"]["action"] for message in _sent_messages(connection)]


def test_resolve_ws_url_accepts_workspace_host_and_full_url() -> None:
    host = "llm-example.cn-beijing.maas.aliyuncs.com"

    assert _resolve_ws_url(host) == f"wss://{host}/api-ws/v1/inference"
    assert _resolve_ws_url(f"https://{host}") == f"wss://{host}/api-ws/v1/inference"
    assert _resolve_ws_url(f"wss://{host}/api-ws/v1/inference") == (
        f"wss://{host}/api-ws/v1/inference"
    )


async def test_duplex_stream_sends_llm_deltas_and_yields_24khz_pcm(monkeypatch) -> None:
    connection = FinishAwareFakeTtsConnection(
        [
            _event("task-started"),
            _event("result-generated"),
            b"\x01\x02",
            b"\x03\x04",
            _event("task-finished"),
        ]
    )
    captured: dict = {}
    monkeypatch.setattr(bailian_tts, "connect", _fake_connect(connection, captured))
    monkeypatch.setattr(bailian_tts.uuid, "uuid4", lambda: "task-1")
    engine = BailianTtsEngine(
        api_key="key-1",
        api_host="llm-example.cn-beijing.maas.aliyuncs.com",
        workspace_id="llm-example",
    )

    async def text_stream():
        yield "你好"
        yield "，世界。"

    chunks = [chunk async for chunk in engine.synthesize_duplex(text_stream())]

    assert captured["url"] == ("wss://llm-example.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference")
    assert captured["headers"]["Authorization"] == "Bearer key-1"
    assert captured["headers"]["X-DashScope-WorkSpace"] == "llm-example"
    assert [chunk.pcm16 for chunk in chunks] == [b"\x01\x02", b"\x03\x04", b""]
    assert [chunk.is_final for chunk in chunks] == [False, False, True]
    assert all(chunk.sample_rate_hz == DEFAULT_SAMPLE_RATE_HZ for chunk in chunks)

    messages = _sent_messages(connection)
    assert [message["header"]["action"] for message in messages] == [
        "run-task",
        "continue-task",
        "continue-task",
        "finish-task",
    ]
    assert [
        message["payload"]["input"]["text"]
        for message in messages
        if message["header"]["action"] == "continue-task"
    ] == ["你好", "，世界。"]
    run_task = messages[0]
    assert run_task["payload"]["model"] == DEFAULT_MODEL
    assert run_task["payload"]["parameters"] == {
        "text_type": "PlainText",
        "voice": DEFAULT_VOICE,
        "format": "pcm",
        "sample_rate": 24000,
        "volume": 50,
        "rate": 1.0,
        "pitch": 1.0,
        "enable_ssml": False,
    }


async def test_successive_synthesis_tasks_reuse_one_websocket(monkeypatch) -> None:
    connection = FakeTtsConnection(
        [
            _event("task-started", "task-1"),
            b"one",
            _event("task-finished", "task-1"),
            _event("task-started", "task-2"),
            b"two",
            _event("task-finished", "task-2"),
        ]
    )
    captured: dict = {}
    monkeypatch.setattr(bailian_tts, "connect", _fake_connect(connection, captured))
    task_ids = iter(("task-1", "task-2"))
    monkeypatch.setattr(bailian_tts.uuid, "uuid4", lambda: next(task_ids))
    engine = BailianTtsEngine(api_key="key-1", api_host="llm-example.example")

    first = await engine.synthesize("第一句。")
    second = await engine.synthesize("第二句。")
    await engine.close()

    assert first.pcm16 == b"one"
    assert second.pcm16 == b"two"
    assert captured["calls"] == 1
    assert connection.closed is True


async def test_task_failure_raises_sanitized_provider_error_and_discards_connection(
    monkeypatch,
) -> None:
    connection = FakeTtsConnection(
        [
            _event(
                "task-failed",
                error_code="InvalidParameter",
                error_message="voice is not available",
            )
        ]
    )
    monkeypatch.setattr(bailian_tts, "connect", _fake_connect(connection, {}))
    monkeypatch.setattr(bailian_tts.uuid, "uuid4", lambda: "task-1")
    engine = BailianTtsEngine(api_key="key-1", api_host="llm-example.example")

    with pytest.raises(BailianTtsError, match="InvalidParameter.*voice is not available"):
        await engine.synthesize("你好。")

    assert connection.closed is True


async def test_duplex_cancellation_sends_cancel_directive_and_discards_connection(
    monkeypatch,
) -> None:
    release = asyncio.Event()

    class BlockingConnection(FakeTtsConnection):
        async def recv(self) -> str | bytes:
            if not self.sent:
                raise AssertionError("run-task must be sent first")
            if "task-started" not in getattr(self, "returned", set()):
                self.returned = {"task-started"}
                return _event("task-started")
            await release.wait()
            return _event("task-finished")

    connection = BlockingConnection([])
    monkeypatch.setattr(bailian_tts, "connect", _fake_connect(connection, {}))
    monkeypatch.setattr(bailian_tts.uuid, "uuid4", lambda: "task-1")
    engine = BailianTtsEngine(api_key="key-1", api_host="llm-example.example")

    async def text_stream():
        yield "还没有说完"
        await asyncio.Event().wait()

    stream = engine.synthesize_duplex(text_stream())
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    finish_messages = [
        message
        for message in _sent_messages(connection)
        if message["header"]["action"] == "finish-task"
    ]
    assert finish_messages[-1]["payload"]["input"] == {"directive": "cancel"}
    assert connection.closed is True


async def test_discard_aborts_a_websocket_that_does_not_close_promptly() -> None:
    connection = SlowCloseFakeTtsConnection()
    engine = BailianTtsEngine(api_key="key-1", api_host="llm-example.example")
    engine._connection = connection

    await asyncio.wait_for(engine._discard_connection(connection), timeout=0.5)

    assert connection.transport.aborted is True
    assert engine._connection is None
