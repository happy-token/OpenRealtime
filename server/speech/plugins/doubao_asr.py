"""Real Doubao (火山引擎) ASR conformer — see CONTEXT.md: AsrEngine.

Speaks Doubao's binary-framed bidirectional streaming WebSocket protocol. The
default endpoint is ``bigmodel``; ``DOUBAO_ASR_WS_URL`` or the constructor's
``ws_url`` argument can select another compatible endpoint. The connection is
opened lazily on first audio, reused while audio keeps flowing, and restarted
after vendor idle/error closure. Provider
`definite` markers are normalized into `AsrSnapshot.sentence_end_revision`;
they remain observations, while the Semantic Endpoint Gate owns the final
commit decision together with VAD and semantic completeness.

Uses the same single-key auth style as doubao_tts_direct.py (`X-Api-Key` /
`DOUBAO_API_KEY`) against `volc.seedasr.sauc.duration`, confirmed granted
and working end-to-end against real speech. The legacy two-credential
(`DOUBAO_APP_ID`/`DOUBAO_Token`) auth style also works on this account but
isn't needed once a single key covers both ASR and TTS (YAGNI).

The credential (`DOUBAO_API_KEY`) is read from the environment and never
logged or printed. See ADR-0058 for the endpoint benchmark and default choice.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import struct
import time
import uuid
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from server.speech.asr import AsrSession, AsrSnapshot

logger = logging.getLogger(__name__)

BIGMODEL_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
BIGMODEL_ASYNC_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DEFAULT_URL = BIGMODEL_URL
RESOURCE_ID = "volc.seedasr.sauc.duration"

_FULL_CLIENT_REQUEST = 0b0001
_AUDIO_ONLY_REQUEST = 0b0010
_FULL_SERVER_RESPONSE = 0b1001
_ERROR_RESPONSE = 0b1111

_FLAGS_POS_SEQ = 0b0001
_FLAGS_LAST_NO_SEQ = 0b0010
_FLAGS_LAST_SEQ = 0b0011


def _build_frame(msg_type: int, flags: int, payload: bytes, *, seq: int | None = None) -> bytes:
    """Encode one Doubao binary-protocol frame. Pure, unit-testable."""
    byte0 = 0x11  # protocol version 1, header size 1 (4 bytes)
    byte1 = (msg_type << 4) | flags
    serialization = 0b0001 if msg_type == _FULL_CLIENT_REQUEST else 0b0000
    byte2 = serialization << 4  # no compression
    header = bytes([byte0, byte1, byte2, 0x00])
    frame = header
    if seq is not None:
        frame += struct.pack(">i", seq)
    frame += struct.pack(">I", len(payload))
    frame += payload
    return frame


def _parse_frame(data: bytes) -> dict[str, Any]:
    """Decode one Doubao binary-protocol response frame. Pure, unit-testable."""
    if len(data) < 4:
        return {"error": True, "message": "frame too short"}

    byte1 = data[1]
    msg_type = (byte1 >> 4) & 0x0F
    flags = byte1 & 0x0F
    compression = data[2] & 0x0F if len(data) > 2 else 0
    offset = 4

    if msg_type == _ERROR_RESPONSE:
        code = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        raw_message = data[offset : offset + size]
        message = raw_message.decode("utf-8", errors="replace")
        if "�" in message:
            # Suspected mechanism (unconfirmed, see ADR-0132): a server
            # response whose actual compression flag doesn't match what we
            # requested would land this slice mid codepoint. Logged, not
            # raised — a diagnostic field must never break the session.
            logger.warning(
                "Doubao ASR error message failed clean UTF-8 decode "
                "(compression=%d, size=%d bytes) — see ADR-0132",
                compression, len(raw_message),
            )
        return {"error": True, "code": code, "message": message}

    if flags in (_FLAGS_POS_SEQ, _FLAGS_LAST_SEQ):
        offset += 4  # sequence number, unused on decode

    payload_size = struct.unpack(">I", data[offset : offset + 4])[0]
    offset += 4
    payload = data[offset : offset + payload_size]

    if msg_type == _FULL_SERVER_RESPONSE:
        return json.loads(payload.decode("utf-8")) if payload else {}
    return {}


def _merge_single_result_segment(committed: str, segment: str) -> str:
    """Project one provider ``result_type=single`` segment into turn text.

    A short endpoint window can finalize several segments during one user
    turn. Some provider responses are cumulative while others contain only
    the newest segment, so accept both shapes without duplicating text.
    """
    if not committed or segment.startswith(committed):
        return segment
    if committed.endswith(segment):
        return committed
    needs_space = (
        committed[-1].isascii()
        and committed[-1].isalnum()
        and segment[0].isascii()
        and segment[0].isalnum()
    )
    return f"{committed}{' ' if needs_space else ''}{segment}"


def _project_unconsumed_text(provider_text: str, consumed_text: str) -> str:
    """Remove a session-cumulative prefix already committed as older turns."""

    if consumed_text and provider_text.startswith(consumed_text):
        return provider_text[len(consumed_text) :].lstrip()
    return provider_text


class DoubaoAsrSession:
    def __init__(
        self,
        connection: ClientConnection,
        *,
        sample_rate_hz: int | None = None,
        packet_duration_ms: int | None = None,
        commit_wait_ms: float = 512,
        api_key: str = "",
    ) -> None:
        if (sample_rate_hz is None) != (packet_duration_ms is None):
            raise ValueError(
                "sample_rate_hz and packet_duration_ms must be configured together"
            )
        if sample_rate_hz is not None and sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if packet_duration_ms is not None and packet_duration_ms <= 0:
            raise ValueError("packet_duration_ms must be positive")
        if commit_wait_ms < 0:
            raise ValueError("commit_wait_ms must be non-negative")
        self._connection = connection
        self._sample_rate_hz = sample_rate_hz
        self._provider_packet_bytes = (
            sample_rate_hz * packet_duration_ms * 2 // 1000
            if sample_rate_hz is not None and packet_duration_ms is not None
            else None
        )
        self._pending_audio = bytearray()
        self._audio_lock = asyncio.Lock()
        self._commit_wait_s = commit_wait_ms / 1000
        self._transcript = ""
        self._committed_transcript = ""
        self._consumed_transcript = ""
        self._revision = 0
        self._sentence_end_revision = 0
        self._seq = 2
        self._alive = True
        self._updates = asyncio.Condition()
        self._provider_failure: RuntimeError | None = None
        self._api_key = api_key
        self._started_at = time.monotonic()
        self._reader_task = asyncio.ensure_future(self._read_loop())

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None:
        if self._provider_failure is not None:
            raise self._provider_failure
        if not self._alive:
            return
        if self._sample_rate_hz is not None and sample_rate_hz != self._sample_rate_hz:
            raise ValueError(
                f"sample_rate_hz changed from {self._sample_rate_hz} to {sample_rate_hz}"
            )
        async with self._audio_lock:
            if self._provider_packet_bytes is not None:
                self._pending_audio.extend(pcm16)
                while len(self._pending_audio) >= self._provider_packet_bytes:
                    payload = bytes(self._pending_audio[: self._provider_packet_bytes])
                    if not await self._send_audio(payload):
                        return
                    del self._pending_audio[: self._provider_packet_bytes]
                return
            await self._send_audio(pcm16)

    async def _send_audio(self, pcm16: bytes) -> bool:
        frame = _build_frame(_AUDIO_ONLY_REQUEST, _FLAGS_POS_SEQ, pcm16, seq=self._seq)
        self._seq += 1
        try:
            await self._connection.send(frame)
        except ConnectionClosed:
            async with self._updates:
                self._alive = False
                self._updates.notify_all()
            return False
        return True

    async def consume_transcript(self) -> str:
        if self._provider_failure is not None:
            raise self._provider_failure
        async with self._updates:
            revision_before_flush = self._revision
            endpoint_before_flush = self._sentence_end_revision
        flushed = await self._flush_pending_audio()
        # Provider results trail the audio stream.  A packet-aligned VAD stop
        # has nothing left in ``_pending_audio``, but its punctuation/final
        # revision can still be in flight.  Waiting only after a local flush
        # stranded that revision in the following turn (for example
        # ``今天天气怎么样`` + ``？``).  A provider endpoint already observed for
        # the current revision is the only safe zero-wait fast path.
        endpoint_is_current = (
            revision_before_flush > 0
            and endpoint_before_flush >= revision_before_flush
        )
        if (
            self._alive
            and self._commit_wait_s > 0
            and (flushed or not endpoint_is_current)
        ):
            try:
                async with asyncio.timeout(self._commit_wait_s):
                    async with self._updates:
                        while self._alive:
                            endpoint_is_current = (
                                self._revision > 0
                                and self._sentence_end_revision >= self._revision
                            )
                            flushed_audio_was_observed = (
                                not flushed
                                or self._revision > revision_before_flush
                                or self._sentence_end_revision > endpoint_before_flush
                            )
                            if endpoint_is_current and flushed_audio_was_observed:
                                break
                            await self._updates.wait()
            except TimeoutError:
                pass
        async with self._updates:
            if self._provider_failure is not None:
                raise self._provider_failure
            transcript, self._transcript = self._transcript, ""
            self._committed_transcript = ""
            self._consumed_transcript += transcript
            return transcript

    async def _flush_pending_audio(self) -> bool:
        async with self._audio_lock:
            if not self._pending_audio or not self._alive:
                return False
            payload = bytes(self._pending_audio)
            self._pending_audio.clear()
            return await self._send_audio(payload)

    async def peek_transcript(self) -> str:
        async with self._updates:
            return self._transcript

    async def snapshot(self) -> AsrSnapshot:
        async with self._updates:
            return self._snapshot_unlocked()

    async def wait_for_update(
        self,
        *,
        after_revision: int,
        after_sentence_end_revision: int,
    ) -> AsrSnapshot:
        async with self._updates:
            while (
                self._alive
                and self._revision <= after_revision
                and self._sentence_end_revision <= after_sentence_end_revision
            ):
                await self._updates.wait()
            if self._provider_failure is not None:
                raise self._provider_failure
            return self._snapshot_unlocked()

    async def close(self) -> None:
        await self._flush_pending_audio()
        with contextlib.suppress(ConnectionClosed):
            await self._connection.send(_build_frame(_AUDIO_ONLY_REQUEST, _FLAGS_LAST_NO_SEQ, b""))
        self._reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader_task
        await self._connection.close()

    async def _read_loop(self) -> None:
        try:
            async for raw in self._connection:
                if not isinstance(raw, bytes) or len(raw) < 4:
                    continue
                response = _parse_frame(raw)
                if response.get("error"):
                    message = str(response.get("message", ""))[:256]
                    if self._api_key:
                        message = message.replace(self._api_key, "[redacted]")
                    self._provider_failure = RuntimeError(
                        f"Doubao ASR code={response.get('code')}: {message}"
                    )
                    logger.warning(
                        "Doubao ASR vendor ended session after %.1fms (code=%s)",
                        (time.monotonic() - self._started_at) * 1000,
                        response.get("code"),
                    )
                    break
                if response.get("unknown"):
                    continue
                result = response.get("result", {})
                provider_text = result.get("text", "")
                if provider_text:
                    async with self._updates:
                        text = _project_unconsumed_text(
                            provider_text,
                            self._consumed_transcript,
                        )
                        if not text:
                            continue
                        utterances = result.get("utterances", ())
                        is_sentence_end = bool(result.get("definite")) or any(
                            isinstance(utterance, dict) and bool(utterance.get("definite"))
                            for utterance in utterances
                        )
                        merged_text = _merge_single_result_segment(
                            self._committed_transcript,
                            text,
                        )
                        if merged_text != self._transcript:
                            self._revision += 1
                        self._transcript = merged_text
                        if is_sentence_end:
                            self._committed_transcript = merged_text
                            self._sentence_end_revision = self._revision
                        self._updates.notify_all()
        except ConnectionClosed as exc:
            logger.warning(
                "Doubao ASR session closed after %.1fms: %s",
                (time.monotonic() - self._started_at) * 1000,
                exc,
            )
        except Exception:
            logger.exception(
                "Doubao ASR session read loop failed after %.1fms",
                (time.monotonic() - self._started_at) * 1000,
            )
            raise
        finally:
            async with self._updates:
                self._alive = False
                self._updates.notify_all()

    def _snapshot_unlocked(self) -> AsrSnapshot:
        return AsrSnapshot(
            text=self._transcript,
            revision=self._revision,
            sentence_end_revision=self._sentence_end_revision,
            supports_sentence_end=True,
        )


class DoubaoAsrEngine:
    """Real conformer: opens one WebSocket session per call against
    Volcengine's Doubao bidirectional streaming ASR endpoint.
    """

    provider_name = "doubao"

    def __init__(
        self,
        api_key: str | None = None,
        ws_url: str | None = None,
        *,
        sample_rate_hz: int = 16000,
        end_window_size_ms: int | None = None,
        packet_duration_ms: int | None = None,
        commit_wait_ms: float | None = None,
        connect_timeout_s: float = 5.0,
    ) -> None:
        if connect_timeout_s <= 0:
            raise ValueError("connect_timeout_s must be positive")
        resolved_end_window_ms = (
            int(os.environ.get("DOUBAO_ASR_END_WINDOW_MS", "256"))
            if end_window_size_ms is None
            else end_window_size_ms
        )
        if resolved_end_window_ms <= 0:
            raise ValueError("end_window_size_ms must be positive")
        resolved_packet_duration_ms = (
            int(os.environ.get("DOUBAO_ASR_PACKET_MS", "100"))
            if packet_duration_ms is None
            else packet_duration_ms
        )
        if not 100 <= resolved_packet_duration_ms <= 200:
            raise ValueError("packet_duration_ms must be between 100 and 200")
        resolved_commit_wait_ms = (
            float(os.environ.get("DOUBAO_ASR_COMMIT_WAIT_MS", "512"))
            if commit_wait_ms is None
            else commit_wait_ms
        )
        if resolved_commit_wait_ms < 0:
            raise ValueError("commit_wait_ms must be non-negative")
        self._api_key = api_key or os.environ["DOUBAO_API_KEY"]
        self._ws_url = ws_url or os.environ.get("DOUBAO_ASR_WS_URL", DEFAULT_URL)
        self._sample_rate_hz = sample_rate_hz
        self._end_window_size_ms = resolved_end_window_ms
        self._packet_duration_ms = resolved_packet_duration_ms
        self._commit_wait_ms = resolved_commit_wait_ms
        self._connect_timeout_s = connect_timeout_s

    @property
    def connect_timeout_s(self) -> float:
        return self._connect_timeout_s

    async def start_session(self) -> AsrSession:
        config = {
            "user": {"uid": "voiceagent"},
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": self._sample_rate_hz,
                "bits": 16,
                "channel": 1,
                "language": "zh-CN",
            },
            "request": {
                "model_name": "bigmodel",
                "enable_nonstream": True,
                "enable_punc": True,
                "enable_itn": True,
                "end_window_size": self._end_window_size_ms,
                "show_utterances": True,
                "result_type": "single",
            },
        }
        payload = json.dumps(config, ensure_ascii=False).encode("utf-8")
        async with asyncio.timeout(self._connect_timeout_s):
            connection = await connect(
                self._ws_url,
                additional_headers={
                    "X-Api-Key": self._api_key,
                    "X-Api-Resource-Id": RESOURCE_ID,
                    "X-Api-Request-Id": str(uuid.uuid4()),
                    "X-Api-Sequence": "-1",
                },
            )
            await connection.send(
                _build_frame(_FULL_CLIENT_REQUEST, _FLAGS_POS_SEQ, payload, seq=1)
            )
        return DoubaoAsrSession(
            connection,
            sample_rate_hz=self._sample_rate_hz,
            packet_duration_ms=self._packet_duration_ms,
            commit_wait_ms=self._commit_wait_ms,
            api_key=self._api_key,
        )
