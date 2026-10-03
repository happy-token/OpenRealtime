"""Real Doubao (火山引擎) TTS conformer — direct Volcengine V3 bidirectional
streaming endpoint, no gateway. See CONTEXT.md: TtsEngine.

Speaks the bidirectional/duplex WebSocket protocol at
`wss://openspeech.bytedance.com/api/v3/tts/bidirection`. Earlier attempts at
this endpoint (see docs/adr/0011-doubao-asr-tts-as-swappable-speech-seam.md
and ../bench/docs/issues/tts-protocol-debug.md) only ever tried ASR-style
sequence flags and were marked "confirmed broken". The actual protocol
instead requires the `MsgTypeFlagWithEvent` framing flag plus a full
connection/session/task event lifecycle — reverse-engineered from
ByteDance's own open-source reference client (TEN-framework's
`bytedance_tts_duplex` extension) and confirmed against the real endpoint.

Frame layout: a 4-byte header (same style as doubao_asr.py's _build_frame),
then a 4-byte big-endian event code, then an optional session id (4-byte
length + utf8 bytes) and an optional payload (4-byte length + bytes).

Only the single-key auth style is supported (`X-Api-Key` /
`DOUBAO_API_KEY`) — the credential already confirmed valid against this
resource id, matching what `.env` is set up for. The legacy two-credential
(app_id/token) auth style used by doubao_asr.py is not needed here.

The credential (`DOUBAO_API_KEY`) is read from the environment and never
logged or printed.
"""

from __future__ import annotations

import asyncio
import json
import math
import logging
import os
import re
import struct
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from server.speech.plugins.doubao_tts import DoubaoTtsError
from server.speech.tts import SynthesizedAudio, SynthesizedAudioChunk, TtsSessionConfig

DEFAULT_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
DEFAULT_RESOURCE_ID = "seed-tts-2.0"
DEFAULT_VOICE = "zh_male_yuanboxiaoshu_uranus_bigtts"
DEFAULT_SAMPLE_RATE_HZ = 24000
# Cancelled/failed sessions are never reusable. Give a graceful close one
# short chance, then abort before the outer 300ms TTS cancellation budget.
_CONNECTION_CLOSE_TIMEOUT_S = 0.1
logger = logging.getLogger(__name__)
SUPPORTED_VOICES = (
    "zh_male_yuanboxiaoshu_uranus_bigtts",
    "zh_female_qingxinnvsheng_uranus_bigtts",
    "zh_female_vv_uranus_bigtts",
    "zh_female_xiaohe_uranus_bigtts",
    "zh_male_m191_uranus_bigtts",
    "zh_female_qingchezizi_uranus_bigtts",
    "zh_female_tianmeitaozi_uranus_bigtts",
    "zh_male_qingshuangnanda_uranus_bigtts",
    "zh_female_kefunvsheng_uranus_bigtts",
    "saturn_zh_female_qingyingduoduo_cs_tob",
    "saturn_zh_male_qingxinmumu_cs_tob",
    "zh_female_yingyujiaoxue_uranus_bigtts",
    "zh_female_shaoergushi_uranus_bigtts",
    "zh_female_xiaoxue_uranus_bigtts",
    "zh_male_cixingjieshuonan_uranus_bigtts",
    "zh_female_liuchangnv_uranus_bigtts",
    "zh_female_cancan_uranus_bigtts",
    "saturn_zh_female_nuanxinxuejie_tob",
    "zh_female_xueayi_saturn_bigtts",
    "zh_male_dayi_saturn_bigtts",
    "zh_female_mizai_saturn_bigtts",
    "zh_female_jitangnv_saturn_bigtts",
    "zh_female_meilinvyou_saturn_bigtts",
    "zh_female_santongyongns_saturn_bigtts",
    "zh_male_ruyayichen_saturn_bigtts",
)
SUPPORTED_DIALECTS = ("", "dongbei", "shaanxi", "sichuan")
DIALECT_VOICE = "zh_female_vv_uranus_bigtts"
_VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,128}$")

_MSG_TYPE_FULL_CLIENT_REQUEST = 0b0001
_MSG_TYPE_FULL_SERVER_RESPONSE = 0b1001
_MSG_TYPE_AUDIO_ONLY_RESPONSE = 0b1011
_MSG_TYPE_ERROR = 0b1111

_FLAGS_WITH_EVENT = 0b0100
_SERIAL_JSON = 0b0001

_EVENT_START_CONNECTION = 1
_EVENT_FINISH_CONNECTION = 2
_EVENT_CONNECTION_STARTED = 50
_EVENT_CONNECTION_FAILED = 51
_EVENT_CONNECTION_FINISHED = 52
_EVENT_START_SESSION = 100
_EVENT_FINISH_SESSION = 102
_EVENT_SESSION_STARTED = 150
_EVENT_SESSION_FINISHED = 152
_EVENT_SESSION_FAILED = 153
_EVENT_TASK_REQUEST = 200
_EVENT_TTS_SENTENCE_START = 350
_EVENT_TTS_SENTENCE_END = 351
_EVENT_TTS_RESPONSE = 352
# TTSSubtitle isn't in Volcengine's documented event table (350-352 only).
# `enable_timestamp` (sent below) only takes effect for TTS1.0/ICL1.0 per
# Volcengine's own docs; this resource id speaks TTS2.0/ICL2.0, whose word
# timing instead requires `enable_subtitle` and arrives on a TTSSubtitle
# event, non-blocking relative to audio (see ADR-0132). This literal is an
# unconfirmed guess carried over from before this was understood — treat
# every occurrence as provisional until the diagnostic logging below
# confirms it against a live session.
_EVENT_TTS_SUBTITLE = 364


def _is_valid_voice_id(voice: str) -> bool:
    """Accept provider voice IDs beyond the curated UI catalog.

    The catalog changes independently of this application. Syntax is checked
    locally; account entitlement and availability remain provider truth and
    are surfaced by synthesis/preview.
    """
    return _VOICE_ID_PATTERN.fullmatch(voice) is not None


def _build_frame(event: int, *, session_id: str | None = None, payload: bytes = b"") -> bytes:
    """Encode one Doubao bidirectional-TTS binary-protocol frame. Pure,
    unit-testable."""
    byte0 = 0x11  # protocol version 1, header size 1 (4 bytes)
    byte1 = (_MSG_TYPE_FULL_CLIENT_REQUEST << 4) | _FLAGS_WITH_EVENT
    byte2 = _SERIAL_JSON << 4  # no compression
    header = bytes([byte0, byte1, byte2, 0x00])
    body = struct.pack(">i", event)
    if session_id is not None:
        session_bytes = session_id.encode("utf-8")
        body += struct.pack(">I", len(session_bytes)) + session_bytes
    if payload:
        body += struct.pack(">I", len(payload)) + payload
    return header + body


def _decode_text_field(data: bytes, *, compression: int, field: str) -> str:
    """Decode a length-prefixed text field, logging when the bytes don't
    round-trip as UTF-8 — the suspected mojibake mechanism (ADR-reasoned,
    not yet confirmed) is a server response whose actual compression flag
    doesn't match what we requested, which would land this slice mid
    codepoint. `errors="replace"` is kept (never raise mid-session over a
    diagnostic field) but every occurrence is now logged with the frame's
    own compression flag so a real sample can confirm or rule this out."""
    decoded = data.decode("utf-8", errors="replace")
    if "�" in decoded:
        logger.warning(
            "Doubao TTS %s field failed clean UTF-8 decode (compression=%d, "
            "size=%d bytes) — see ADR-0132 for the suspected cause",
            field, compression, len(data),
        )
    return decoded


def _parse_frame(data: bytes) -> dict[str, Any]:
    """Decode one Doubao bidirectional-TTS binary-protocol response frame.
    Pure, unit-testable."""
    if len(data) < 8:
        return {"error": True, "message": "frame too short"}

    msg_type = (data[1] >> 4) & 0x0F
    compression = data[2] & 0x0F
    event = struct.unpack(">i", data[4:8])[0]
    offset = 8

    if msg_type == _MSG_TYPE_ERROR:
        code = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        message = _decode_text_field(
            data[offset : offset + size], compression=compression, field="error message"
        )
        return {"error": True, "code": code, "message": message}

    session_id: str | None = None
    if offset + 4 <= len(data):
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        session_id = _decode_text_field(
            data[offset : offset + size], compression=compression, field="session_id"
        )
        offset += size

    payload = b""
    if offset + 4 <= len(data):
        payload_size = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        payload = data[offset : offset + payload_size]

    return {"event": event, "session_id": session_id, "payload": payload}


def _decode_json_payload(payload: bytes) -> Any:
    return json.loads(payload.decode("utf-8")) if payload else {}


def _payload_keys(payload: bytes) -> list[str]:
    """Top-level JSON keys only, for diagnostics — never the text content."""
    try:
        decoded = _decode_json_payload(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ["<undecodable>"]
    return sorted(decoded.keys()) if isinstance(decoded, dict) else ["<non-object>"]


def _alignment_chunks(payload: object, sample_rate_hz: int, *, event: int | None = None):
    """Yield only real per-word provider timings; never manufacture word
    durations and never guess a whole-sentence fallback here.

    Confirmed against a real seed-tts-2.0 session (not just static
    reading): TTSSentenceEnd (351) always arrives first with an empty
    `words` list, and the real per-word data arrives later on a separate
    TTSSubtitle (364) event. A whole-sentence chunk emitted eagerly on 351
    used to race ahead of 364's real data — on the client, that whole-text
    cue satisfies its 20ms visibility threshold almost immediately and is
    always the "longest" cue, so it visually overrides the real per-word
    cues that keep arriving right after it (the user-observed "text and
    audio aren't in sync" symptom). The correct whole-utterance fallback
    for "no word timing ever arrived" already exists one layer up, keyed
    off the whole response finishing (ResponseCompleted in
    server/realtime/transport/websocket.py), which cannot fire
    prematurely. This function must not duplicate or race that decision.
    """
    if not isinstance(payload, dict):
        logger.debug("Doubao TTS alignment event=%s payload is not an object", event)
        return
    # Confirmed against a real session: this sentence-level `text` field
    # is always the exact original text, never a pronunciation rendering
    # — unlike individual words[].word, which can diverge (numbers read
    # aloud, dropped spaces between Latin words, etc). Used as the
    # reliable anchor a consumer maps real elapsed time onto, instead of
    # ever matching word text against original text character by character.
    sentence_text = payload.get("text")
    if not isinstance(sentence_text, str) or not sentence_text:
        sentence_text = None
    timed_words = False
    raw_words = payload.get("words", [])
    word_count = len(raw_words) if isinstance(raw_words, list) else None
    valid_words: list[tuple[str, float, float]] = []
    if isinstance(raw_words, list):
        for word in raw_words:
            if not isinstance(word, dict):
                continue
            text = word.get("word", word.get("text"))
            start = word.get("startTime", word.get("start_time"))
            end = word.get("endTime", word.get("end_time"))
            if not isinstance(text, str) or not text or isinstance(start, bool) or isinstance(end, bool):
                continue
            try:
                start, end = float(start), float(end)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                continue
            valid_words.append((text, start, end))
    sentence_duration_us = (
        round(max(end for _, _, end in valid_words) * 1_000_000) if valid_words else None
    )
    for text, start, end in valid_words:
        timed_words = True
        yield SynthesizedAudioChunk(
            pcm16=b"", sample_rate_hz=sample_rate_hz, is_final=False,
            spoken_text=text, spoken_start_us=round(start * 1_000_000), spoken_end_us=round(end * 1_000_000),
            sentence_text=sentence_text, sentence_duration_us=sentence_duration_us,
        )
    if timed_words:
        logger.debug(
            "Doubao TTS alignment event=%s resolved per-word timing (words=%d)",
            event, word_count,
        )
    else:
        logger.debug(
            "Doubao TTS alignment event=%s had no word timing (words=%s, keys=%s) "
            "— deferring to ResponseCompleted's whole-utterance fallback, not guessing here",
            event, word_count, sorted(payload.keys()),
        )


class DoubaoDirectTtsEngine:
    """Real conformer with one reusable connection and serial TTS sessions.

    The vendor connection is expensive to establish, while StartSession /
    FinishSession are deliberately repeatable on it. A duplex synthesis keeps
    one session open while incremental LLM text enters and provider audio exits.
    Sequential turns reuse the WebSocket until ``close`` or a connection failure.
    """

    provider_name = "doubao"

    def __init__(
        self,
        api_key: str | None = None,
        ws_url: str | None = None,
        resource_id: str | None = None,
        voice: str = DEFAULT_VOICE,
        *,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        speech_rate: int = 0,
    ) -> None:
        self._api_key = api_key or os.environ["DOUBAO_API_KEY"]
        self._ws_url = ws_url or os.environ.get("DOUBAO_TTS_WS_URL", DEFAULT_URL)
        self._resource_id = resource_id or os.environ.get("DOUBAO_RESOURCE_ID", DEFAULT_RESOURCE_ID)
        self._voice = voice
        self._speech_rate = speech_rate
        self._dialect = ""
        self._sample_rate_hz = sample_rate_hz
        self._connection: Any | None = None
        self._last_connection_setup_ms: float | None = None
        self._last_connection_reused = False
        self._last_connection_disconnects = 0
        self._session_lock = asyncio.Lock()
        self.configure(TtsSessionConfig(voice=voice, speech_rate=speech_rate))

    def configure(self, config: TtsSessionConfig) -> None:
        if not _is_valid_voice_id(config.voice):
            raise ValueError("unsupported Doubao voice")
        if not -50 <= config.speech_rate <= 100:
            raise ValueError("speech_rate must be between -50 and 100")
        if config.dialect not in SUPPORTED_DIALECTS:
            raise ValueError("unsupported Doubao dialect")
        if config.dialect and config.voice != DIALECT_VOICE:
            raise ValueError("Doubao dialects require the Vivi voice")
        self._voice = config.voice
        self._speech_rate = config.speech_rate
        self._dialect = config.dialect

    async def synthesize(self, text: str) -> SynthesizedAudio:
        chunks = [chunk.pcm16 async for chunk in self.synthesize_stream(text)]
        return SynthesizedAudio(pcm16=b"".join(chunks), sample_rate_hz=self._sample_rate_hz)

    async def warmup(self) -> None:
        """Open the reusable provider connection before the first response."""

        async with self._session_lock:
            await self._ensure_connection()

    async def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]:
        async with self._session_lock:
            self._last_connection_disconnects = 0
            for attempt in range(2):
                connection = await self._ensure_connection()
                session_finished = False
                audio_started = False
                retry = False
                try:
                    async for chunk in self._synthesize_session(connection, text):
                        audio_started = audio_started or bool(chunk.pcm16)
                        yield chunk
                    session_finished = True
                except ConnectionClosed:
                    self._last_connection_disconnects += 1
                    retry = attempt == 0 and not audio_started
                    if not retry:
                        raise
                finally:
                    # A cancelled or failed session can leave unread vendor
                    # frames on the socket. Never hand that dirty stream to the
                    # next synthesis.
                    if not session_finished:
                        await self._discard_connection(connection)
                if retry:
                    continue
                yield SynthesizedAudioChunk(
                    pcm16=b"",
                    sample_rate_hz=self._sample_rate_hz,
                    is_final=True,
                )
                return

    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        """Send text deltas and receive audio concurrently in one vendor session."""

        async with self._session_lock:
            self._last_connection_disconnects = 0
            connection: Any | None = None
            session_id: str | None = None
            for attempt in range(2):
                connection = await self._ensure_connection()
                try:
                    session_id = await self._start_session(connection)
                    break
                except ConnectionClosed:
                    self._last_connection_disconnects += 1
                    await self._discard_connection(connection)
                    if attempt == 1:
                        await _close_async_iterator(text_stream)
                        raise
                except BaseException:
                    await self._discard_connection(connection)
                    await _close_async_iterator(text_stream)
                    raise

            assert connection is not None
            assert session_id is not None
            session_finished = False
            session_stream = self._run_duplex_session(
                connection,
                session_id,
                text_stream,
            )
            try:
                async for chunk in session_stream:
                    yield chunk
                session_finished = True
            except ConnectionClosed:
                self._last_connection_disconnects += 1
                raise
            finally:
                await _close_async_iterator(session_stream)
                # Cancellation or a provider/input failure can leave frames
                # unread. A dirty connection must never serve the next turn.
                if not session_finished:
                    await self._discard_connection(connection)
            yield SynthesizedAudioChunk(
                pcm16=b"",
                sample_rate_hz=self._sample_rate_hz,
                is_final=True,
            )

    async def close(self) -> None:
        """Finish and close the reusable vendor connection, if one exists."""
        async with self._session_lock:
            connection, self._connection = self._connection, None
            if connection is None:
                return
            try:
                await connection.send(_build_frame(_EVENT_FINISH_CONNECTION, payload=b"{}"))
                await self._expect(
                    connection,
                    _EVENT_CONNECTION_FINISHED,
                    _EVENT_CONNECTION_FAILED,
                )
            except (ConnectionClosed, DoubaoTtsError):
                # Session shutdown is best effort. A vendor idle timeout must
                # not turn a successfully delivered conversation into a
                # Kernel failure while resources are being released.
                pass
            finally:
                await connection.close()

    async def _ensure_connection(self) -> Any:
        if self._connection is not None:
            self._last_connection_setup_ms = 0.0
            self._last_connection_reused = True
            return self._connection
        started_at = time.monotonic()
        connection = await connect(
            self._ws_url,
            additional_headers={
                "X-Api-Key": self._api_key,
                "X-Api-Resource-Id": self._resource_id,
                "X-Api-Connect-Id": str(uuid.uuid4()),
            },
        )
        try:
            await connection.send(_build_frame(_EVENT_START_CONNECTION, payload=b"{}"))
            await self._expect(
                connection,
                _EVENT_CONNECTION_STARTED,
                _EVENT_CONNECTION_FAILED,
            )
        except BaseException:
            await connection.close()
            raise
        self._connection = connection
        self._last_connection_setup_ms = (time.monotonic() - started_at) * 1000
        self._last_connection_reused = False
        return connection

    @property
    def last_connection_setup_ms(self) -> float | None:
        return self._last_connection_setup_ms

    @property
    def last_connection_reused(self) -> bool:
        return self._last_connection_reused

    @property
    def last_connection_disconnects(self) -> int:
        return self._last_connection_disconnects

    async def _synthesize_session(
        self,
        connection: Any,
        text: str,
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        session_id = await self._start_session(connection)
        await self._send_text(connection, session_id, text)
        await self._finish_session(connection, session_id)
        async for chunk in self._stream_audio(connection):
            yield chunk

    async def _start_session(self, connection: Any) -> str:
        session_id = uuid.uuid4().hex
        await connection.send(
            _build_frame(
                _EVENT_START_SESSION,
                session_id=session_id,
                payload=json.dumps(
                    {
                        "user": {"uid": "voiceagent"},
                        "event": _EVENT_START_SESSION,
                        "namespace": "BidirectionalTTS",
                        "req_params": {
                            "speaker": self._voice,
                            "audio_params": {
                                "format": "pcm",
                                "sample_rate": self._sample_rate_hz,
                                "speech_rate": self._speech_rate,
                                # enable_timestamp only takes effect for
                                # TTS1.0/ICL1.0; enable_subtitle is the
                                # TTS2.0/ICL2.0 equivalent (see ADR-0132).
                                # Both are requested since resource_id is
                                # configurable and may point at either.
                                "enable_timestamp": True,
                                "enable_subtitle": True,
                            },
                            **(
                                {
                                    "additions": json.dumps(
                                        {"explicit_dialect": self._dialect},
                                        ensure_ascii=False,
                                    )
                                }
                                if self._dialect
                                else {}
                            ),
                        },
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        )
        await self._expect(
            connection,
            _EVENT_SESSION_STARTED,
            _EVENT_SESSION_FAILED,
        )
        return session_id

    async def _send_text(self, connection: Any, session_id: str, text: str) -> None:
        await connection.send(
            _build_frame(
                _EVENT_TASK_REQUEST,
                session_id=session_id,
                payload=json.dumps(
                    {
                        "event": _EVENT_TASK_REQUEST,
                        "namespace": "BidirectionalTTS",
                        "req_params": {"text": text},
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        )

    async def _finish_session(self, connection: Any, session_id: str) -> None:
        await connection.send(
            _build_frame(
                _EVENT_FINISH_SESSION,
                session_id=session_id,
                payload=b"{}",
            )
        )

    async def _run_duplex_session(
        self,
        connection: Any,
        session_id: str,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        text_iterator = text_stream.__aiter__()
        text_task: asyncio.Task[str] | None = asyncio.create_task(anext(text_iterator))
        receive_task: asyncio.Task[bytes] | None = asyncio.create_task(connection.recv())
        input_finished = False
        try:
            while receive_task is not None:
                wait_for: set[asyncio.Task[Any]] = {receive_task}
                if text_task is not None:
                    wait_for.add(text_task)
                done, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)

                # Prefer ready text so an immediately available server frame
                # cannot overtake client input in deterministic test adapters.
                if text_task is not None and text_task in done:
                    try:
                        text = text_task.result()
                    except StopAsyncIteration:
                        input_finished = True
                        text_task = None
                        await self._finish_session(connection, session_id)
                    else:
                        if text:
                            await self._send_text(connection, session_id, text)
                        text_task = asyncio.create_task(anext(text_iterator))

                if receive_task not in done:
                    continue
                parsed = _parse_frame(receive_task.result())
                if parsed.get("error"):
                    raise DoubaoTtsError(self._safe_error(parsed["message"]))
                event = parsed["event"]
                if event == _EVENT_TTS_RESPONSE:
                    yield SynthesizedAudioChunk(
                        pcm16=parsed["payload"],
                        sample_rate_hz=self._sample_rate_hz,
                        is_final=False,
                    )
                elif event in (_EVENT_TTS_SENTENCE_END, _EVENT_TTS_SUBTITLE):
                    payload = _decode_json_payload(parsed["payload"])
                    for alignment in _alignment_chunks(payload, self._sample_rate_hz, event=event):
                        yield alignment
                elif event == _EVENT_SESSION_FAILED:
                    raise DoubaoTtsError(self._safe_error(_decode_json_payload(parsed["payload"])))
                elif event == _EVENT_SESSION_FINISHED:
                    if not input_finished:
                        raise DoubaoTtsError("provider finished before text input completed")
                    receive_task = None
                    continue
                elif event not in (_EVENT_SESSION_STARTED, _EVENT_TTS_SENTENCE_START):
                    logger.debug(
                        "Doubao TTS received unrecognized event=%d (payload keys: %s)",
                        event,
                        _payload_keys(parsed["payload"]),
                    )
                receive_task = asyncio.create_task(connection.recv())
        finally:
            pending = [task for task in (text_task, receive_task) if task is not None]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await _close_async_iterator(text_iterator)

    async def _discard_connection(self, connection: Any) -> None:
        if self._connection is connection:
            self._connection = None
        close_task = asyncio.create_task(connection.close())
        done, pending = await asyncio.wait(
            {close_task},
            timeout=_CONNECTION_CLOSE_TIMEOUT_S,
        )
        if done:
            await asyncio.gather(*done, return_exceptions=True)
            return
        logger.warning(
            "Doubao TTS connection close exceeded %.0fms; aborting transport",
            _CONNECTION_CLOSE_TIMEOUT_S * 1000,
        )
        transport = getattr(connection, "transport", None)
        abort = getattr(transport, "abort", None)
        if abort is not None:
            abort()
        for task in pending:
            task.cancel()
            task.add_done_callback(_consume_task_result)

    def _safe_error(self, detail: object) -> str:
        message = str(detail)[:1024]
        return message.replace(self._api_key, "[redacted]") if self._api_key else message

    async def _expect(self, connection: Any, expected_event: int, failure_event: int) -> None:
        raw = await connection.recv()
        parsed = _parse_frame(raw)
        if parsed.get("error"):
            raise DoubaoTtsError(self._safe_error(parsed["message"]))
        if parsed["event"] == failure_event:
            raise DoubaoTtsError(self._safe_error(_decode_json_payload(parsed["payload"])))
        if parsed["event"] != expected_event:
            raise DoubaoTtsError(
                f"expected event {expected_event}, got {parsed['event']}: "
                f"{self._safe_error(_decode_json_payload(parsed['payload']))}"
            )

    async def _stream_audio(self, connection: Any) -> AsyncIterator[SynthesizedAudioChunk]:
        async for raw in connection:
            parsed = _parse_frame(raw)
            if parsed.get("error"):
                raise DoubaoTtsError(self._safe_error(parsed["message"]))
            event = parsed["event"]
            if event == _EVENT_TTS_RESPONSE:
                yield SynthesizedAudioChunk(
                    pcm16=parsed["payload"], sample_rate_hz=self._sample_rate_hz, is_final=False
                )
            elif event in (_EVENT_TTS_SENTENCE_END, _EVENT_TTS_SUBTITLE):
                payload = _decode_json_payload(parsed["payload"])
                for alignment in _alignment_chunks(payload, self._sample_rate_hz, event=event):
                    yield alignment
            elif event == _EVENT_SESSION_FAILED:
                raise DoubaoTtsError(self._safe_error(_decode_json_payload(parsed["payload"])))
            elif event == _EVENT_SESSION_FINISHED:
                return
            elif event not in (
                _EVENT_SESSION_STARTED,
                _EVENT_TTS_SENTENCE_START,
            ):
                logger.debug(
                    "Doubao TTS received unrecognized event=%d (payload keys: %s)",
                    event,
                    _payload_keys(parsed["payload"]),
                )


async def _close_async_iterator(iterator: AsyncIterator[object]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


def _consume_task_result(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    task.exception()
