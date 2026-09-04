"""Pure encode/decode tests for Doubao ASR's binary frame protocol — no
socket, no network. See server/speech/doubao_asr.py.
"""

import json
import struct

from server.speech.plugins.doubao_asr import (
    _AUDIO_ONLY_REQUEST,
    _ERROR_RESPONSE,
    _FLAGS_LAST_NO_SEQ,
    _FLAGS_POS_SEQ,
    _FULL_SERVER_RESPONSE,
    _build_frame,
    _parse_frame,
)


def test_build_frame_with_seq_prefixes_four_byte_sequence():
    frame = _build_frame(_AUDIO_ONLY_REQUEST, _FLAGS_POS_SEQ, b"abcd", seq=7)

    assert frame[:4] == bytes([0x11, (_AUDIO_ONLY_REQUEST << 4) | _FLAGS_POS_SEQ, 0x00, 0x00])
    assert frame[4:8] == struct.pack(">i", 7)
    assert frame[8:12] == struct.pack(">I", 4)
    assert frame[12:] == b"abcd"


def test_build_frame_without_seq_has_no_sequence_bytes():
    frame = _build_frame(_AUDIO_ONLY_REQUEST, _FLAGS_LAST_NO_SEQ, b"xyz")

    assert frame[4:8] == struct.pack(">I", 3)
    assert frame[8:] == b"xyz"


def test_parse_frame_round_trips_full_server_response_json():
    payload = json.dumps({"result": {"text": "hello"}}).encode("utf-8")
    frame = _build_frame(_FULL_SERVER_RESPONSE, 0, payload)

    assert _parse_frame(frame) == {"result": {"text": "hello"}}


def test_parse_frame_with_seq_flag_skips_sequence_bytes():
    payload = json.dumps({"ok": True}).encode("utf-8")
    frame = _build_frame(_FULL_SERVER_RESPONSE, _FLAGS_POS_SEQ, payload, seq=3)

    assert _parse_frame(frame) == {"ok": True}


def test_parse_frame_error_response_extracts_code_and_message():
    message = "bad request"
    body = (
        struct.pack(">I", 400)
        + struct.pack(">I", len(message.encode("utf-8")))
        + message.encode("utf-8")
    )
    frame = bytes([0x11, (_ERROR_RESPONSE << 4) | 0, 0x00, 0x00]) + body

    assert _parse_frame(frame) == {"error": True, "code": 400, "message": "bad request"}


def test_parse_frame_too_short_reports_error():
    assert _parse_frame(b"\x01\x02") == {"error": True, "message": "frame too short"}
