"""BellaAsrSession/BellaAsrEngine against a fake WebSocket double — no real
socket is ever opened. See server/speech/bella_asr.py.
"""

import asyncio
import json

from websockets.exceptions import ConnectionClosed

from server.speech.plugins import bella_asr
from server.speech.plugins.bella_asr import (
    DEFAULT_MODEL,
    DEFAULT_URL,
    BellaAsrEngine,
    BellaAsrSession,
)


def _event(name: str, *, task_id: str = "server-task-1", payload: dict | None = None) -> str:
    return json.dumps({"header": {"name": name, "task_id": task_id}, "payload": payload or {}})


class FakeAsrConnection:
    """Models a real websockets connection closely enough for this module's
    single continuous `_read_loop` iteration: `__aiter__` returns `self`, and
    `__anext__` pulls from one forward-only cursor over the preset frames."""

    def __init__(self, server_frames: list[str] | None = None) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._frames = iter(server_frames or [])

    async def send(self, data: bytes | str) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._frames)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        self.closed = True


class ClosingAsrConnection:
    """Connection double whose iteration immediately raises ConnectionClosed,
    modeling the socket dropping out from under a session with no TaskFailed
    control frame at all."""

    def __init__(self) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False

    async def send(self, data: bytes | str) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        raise ConnectionClosed(None, None)

    async def close(self) -> None:
        self.closed = True


class GatedAsrConnection:
    """Connection double whose frames are delivered from an asyncio.Queue on
    demand, so a test can control the exact interleaving between `_read_loop`
    observing an event and the test driving `push_audio`/`consume_transcript`."""

    def __init__(self) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    def push_frame(self, frame: str) -> None:
        self._queue.put_nowait(frame)

    async def send(self, data: bytes | str) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        return await self._queue.get()

    async def close(self) -> None:
        self.closed = True


class BlockingAsrConnection:
    """Connection double whose read loop never yields a frame on its own, so
    tests can isolate push_audio's own ConnectionClosed handling from
    _read_loop's."""

    def __init__(self) -> None:
        self.sent: list[bytes | str] = []
        self.closed = False
        self._never = asyncio.Event()

    async def send(self, data: bytes | str) -> None:
        raise ConnectionClosed(None, None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        await self._never.wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


async def test_start_session_sends_auth_headers_and_start_transcription_message(monkeypatch):
    connection = FakeAsrConnection([_event("TranscriptionStarted", task_id="server-task-1")])
    captured = {}

    async def fake_connect(url, *, additional_headers):
        captured["url"] = url
        captured["headers"] = additional_headers
        return connection

    monkeypatch.setattr(bella_asr, "connect", fake_connect)

    engine = BellaAsrEngine(api_key="key-1")
    session = await engine.start_session()

    assert captured["url"] == f"{DEFAULT_URL}?model={DEFAULT_MODEL}"
    assert captured["headers"]["Authorization"] == "Bearer key-1"
    assert captured["headers"]["format"] == "pcm"
    assert captured["headers"]["sample_rate"] == "16000"

    sent = json.loads(connection.sent[0])
    assert sent["header"]["name"] == "StartTranscription"
    assert sent["header"]["namespace"] == "SpeechTranscriber"
    assert sent["header"]["appkey"] == "voiceagent"
    assert sent["payload"]["format"] == "pcm"
    assert sent["payload"]["sample_rate"] == 16000
    assert sent["payload"]["enable_intermediate_result"] is True

    assert session._task_id == "server-task-1"

    await session.close()


async def test_push_audio_sends_raw_pcm_binary():
    connection = FakeAsrConnection()
    session = BellaAsrSession(connection, "task-1")

    await session.push_audio(b"\x01\x02\x03", sample_rate_hz=16000)

    assert connection.sent[-1] == b"\x01\x02\x03"

    await session.close()


async def test_transcription_result_changed_updates_transcript():
    frame = _event("TranscriptionResultChanged", payload={"result": "hello"})
    connection = FakeAsrConnection([frame])
    session = BellaAsrSession(connection, "task-1")

    await session._reader_task

    assert await session.peek_transcript() == "hello"
    assert await session.consume_transcript() == "hello"
    assert await session.consume_transcript() == ""

    await session.close()


async def test_sentence_end_updates_transcript():
    frame = _event("SentenceEnd", payload={"result": "hello world"})
    connection = FakeAsrConnection([frame])
    session = BellaAsrSession(connection, "task-1")

    await session._reader_task

    assert await session.peek_transcript() == "hello world"
    assert await session.consume_transcript() == "hello world"

    await session.close()


async def test_late_finalize_from_prior_turn_is_discarded_when_next_turn_audio_starts():
    """Regression test for a live multi-turn simulation finding: Bella can send a
    late SentenceEnd for turn N's utterance (fuller, punctuated) after the kernel
    has already drained turn N's transcript via consume_transcript() and moved on.
    Without a fix, that stale text sits in `_transcript` and gets handed to turn
    N+1's consume_transcript() call instead of turn N+1's own transcript.
    """
    connection = GatedAsrConnection()
    session = BellaAsrSession(connection, "task-1")

    connection.push_frame(_event("TranscriptionResultChanged", payload={"result": "今天北京"}))
    await asyncio.sleep(0)
    assert await session.consume_transcript() == "今天北京"

    connection.push_frame(_event("SentenceEnd", payload={"result": "今天北京天气怎么样？"}))
    await asyncio.sleep(0)

    await session.push_audio(b"\x03\x04", sample_rate_hz=16000)

    assert await session.consume_transcript() == ""

    await session.close()


async def test_task_failed_is_logged_and_swallowed_not_raised():
    frame = _event("TaskFailed", payload={"message": "boom"})
    connection = FakeAsrConnection([frame])
    session = BellaAsrSession(connection, "task-1")

    await session._reader_task

    assert await session.peek_transcript() == ""
    assert session.is_alive is False

    await session.close()


async def test_connection_closed_during_read_loop_marks_session_dead(caplog):
    connection = ClosingAsrConnection()

    with caplog.at_level("WARNING"):
        session = BellaAsrSession(connection, "task-1")
        await session._reader_task

    assert session.is_alive is False
    assert any("Bella ASR session closed" in record.message for record in caplog.records)

    await session.close()


async def test_push_audio_after_connection_closed_marks_session_dead_without_raising():
    connection = BlockingAsrConnection()
    session = BellaAsrSession(connection, "task-1")

    await session.push_audio(b"\x01\x02", sample_rate_hz=16000)

    assert session.is_alive is False

    await session.close()


async def test_close_sends_stop_transcription_and_closes_connection():
    connection = FakeAsrConnection()
    session = BellaAsrSession(connection, "task-1")

    await session.close()

    last_sent = json.loads(connection.sent[-1])
    assert last_sent["header"]["name"] == "StopTranscription"
    assert last_sent["header"]["task_id"] == "task-1"
    assert connection.closed is True
