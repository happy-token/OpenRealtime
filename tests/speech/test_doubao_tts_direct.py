"""DoubaoDirectTtsEngine against a fake WebSocket double — no real socket is
ever opened. See server/speech/plugins/doubao_tts_direct.py.
"""

import asyncio
import json

import pytest
from websockets.exceptions import ConnectionClosed

from server.speech.plugins import doubao_tts_direct
from server.speech.plugins.doubao_tts import DoubaoTtsError
from server.speech.plugins.doubao_tts_direct import (
    DEFAULT_SAMPLE_RATE_HZ,
    DoubaoDirectTtsEngine,
    _build_frame,
    _decode_text_field,
    _parse_frame,
)
from server.speech.tts import TtsSessionConfig


class FakeTtsConnection:
    """Mirrors tests/speech/test_doubao_tts.py's FakeTtsConnection: a
    forward-only cursor over pre-built server frames, usable both as an
    async iterator and an async context manager."""

    def __init__(self, server_frames: list[bytes], *, fail_send_at: int | None = None) -> None:
        self.sent: list[bytes] = []
        self.received: list[bytes] = []
        self.closed = False
        self._frames = iter(server_frames)
        self._send_calls = 0
        self._fail_send_at = fail_send_at

    async def send(self, data: bytes) -> None:
        if self._send_calls == self._fail_send_at:
            self._send_calls += 1
            raise ConnectionClosed(None, None)
        self._send_calls += 1
        self.sent.append(data)

    async def recv(self) -> bytes:
        frame = next(self._frames)
        self.received.append(frame)
        return frame

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            frame = next(self._frames)
            self.received.append(frame)
            return frame
        except StopIteration:
            raise StopAsyncIteration from None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def close(self) -> None:
        self.closed = True


class FinishAwareFakeTtsConnection(FakeTtsConnection):
    """Only exposes SessionFinished after the client finishes text input."""

    async def recv(self) -> bytes:
        frame = next(self._frames)
        if _parse_frame(frame)["event"] == doubao_tts_direct._EVENT_SESSION_FINISHED:
            while doubao_tts_direct._EVENT_FINISH_SESSION not in _sent_events(self):
                await asyncio.sleep(0)
        self.received.append(frame)
        return frame


class _AbortableTransport:
    def __init__(self) -> None:
        self.aborted = False

    def abort(self) -> None:
        self.aborted = True


class SlowCloseFakeTtsConnection(FakeTtsConnection):
    def __init__(self, server_frames: list[bytes]) -> None:
        super().__init__(server_frames)
        self.transport = _AbortableTransport()
        self.close_release = asyncio.Event()

    async def close(self) -> None:
        await self.close_release.wait()
        self.closed = True


class FakeConnectAttempt:
    """Matches websockets.connect: both awaitable and an async context manager."""

    def __init__(self, connection: FakeTtsConnection) -> None:
        self._connection = connection

    def __await__(self):
        async def resolve():
            return self._connection

        return resolve().__await__()

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, *exc_info):
        return False


def _fake_connect(connection: FakeTtsConnection, captured: dict):
    def fake_connect(url, *, additional_headers):
        captured["url"] = url
        captured["headers"] = additional_headers
        captured["calls"] = captured.get("calls", 0) + 1
        return FakeConnectAttempt(connection)

    return fake_connect


def _fake_connect_sequence(connections: list[FakeTtsConnection], captured: dict):
    remaining = iter(connections)

    def fake_connect(url, *, additional_headers):
        captured["url"] = url
        captured["headers"] = additional_headers
        captured["calls"] = captured.get("calls", 0) + 1
        return FakeConnectAttempt(next(remaining))

    return fake_connect


def _server_frame(event: int, *, session_id: str | None = None, payload: bytes = b"") -> bytes:
    """Builds a server-style response frame using the same body layout as a
    client request — the byte layout after the header is identical."""
    return _build_frame(event, session_id=session_id, payload=payload)


def _sent_events(connection: FakeTtsConnection) -> list[int]:
    from server.speech.plugins.doubao_tts_direct import _parse_frame

    return [_parse_frame(frame)["event"] for frame in connection.sent]


async def test_synthesize_sends_expected_event_sequence_and_collects_audio(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-1", payload=b"\x01\x02\x03\x04"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FakeTtsConnection(frames)
    captured: dict = {}
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, captured))

    engine = DoubaoDirectTtsEngine(api_key="key-1")
    audio = await engine.synthesize("hello")
    await engine.close()

    assert captured["headers"]["X-Api-Key"] == "key-1"
    assert audio.pcm16 == b"\x01\x02\x03\x04"
    assert audio.sample_rate_hz == DEFAULT_SAMPLE_RATE_HZ
    assert _sent_events(connection) == [
        doubao_tts_direct._EVENT_START_CONNECTION,
        doubao_tts_direct._EVENT_START_SESSION,
        doubao_tts_direct._EVENT_TASK_REQUEST,
        doubao_tts_direct._EVENT_FINISH_SESSION,
        doubao_tts_direct._EVENT_FINISH_CONNECTION,
    ]


async def test_synthesize_stream_yields_one_chunk_per_response_then_a_final_empty_chunk(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-1", payload=b"\x01\x02"),
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-1", payload=b"\x03\x04"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))

    engine = DoubaoDirectTtsEngine(api_key="key-1")
    chunks = [chunk async for chunk in engine.synthesize_stream("hello")]
    await engine.close()

    assert [chunk.pcm16 for chunk in chunks] == [b"\x01\x02", b"\x03\x04", b""]
    assert [chunk.is_final for chunk in chunks] == [False, False, True]
    assert all(chunk.sample_rate_hz == DEFAULT_SAMPLE_RATE_HZ for chunk in chunks)


async def test_duplex_stream_sends_incremental_text_in_one_session_while_receiving_audio(
    monkeypatch,
):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(
            doubao_tts_direct._EVENT_TTS_RESPONSE,
            session_id="sess-1",
            payload=b"\x01\x02",
        ),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FinishAwareFakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))
    engine = DoubaoDirectTtsEngine(api_key="key-1")

    async def text_stream():
        yield "你好"
        yield "，世界"

    chunks = [chunk async for chunk in engine.synthesize_duplex(text_stream())]
    await engine.close()

    assert [chunk.pcm16 for chunk in chunks] == [b"\x01\x02", b""]
    assert _sent_events(connection) == [
        doubao_tts_direct._EVENT_START_CONNECTION,
        doubao_tts_direct._EVENT_START_SESSION,
        doubao_tts_direct._EVENT_TASK_REQUEST,
        doubao_tts_direct._EVENT_TASK_REQUEST,
        doubao_tts_direct._EVENT_FINISH_SESSION,
        doubao_tts_direct._EVENT_FINISH_CONNECTION,
    ]
    task_payloads = [
        json.loads(_parse_frame(frame)["payload"])["req_params"]["text"]
        for frame in connection.sent
        if _parse_frame(frame)["event"] == doubao_tts_direct._EVENT_TASK_REQUEST
    ]
    assert task_payloads == ["你好", "，世界"]


async def test_closing_duplex_stream_closes_text_input_and_discards_dirty_connection(
    monkeypatch,
):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(
            doubao_tts_direct._EVENT_TTS_RESPONSE,
            session_id="sess-1",
            payload=b"\x01\x02",
        ),
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))
    engine = DoubaoDirectTtsEngine(api_key="key-1")
    text_closed = asyncio.Event()

    async def text_stream():
        try:
            yield "你好"
            await asyncio.Event().wait()
        finally:
            text_closed.set()

    stream = engine.synthesize_duplex(text_stream())
    first = await anext(stream)
    await stream.aclose()

    assert first.pcm16 == b"\x01\x02"
    assert text_closed.is_set()
    assert connection.closed is True


async def test_closing_duplex_stream_aborts_a_stalled_provider_connection(
    monkeypatch,
):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1"),
        _server_frame(
            doubao_tts_direct._EVENT_TTS_RESPONSE,
            session_id="sess-1",
            payload=b"\x01\x02",
        ),
    ]
    connection = SlowCloseFakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))
    engine = DoubaoDirectTtsEngine(api_key="key-1")

    async def text_stream():
        yield "你好"
        await asyncio.Event().wait()

    stream = engine.synthesize_duplex(text_stream())
    assert (await anext(stream)).pcm16 == b"\x01\x02"

    try:
        started_at = asyncio.get_running_loop().time()
        await asyncio.wait_for(stream.aclose(), timeout=0.7)
        elapsed_s = asyncio.get_running_loop().time() - started_at
        assert connection.transport.aborted is True
        assert elapsed_s < 0.2
    finally:
        connection.close_release.set()


async def test_duplex_session_start_failure_discards_connection(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(
            doubao_tts_direct._EVENT_SESSION_FAILED,
            session_id="sess-1",
            payload=b'{"error":"boom"}',
        ),
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))
    engine = DoubaoDirectTtsEngine(api_key="key-1")

    async def text_stream():
        yield "你好"

    with pytest.raises(DoubaoTtsError):
        _ = [chunk async for chunk in engine.synthesize_duplex(text_stream())]

    assert connection.closed is True


async def test_session_config_updates_voice_and_speech_rate_payload(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))
    engine = DoubaoDirectTtsEngine(api_key="key-1")
    engine.configure(
        TtsSessionConfig(
            voice="zh_female_vv_uranus_bigtts",
            speech_rate=25,
            dialect="sichuan",
        )
    )

    await engine.synthesize("hello")
    start_session = _parse_frame(connection.sent[1])
    payload = json.loads(start_session["payload"])

    assert payload["req_params"]["speaker"] == "zh_female_vv_uranus_bigtts"
    assert payload["req_params"]["audio_params"]["speech_rate"] == 25
    assert json.loads(payload["req_params"]["additions"]) == {
        "explicit_dialect": "sichuan"
    }
    await engine.close()


def test_dialect_requires_vivi_voice() -> None:
    engine = DoubaoDirectTtsEngine(api_key="key-1")

    with pytest.raises(ValueError, match="require the Vivi voice"):
        engine.configure(
            TtsSessionConfig(
                voice="zh_male_yuanboxiaoshu_uranus_bigtts",
                dialect="sichuan",
            )
        )


async def test_close_waits_for_connection_finished(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))

    engine = DoubaoDirectTtsEngine(api_key="key-1")
    await engine.synthesize("hello")

    assert len(connection.received) == len(frames) - 1

    await engine.close()

    assert len(connection.received) == len(frames)
    assert connection.closed is True


async def test_two_syntheses_reuse_one_connection_with_distinct_sessions(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-1", payload=b"\x01\x02"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-2", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-2", payload=b"\x03\x04"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-2", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FakeTtsConnection(frames)
    captured: dict = {}
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, captured))

    engine = DoubaoDirectTtsEngine(api_key="key-1")

    first = await engine.synthesize("first")
    second = await engine.synthesize("second")

    assert first.pcm16 == b"\x01\x02"
    assert second.pcm16 == b"\x03\x04"
    assert captured["calls"] == 1
    assert _sent_events(connection) == [
        doubao_tts_direct._EVENT_START_CONNECTION,
        doubao_tts_direct._EVENT_START_SESSION,
        doubao_tts_direct._EVENT_TASK_REQUEST,
        doubao_tts_direct._EVENT_FINISH_SESSION,
        doubao_tts_direct._EVENT_START_SESSION,
        doubao_tts_direct._EVENT_TASK_REQUEST,
        doubao_tts_direct._EVENT_FINISH_SESSION,
    ]

    await engine.close()

    assert _sent_events(connection)[-1] == doubao_tts_direct._EVENT_FINISH_CONNECTION


async def test_warmup_opens_connection_and_first_synthesis_reuses_it(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-1", payload=b"\x01\x02"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FakeTtsConnection(frames)
    captured: dict = {}
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, captured))
    engine = DoubaoDirectTtsEngine(api_key="key-1")

    await engine.warmup()
    audio = await engine.synthesize("hello")

    assert audio.pcm16 == b"\x01\x02"
    assert captured["calls"] == 1
    await engine.close()


async def test_stale_reused_connection_reconnects_once_before_audio_starts(monkeypatch):
    first_connection = FakeTtsConnection(
        [
            _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
            _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
            _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-1", payload=b"\x01\x02"),
            _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        ],
        fail_send_at=4,
    )
    second_connection = FakeTtsConnection(
        [
            _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-2"),
            _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-2", payload=b"{}"),
            _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-2", payload=b"\x03\x04"),
            _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-2", payload=b"{}"),
            _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
        ]
    )
    captured: dict = {}
    monkeypatch.setattr(
        doubao_tts_direct,
        "connect",
        _fake_connect_sequence([first_connection, second_connection], captured),
    )
    engine = DoubaoDirectTtsEngine(api_key="key-1")

    first = await engine.synthesize("first")
    second = await engine.synthesize("second")

    assert first.pcm16 == b"\x01\x02"
    assert second.pcm16 == b"\x03\x04"
    assert captured["calls"] == 2
    assert first_connection.closed is True

    await engine.close()


async def test_close_is_best_effort_when_vendor_already_dropped_connection(monkeypatch):
    connection = FakeTtsConnection(
        [
            _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
            _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
            _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        ],
        fail_send_at=4,
    )
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))
    engine = DoubaoDirectTtsEngine(api_key="key-1")
    await engine.synthesize("hello")

    await engine.close()

    assert connection.closed is True


async def test_synthesize_raises_on_connection_failed(monkeypatch):
    frames = [
        _server_frame(
            doubao_tts_direct._EVENT_CONNECTION_FAILED, session_id="conn-1", payload=b'{"error":"boom"}'
        )
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))

    engine = DoubaoDirectTtsEngine(api_key="key-1")

    with pytest.raises(DoubaoTtsError):
        await engine.synthesize("hello")


async def test_synthesize_raises_on_session_failed(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(
            doubao_tts_direct._EVENT_SESSION_FAILED, session_id="sess-1", payload=b'{"error":"boom"}'
        ),
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))

    engine = DoubaoDirectTtsEngine(api_key="key-1")

    with pytest.raises(DoubaoTtsError):
        await engine.synthesize("hello")


async def test_synthesize_stream_raises_on_session_failed_mid_stream(monkeypatch):
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="sess-1", payload=b"\x01\x02"),
        _server_frame(
            doubao_tts_direct._EVENT_SESSION_FAILED, session_id="sess-1", payload=b'{"error":"boom"}'
        ),
    ]
    connection = FakeTtsConnection(frames)
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, {}))

    engine = DoubaoDirectTtsEngine(api_key="key-1")
    stream = engine.synthesize_stream("hello")

    first = await stream.__anext__()
    assert first.pcm16 == b"\x01\x02"
    with pytest.raises(DoubaoTtsError):
        await stream.__anext__()


async def test_reads_credentials_from_env_when_not_passed(monkeypatch):
    monkeypatch.setenv("DOUBAO_API_KEY", "env-key")
    monkeypatch.setenv("DOUBAO_TTS_WS_URL", "wss://env.example/tts")
    monkeypatch.setenv("DOUBAO_RESOURCE_ID", "env-resource")
    frames = [
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_STARTED, session_id="conn-1"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="sess-1", payload=b"{}"),
        _server_frame(doubao_tts_direct._EVENT_CONNECTION_FINISHED, payload=b"{}"),
    ]
    connection = FakeTtsConnection(frames)
    captured: dict = {}
    monkeypatch.setattr(doubao_tts_direct, "connect", _fake_connect(connection, captured))

    engine = DoubaoDirectTtsEngine()
    await engine.synthesize("hello")
    await engine.close()

    assert captured["url"] == "wss://env.example/tts"
    assert captured["headers"]["X-Api-Key"] == "env-key"
    assert captured["headers"]["X-Api-Resource-Id"] == "env-resource"

@pytest.mark.asyncio
async def test_sentence_end_without_words_yields_no_alignment_chunk():
    # Confirmed against a real seed-tts-2.0 session: TTSSentenceEnd always
    # arrives with an empty `words` list; real timing arrives later on a
    # separate TTSSubtitle event. _alignment_chunks must not guess a
    # whole-sentence chunk here — that decision belongs to
    # ResponseCompleted (server/realtime/transport/websocket.py), which
    # only fires once the whole response is known to be done.
    engine = DoubaoDirectTtsEngine(api_key="test-key")
    connection = FakeTtsConnection([
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="s", payload=b"audio"),
        _server_frame(doubao_tts_direct._EVENT_TTS_SENTENCE_END, session_id="s", payload=json.dumps({"text": "第一句。", "words": []}).encode()),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="s"),
    ])
    chunks = [chunk async for chunk in engine._stream_audio(connection)]
    assert len(chunks) == 1
    assert chunks[0].pcm16 == b"audio"

def test_provider_word_timing_normalizes_seconds_and_rejects_invalid_values():
    chunks = list(doubao_tts_direct._alignment_chunks({"words": [
        {"word": "你", "startTime": 0.1, "endTime": 0.3},
        {"word": "好", "start_time": "0.3", "end_time": "0.5"},
        {"word": "错", "start_time": True, "end_time": 1},
        {"word": "错", "start_time": 1, "end_time": 0},
        {"word": "错", "start_time": "nan", "end_time": 2},
    ]}, 24_000))
    assert [(c.spoken_text, c.spoken_start_us, c.spoken_end_us) for c in chunks] == [
        ("你", 100_000, 300_000), ("好", 300_000, 500_000)]

def test_word_alignment_does_not_repeat_the_overlapping_sentence_text():
    chunks = list(doubao_tts_direct._alignment_chunks({
        "text": "你好", "words": [{"word": "你好", "startTime": 0, "endTime": .5}],
    }, 24_000))
    assert len(chunks) == 1
    assert chunks[0].spoken_text == "你好"
    assert chunks[0].spoken_end_us == 500_000

@pytest.mark.asyncio
async def test_subtitle_event_resolves_to_per_word_alignment():
    # ADR-0132: TTS2.0 word timing arrives on TTSSubtitle (364), not
    # TTSSentenceEnd. Must be routed the same as sentence-end alignment.
    engine = DoubaoDirectTtsEngine(api_key="test-key")
    connection = FakeTtsConnection([
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="s", payload=b"audio"),
        _server_frame(
            doubao_tts_direct._EVENT_TTS_SUBTITLE, session_id="s",
            payload=json.dumps({"text": "你好", "words": [
                {"word": "你好", "startTime": 0, "endTime": 0.5},
            ]}).encode(),
        ),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="s"),
    ])
    chunks = [chunk async for chunk in engine._stream_audio(connection)]
    assert chunks[0].pcm16 == b"audio"
    assert chunks[1].spoken_text == "你好"
    assert chunks[1].spoken_start_us == 0
    assert chunks[1].spoken_end_us == 500_000

@pytest.mark.asyncio
async def test_sentence_end_then_subtitle_never_emits_a_premature_whole_sentence_chunk():
    # Reproduces the exact ordering confirmed against a real seed-tts-2.0
    # session: TTSSentenceEnd (351, empty words) arrives before TTSSubtitle
    # (364, real per-word timing) for the same utterance. Before this fix,
    # 351 alone eagerly emitted a whole-sentence chunk that raced ahead of
    # the real per-word data arriving right after it on the client
    # (the user-observed "text and audio aren't in sync" symptom).
    engine = DoubaoDirectTtsEngine(api_key="test-key")
    connection = FakeTtsConnection([
        _server_frame(doubao_tts_direct._EVENT_TTS_RESPONSE, session_id="s", payload=b"audio"),
        _server_frame(
            doubao_tts_direct._EVENT_TTS_SENTENCE_END, session_id="s",
            payload=json.dumps({"phonemes": [], "text": "你好", "words": []}).encode(),
        ),
        _server_frame(
            doubao_tts_direct._EVENT_TTS_SUBTITLE, session_id="s",
            payload=json.dumps({"text": "你好", "words": [
                {"word": "你好", "startTime": 0, "endTime": 0.5},
            ]}).encode(),
        ),
        _server_frame(doubao_tts_direct._EVENT_SESSION_FINISHED, session_id="s"),
    ])
    chunks = [chunk async for chunk in engine._stream_audio(connection)]
    alignment_chunks = [chunk for chunk in chunks if chunk.spoken_text]
    assert len(alignment_chunks) == 1
    assert alignment_chunks[0].spoken_start_us == 0
    assert alignment_chunks[0].spoken_end_us == 500_000

def test_decode_text_field_with_valid_utf8_logs_nothing(caplog):
    with caplog.at_level("WARNING"):
        result = _decode_text_field("会话正常".encode("utf-8"), compression=0, field="session_id")

    assert result == "会话正常"
    assert not caplog.records

def test_decode_text_field_mid_codepoint_split_logs_warning_with_compression_flag(caplog):
    # The suspected mojibake mechanism (ADR-0132): a length field landing
    # mid-UTF-8-codepoint. Must surface the frame's compression bits so a
    # real occurrence can confirm whether they disagree with the request.
    truncated = "会话标识符".encode("utf-8")[:-1]

    with caplog.at_level("WARNING"):
        result = _decode_text_field(truncated, compression=1, field="session_id")

    assert "�" in result
    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "session_id" in message
    assert "compression=1" in message

def test_alignment_chunks_yields_nothing_when_words_missing():
    # The whole-sentence fallback belongs to ResponseCompleted one layer
    # up (ADR-0132) — this function must stay silent, not guess, so it
    # can never race ahead of a later event that does carry real timing.
    chunks = list(doubao_tts_direct._alignment_chunks({"text": "没有时间戳的句子。"}, 24_000))
    assert chunks == []
