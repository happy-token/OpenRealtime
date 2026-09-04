"""DoubaoTtsEngine against a fake WebSocket double — no real socket is ever
opened. See server/speech/doubao_tts.py.
"""

import base64
import json

import pytest

from server.speech.plugins import doubao_tts
from server.speech.plugins.doubao_tts import (
    DEFAULT_SAMPLE_RATE_HZ,
    DoubaoTtsEngine,
    DoubaoTtsError,
)


class FakeTtsConnection:
    """Models a real websockets connection closely enough for `synthesize`'s
    two-phase consumption (`_wait_for` then `_collect_audio` both iterate the
    same connection): `__aiter__` returns `self`, and `__anext__` pulls from
    one forward-only cursor, so the second `async for` continues where the
    first left off rather than restarting. Also usable as an async context
    manager, matching `async with connect(...) as connection:`."""

    def __init__(self, server_messages: list[str | bytes]) -> None:
        self.sent: list[str] = []
        self._messages = iter(server_messages)

    async def send(self, data: str) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration from None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _fake_connect(connection: FakeTtsConnection, captured: dict):
    def fake_connect(url, *, additional_headers):
        captured["url"] = url
        captured["headers"] = additional_headers
        return connection

    return fake_connect


async def test_synthesize_sends_expected_event_sequence_and_collects_audio(monkeypatch):
    audio_chunk = base64.b64encode(b"\x01\x02\x03\x04").decode("ascii")
    messages = [
        json.dumps({"header": {"name": "SpeechStarted"}, "payload": {}}),
        json.dumps({"header": {"name": "SpeechAudioDelta"}, "payload": {"audio": audio_chunk}}),
        json.dumps({"header": {"name": "SpeechCompleted"}, "payload": {}}),
    ]
    connection = FakeTtsConnection(messages)
    captured: dict = {}
    monkeypatch.setattr(doubao_tts, "connect", _fake_connect(connection, captured))

    engine = DoubaoTtsEngine(api_key="key-1")
    audio = await engine.synthesize("hello")

    assert captured["headers"]["Authorization"] == "Bearer key-1"
    assert audio.pcm16 == b"\x01\x02\x03\x04"
    assert audio.sample_rate_hz == DEFAULT_SAMPLE_RATE_HZ

    sent_names = [json.loads(s)["header"]["name"] for s in connection.sent]
    assert sent_names == ["StartSpeech", "InputText", "FinishSpeech"]


async def test_synthesize_raises_on_speech_failed(monkeypatch):
    messages = [
        json.dumps({"header": {"name": "SpeechStarted"}, "payload": {}}),
        json.dumps({"header": {"name": "SpeechFailed"}, "payload": {"reason": "boom"}}),
    ]
    connection = FakeTtsConnection(messages)
    monkeypatch.setattr(doubao_tts, "connect", _fake_connect(connection, {}))

    engine = DoubaoTtsEngine(api_key="key-1")

    with pytest.raises(DoubaoTtsError):
        await engine.synthesize("hello")


async def test_synthesize_accumulates_raw_binary_audio_frames(monkeypatch):
    messages = [
        json.dumps({"header": {"name": "SpeechStarted"}, "payload": {}}),
        b"\x0a\x0b",
        b"\x0c\x0d",
        json.dumps({"header": {"name": "SpeechCompleted"}, "payload": {}}),
    ]
    connection = FakeTtsConnection(messages)
    monkeypatch.setattr(doubao_tts, "connect", _fake_connect(connection, {}))

    engine = DoubaoTtsEngine(api_key="key-1")
    audio = await engine.synthesize("hello")

    assert audio.pcm16 == b"\x0a\x0b\x0c\x0d"


async def test_synthesize_stream_yields_one_chunk_per_delta_then_a_final_empty_chunk(monkeypatch):
    chunk_1 = base64.b64encode(b"\x01\x02").decode("ascii")
    chunk_2 = base64.b64encode(b"\x03\x04").decode("ascii")
    messages = [
        json.dumps({"header": {"name": "SpeechStarted"}, "payload": {}}),
        json.dumps({"header": {"name": "SpeechAudioDelta"}, "payload": {"audio": chunk_1}}),
        json.dumps({"header": {"name": "SpeechAudioDelta"}, "payload": {"audio": chunk_2}}),
        json.dumps({"header": {"name": "SpeechCompleted"}, "payload": {}}),
    ]
    connection = FakeTtsConnection(messages)
    monkeypatch.setattr(doubao_tts, "connect", _fake_connect(connection, {}))

    engine = DoubaoTtsEngine(api_key="key-1")
    chunks = [chunk async for chunk in engine.synthesize_stream("hello")]

    assert [chunk.pcm16 for chunk in chunks] == [b"\x01\x02", b"\x03\x04", b""]
    assert [chunk.is_final for chunk in chunks] == [False, False, True]
    assert all(chunk.sample_rate_hz == DEFAULT_SAMPLE_RATE_HZ for chunk in chunks)


async def test_synthesize_stream_raises_on_speech_failed_mid_stream(monkeypatch):
    audio_chunk = base64.b64encode(b"\x01\x02").decode("ascii")
    messages = [
        json.dumps({"header": {"name": "SpeechStarted"}, "payload": {}}),
        json.dumps({"header": {"name": "SpeechAudioDelta"}, "payload": {"audio": audio_chunk}}),
        json.dumps({"header": {"name": "SpeechFailed"}, "payload": {"reason": "boom"}}),
    ]
    connection = FakeTtsConnection(messages)
    monkeypatch.setattr(doubao_tts, "connect", _fake_connect(connection, {}))

    engine = DoubaoTtsEngine(api_key="key-1")
    stream = engine.synthesize_stream("hello")

    first = await stream.__anext__()
    assert first.pcm16 == b"\x01\x02"
    with pytest.raises(DoubaoTtsError):
        await stream.__anext__()
