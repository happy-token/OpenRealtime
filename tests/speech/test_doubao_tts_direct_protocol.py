"""Pure encode/decode tests for Doubao direct bidirectional TTS's
event-framed binary protocol — no socket, no network. See
server/speech/plugins/doubao_tts_direct.py.
"""

import struct

from server.speech.plugins.doubao_tts_direct import (
    _EVENT_CONNECTION_STARTED,
    _EVENT_SESSION_STARTED,
    _EVENT_START_CONNECTION,
    _MSG_TYPE_AUDIO_ONLY_RESPONSE,
    _MSG_TYPE_ERROR,
    _MSG_TYPE_FULL_CLIENT_REQUEST,
    _MSG_TYPE_FULL_SERVER_RESPONSE,
    _build_frame,
    _parse_frame,
)


def test_build_frame_without_session_id_has_no_session_bytes():
    frame = _build_frame(_EVENT_START_CONNECTION, payload=b"{}")

    assert frame[:4] == bytes([0x11, (_MSG_TYPE_FULL_CLIENT_REQUEST << 4) | 0b0100, 0x10, 0x00])
    assert frame[4:8] == struct.pack(">i", _EVENT_START_CONNECTION)
    assert frame[8:12] == struct.pack(">I", 2)
    assert frame[12:] == b"{}"


def test_build_frame_with_session_id_prefixes_length_and_bytes():
    frame = _build_frame(_EVENT_SESSION_STARTED, session_id="abc", payload=b"hi")

    assert frame[4:8] == struct.pack(">i", _EVENT_SESSION_STARTED)
    assert frame[8:12] == struct.pack(">I", 3)
    assert frame[12:15] == b"abc"
    assert frame[15:19] == struct.pack(">I", 2)
    assert frame[19:] == b"hi"


def test_build_frame_omits_payload_length_when_payload_empty():
    frame = _build_frame(_EVENT_START_CONNECTION, session_id="s")

    assert frame[8:12] == struct.pack(">I", 1)
    assert frame[12:13] == b"s"
    assert len(frame) == 13


def test_parse_frame_round_trips_session_id_and_payload():
    frame = _build_frame(_EVENT_SESSION_STARTED, session_id="sess-1", payload=b"{}")
    # server responses use FULL_SERVER_RESPONSE, but byte layout after the
    # header is identical to what _build_frame produces for client requests
    frame = bytes([0x11, (_MSG_TYPE_FULL_SERVER_RESPONSE << 4) | 0b0100, 0x10, 0x00]) + frame[4:]

    parsed = _parse_frame(frame)

    assert parsed == {"event": _EVENT_SESSION_STARTED, "session_id": "sess-1", "payload": b"{}"}


def test_parse_frame_audio_only_response_carries_raw_bytes_payload():
    body = struct.pack(">i", 352) + struct.pack(">I", 4) + b"sess" + struct.pack(">I", 4) + b"\x01\x02\x03\x04"
    frame = bytes([0x11, (_MSG_TYPE_AUDIO_ONLY_RESPONSE << 4) | 0b0100, 0x10, 0x00]) + body

    parsed = _parse_frame(frame)

    assert parsed == {"event": 352, "session_id": "sess", "payload": b"\x01\x02\x03\x04"}


def test_parse_frame_with_id_field_but_no_trailing_payload_bytes():
    """Connection-scoped responses (e.g. ConnectionStarted) echo back a
    single length-prefixed id field with nothing after it — the generic
    parser reads that into the same slot as a session id and leaves payload
    empty rather than erroring."""
    body = struct.pack(">i", _EVENT_CONNECTION_STARTED) + struct.pack(">I", 2) + b"{}"
    frame = bytes([0x11, (_MSG_TYPE_FULL_SERVER_RESPONSE << 4) | 0b0100, 0x10, 0x00]) + body

    parsed = _parse_frame(frame)

    assert parsed == {"event": _EVENT_CONNECTION_STARTED, "session_id": "{}", "payload": b""}


def test_parse_frame_error_response_extracts_code_and_message():
    message = "bad request"
    body = (
        struct.pack(">i", 0)
        + struct.pack(">I", 400)
        + struct.pack(">I", len(message.encode("utf-8")))
        + message.encode("utf-8")
    )
    frame = bytes([0x11, (_MSG_TYPE_ERROR << 4) | 0b0100, 0x00, 0x00]) + body

    assert _parse_frame(frame) == {"error": True, "code": 400, "message": "bad request"}


def test_parse_frame_too_short_reports_error():
    assert _parse_frame(b"\x01\x02\x03") == {"error": True, "message": "frame too short"}
