"""DoubaoAsrSession/DoubaoAsrEngine against a fake WebSocket double — no
real socket is ever opened. See server/speech/doubao_asr.py.
"""

import asyncio
import json
import struct

from websockets.exceptions import ConnectionClosed

from server.speech.plugins import doubao_asr
from server.speech.plugins.doubao_asr import (
    _AUDIO_ONLY_REQUEST,
    _FLAGS_LAST_NO_SEQ,
    _FLAGS_POS_SEQ,
    _FULL_CLIENT_REQUEST,
    _FULL_SERVER_RESPONSE,
    DEFAULT_URL,
    RESOURCE_ID,
    DoubaoAsrEngine,
    DoubaoAsrSession,
    _build_frame,
)


class FakeAsrConnection:
    """Models a real websockets connection closely enough for this module's
    single continuous `_read_loop` iteration: `__aiter__` returns `self`, and
    `__anext__` pulls from one forward-only cursor over the preset frames."""

    def __init__(self, server_frames: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self._frames = iter(server_frames or [])

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._frames)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        self.closed = True


class GatedAsrConnection(FakeAsrConnection):
    """Lets a test deliver provider revisions on opposite sides of a consume."""

    def __init__(self) -> None:
        super().__init__()
        self._incoming: asyncio.Queue[bytes] = asyncio.Queue()

    def push_frame(self, frame: bytes) -> None:
        self._incoming.put_nowait(frame)

    async def __anext__(self) -> bytes:
        return await self._incoming.get()


class ClosingAsrConnection:
    """Connection double whose iteration immediately raises ConnectionClosed,
    modeling the socket dropping out from under a session."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        raise ConnectionClosed(None, None)

    async def close(self) -> None:
        self.closed = True


class BlockingAsrConnection:
    """Connection double whose read loop never yields a frame on its own, so
    tests can isolate push_audio's own ConnectionClosed handling from
    _read_loop's."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self._never = asyncio.Event()

    async def send(self, data: bytes) -> None:
        raise ConnectionClosed(None, None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        await self._never.wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


class ErrorThenBlockingConnection(FakeAsrConnection):
    def __init__(self, error_frame: bytes) -> None:
        super().__init__()
        self._error_frame = error_frame
        self._sent_error = False
        self._never = asyncio.Event()

    async def __anext__(self) -> bytes:
        if not self._sent_error:
            self._sent_error = True
            return self._error_frame
        await self._never.wait()
        raise StopAsyncIteration


def test_default_endpoint_is_bidirectional_bigmodel():
    assert DEFAULT_URL == "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"


async def test_start_session_has_a_bounded_websocket_handshake(monkeypatch):
    async def fake_connect(url, *, additional_headers):
        del url, additional_headers
        await asyncio.Event().wait()

    monkeypatch.setattr(doubao_asr, "connect", fake_connect)
    engine = DoubaoAsrEngine(api_key="key-1", connect_timeout_s=0.01)

    try:
        await engine.start_session()
    except TimeoutError:
        pass
    else:
        raise AssertionError("an ASR handshake must not wait forever")


async def test_start_session_uses_environment_url_override(monkeypatch):
    connection = FakeAsrConnection()
    captured = {}

    async def fake_connect(url, *, additional_headers):
        captured["url"] = url
        return connection

    monkeypatch.setattr(doubao_asr, "connect", fake_connect)
    monkeypatch.setenv("DOUBAO_ASR_WS_URL", "wss://example.invalid/custom-asr")

    session = await DoubaoAsrEngine(api_key="key-1").start_session()

    assert captured["url"] == "wss://example.invalid/custom-asr"
    await session.close()


async def test_start_session_sends_auth_headers_and_config_frame(monkeypatch):
    connection = FakeAsrConnection()
    captured = {}

    async def fake_connect(url, *, additional_headers):
        captured["url"] = url
        captured["headers"] = additional_headers
        return connection

    monkeypatch.setattr(doubao_asr, "connect", fake_connect)
    monkeypatch.delenv("DOUBAO_ASR_WS_URL", raising=False)

    engine = DoubaoAsrEngine(api_key="key-1")
    session = await engine.start_session()

    assert captured["url"] == DEFAULT_URL
    assert captured["headers"]["X-Api-Key"] == "key-1"
    assert captured["headers"]["X-Api-Resource-Id"] == RESOURCE_ID

    sent = connection.sent[0]
    assert sent[1] == (_FULL_CLIENT_REQUEST << 4) | _FLAGS_POS_SEQ
    size = struct.unpack(">I", sent[8:12])[0]
    config = json.loads(sent[12 : 12 + size].decode("utf-8"))
    assert config["audio"]["rate"] == 16000
    assert config["request"]["end_window_size"] == 256
    assert session._commit_wait_s == 0.512

    connection.sent.clear()
    local_32ms = b"\x01\x02" * 512
    await session.push_audio(local_32ms, sample_rate_hz=16000)
    await session.push_audio(local_32ms, sample_rate_hz=16000)
    await session.push_audio(local_32ms, sample_rate_hz=16000)
    assert connection.sent == []
    await session.push_audio(local_32ms, sample_rate_hz=16000)
    assert len(connection.sent) == 1

    await session.close()


async def test_start_session_accepts_end_window_environment_override(monkeypatch):
    connection = FakeAsrConnection()

    async def fake_connect(url, *, additional_headers):
        return connection

    monkeypatch.setattr(doubao_asr, "connect", fake_connect)
    monkeypatch.setenv("DOUBAO_ASR_END_WINDOW_MS", "180")

    session = await DoubaoAsrEngine(api_key="key-1").start_session()

    sent = connection.sent[0]
    size = struct.unpack(">I", sent[8:12])[0]
    config = json.loads(sent[12 : 12 + size].decode("utf-8"))
    assert config["request"]["end_window_size"] == 180
    await session.close()


async def test_push_audio_sends_incrementing_seq_binary_frames():
    connection = FakeAsrConnection()
    session = DoubaoAsrSession(connection)

    await session.push_audio(b"\x01\x02", sample_rate_hz=16000)
    await session.push_audio(b"\x03\x04", sample_rate_hz=16000)

    first_seq = struct.unpack(">i", connection.sent[0][4:8])[0]
    second_seq = struct.unpack(">i", connection.sent[1][4:8])[0]
    assert (first_seq, second_seq) == (2, 3)
    assert connection.sent[0].endswith(b"\x01\x02")
    assert connection.sent[1].endswith(b"\x03\x04")

    await session.close()


async def test_push_audio_aggregates_local_32ms_chunks_into_provider_100ms_frames():
    connection = FakeAsrConnection()
    session = DoubaoAsrSession(
        connection,
        sample_rate_hz=16000,
        packet_duration_ms=100,
    )
    chunks = [bytes([index, index]) * 512 for index in range(1, 5)]

    for chunk in chunks[:3]:
        await session.push_audio(chunk, sample_rate_hz=16000)
    assert connection.sent == []

    await session.push_audio(chunks[3], sample_rate_hz=16000)

    assert len(connection.sent) == 1
    assert connection.sent[0].endswith(b"".join(chunks)[:3200])
    await session.close()


async def test_close_flushes_a_partial_provider_audio_frame_before_last_marker():
    connection = FakeAsrConnection()
    session = DoubaoAsrSession(
        connection,
        sample_rate_hz=16000,
        packet_duration_ms=100,
    )
    final_32ms = b"\x05\x06" * 512

    await session.push_audio(final_32ms, sample_rate_hz=16000)
    await session.close()

    assert len(connection.sent) == 2
    assert connection.sent[0].endswith(final_32ms)
    assert connection.sent[1][1] == (_AUDIO_ONLY_REQUEST << 4) | _FLAGS_LAST_NO_SEQ


async def test_consume_transcript_extracts_text_from_server_response_frame():
    payload = json.dumps({"result": {"text": "hello world"}}).encode("utf-8")
    frame = _build_frame(_FULL_SERVER_RESPONSE, 0, payload)
    connection = FakeAsrConnection([frame])
    session = DoubaoAsrSession(connection)

    await session._reader_task

    assert await session.consume_transcript() == "hello world"
    assert await session.consume_transcript() == ""

    await session.close()


async def test_consume_transcript_rebases_a_cumulative_provider_result_for_the_next_turn():
    connection = GatedAsrConnection()
    session = DoubaoAsrSession(connection)
    first = "你好呀，今天天气"
    connection.push_frame(
        _build_frame(
            _FULL_SERVER_RESPONSE,
            0,
            json.dumps({"result": {"text": first}}).encode("utf-8"),
        )
    )
    await session.wait_for_update(after_revision=0, after_sentence_end_revision=0)

    assert await session.consume_transcript() == first

    connection.push_frame(
        _build_frame(
            _FULL_SERVER_RESPONSE,
            0,
            json.dumps(
                {"result": {"text": f"{first}怎么样呀？"}}
            ).encode("utf-8"),
        )
    )
    snapshot = await session.wait_for_update(
        after_revision=1,
        after_sentence_end_revision=0,
    )

    assert snapshot.text == "怎么样呀？"
    assert await session.consume_transcript() == "怎么样呀？"
    await session.close()


async def test_consume_transcript_flushes_the_partial_audio_packet_before_finalizing():
    connection = GatedAsrConnection()
    session = DoubaoAsrSession(
        connection,
        sample_rate_hz=16_000,
        packet_duration_ms=100,
        commit_wait_ms=50,
    )
    final_32ms = b"\x01\x02" * 512
    await session.push_audio(final_32ms, sample_rate_hz=16_000)
    assert connection.sent == []

    consume = asyncio.create_task(session.consume_transcript())
    while not connection.sent:
        await asyncio.sleep(0)
    connection.push_frame(
        _build_frame(
            _FULL_SERVER_RESPONSE,
            0,
            json.dumps(
                {
                    "result": {
                        "text": "北京的",
                        "utterances": [{"text": "北京的", "definite": True}],
                    }
                }
            ).encode("utf-8"),
        )
    )

    assert await asyncio.wait_for(consume, timeout=0.1) == "北京的"
    assert connection.sent[0].endswith(final_32ms)
    await session.close()


async def test_consume_transcript_waits_for_late_provider_final_without_buffered_audio():
    """A packet-aligned VAD stop must not strand the provider's tail in a new turn."""

    connection = GatedAsrConnection()
    session = DoubaoAsrSession(connection, commit_wait_ms=100)
    connection.push_frame(
        _build_frame(
            _FULL_SERVER_RESPONSE,
            0,
            json.dumps({"result": {"text": "今天天气怎么样呢"}}).encode("utf-8"),
        )
    )
    await session.wait_for_update(after_revision=0, after_sentence_end_revision=0)

    consume = asyncio.create_task(session.consume_transcript())
    await asyncio.sleep(0)
    assert not consume.done()

    connection.push_frame(
        _build_frame(
            _FULL_SERVER_RESPONSE,
            0,
            json.dumps({"result": {"text": "今天天气怎么样"}}).encode("utf-8"),
        )
    )
    await session.wait_for_update(after_revision=1, after_sentence_end_revision=0)
    assert not consume.done()

    connection.push_frame(
        _build_frame(
            _FULL_SERVER_RESPONSE,
            0,
            json.dumps(
                {
                    "result": {
                        "text": "今天天气怎么样？",
                        "utterances": [
                            {"text": "今天天气怎么样？", "definite": True}
                        ],
                    }
                }
            ).encode("utf-8"),
        )
    )

    assert await asyncio.wait_for(consume, timeout=0.1) == "今天天气怎么样？"
    await session.close()


async def test_peek_transcript_reflects_latest_text_without_clearing_it():
    payload = json.dumps({"result": {"text": "hello world"}}).encode("utf-8")
    frame = _build_frame(_FULL_SERVER_RESPONSE, 0, payload)
    connection = FakeAsrConnection([frame])
    session = DoubaoAsrSession(connection)

    await session._reader_task

    assert await session.peek_transcript() == "hello world"
    assert await session.peek_transcript() == "hello world"
    assert await session.consume_transcript() == "hello world"

    await session.close()


async def test_snapshot_exposes_increment_revision_and_sentence_end_marker():
    partial = json.dumps(
        {
            "result": {
                "text": "你",
                "utterances": [{"text": "你", "definite": False}],
            }
        }
    ).encode("utf-8")
    final = json.dumps(
        {
            "result": {
                "text": "你好。",
                "utterances": [{"text": "你好。", "definite": True}],
            }
        }
    ).encode("utf-8")
    connection = FakeAsrConnection(
        [
            _build_frame(_FULL_SERVER_RESPONSE, 0, partial),
            _build_frame(_FULL_SERVER_RESPONSE, 0, final),
        ]
    )
    session = DoubaoAsrSession(connection)

    await session._reader_task

    snapshot = await session.snapshot()
    assert snapshot.text == "你好。"
    assert snapshot.revision == 2
    assert snapshot.sentence_end_revision == 2
    assert snapshot.is_sentence_end is True

    await session.close()


async def test_multiple_single_result_segments_accumulate_without_losing_earlier_text():
    first = json.dumps(
        {"result": {"text": "你好。", "utterances": [{"text": "你好。", "definite": True}]}}
    ).encode("utf-8")
    second = json.dumps(
        {
            "result": {
                "text": "请介绍一下自己。",
                "utterances": [{"text": "请介绍一下自己。", "definite": True}],
            }
        }
    ).encode("utf-8")
    connection = FakeAsrConnection(
        [
            _build_frame(_FULL_SERVER_RESPONSE, 0, first),
            _build_frame(_FULL_SERVER_RESPONSE, 0, second),
        ]
    )
    session = DoubaoAsrSession(connection)

    await session._reader_task

    snapshot = await session.snapshot()
    assert snapshot.text == "你好。请介绍一下自己。"
    assert snapshot.revision == 2
    assert snapshot.is_sentence_end is True
    assert await session.consume_transcript() == "你好。请介绍一下自己。"
    await session.close()


async def test_wait_for_update_observes_async_sentence_end_without_more_audio_pushes():
    final = json.dumps(
        {
            "result": {
                "text": "你好。",
                "utterances": [{"text": "你好。", "definite": True}],
            }
        }
    ).encode("utf-8")
    connection = FakeAsrConnection([_build_frame(_FULL_SERVER_RESPONSE, 0, final)])
    session = DoubaoAsrSession(connection)

    snapshot = await session.wait_for_update(
        after_revision=0,
        after_sentence_end_revision=0,
    )

    assert snapshot.text == "你好。"
    assert snapshot.is_sentence_end is True

    await session.close()


async def test_close_sends_closing_frame_and_closes_connection():
    connection = FakeAsrConnection()
    session = DoubaoAsrSession(connection)

    await session.close()

    last_sent = connection.sent[-1]
    assert last_sent[1] == (_AUDIO_ONLY_REQUEST << 4) | _FLAGS_LAST_NO_SEQ
    assert connection.closed is True


async def test_connection_closed_during_read_loop_marks_session_dead(caplog):
    connection = ClosingAsrConnection()

    with caplog.at_level("WARNING"):
        session = DoubaoAsrSession(connection)
        await session._reader_task

    assert session.is_alive is False
    assert any("Doubao ASR session closed" in record.message for record in caplog.records)

    await session.close()


async def test_vendor_error_frame_ends_session_instead_of_leaving_it_reusable():
    message = b"connection ended"
    frame = (
        bytes([0x11, 0xF0, 0x00, 0x00])
        + struct.pack(">I", 20000000)
        + struct.pack(">I", len(message))
        + message
    )
    connection = ErrorThenBlockingConnection(frame)
    session = DoubaoAsrSession(connection)

    await asyncio.wait_for(session._reader_task, timeout=0.1)

    assert session.is_alive is False

    await session.close()


async def test_push_audio_after_connection_closed_marks_session_dead_without_raising():
    connection = BlockingAsrConnection()
    session = DoubaoAsrSession(connection)

    await session.push_audio(b"\x01\x02", sample_rate_hz=16000)

    assert session.is_alive is False

    await session.close()
