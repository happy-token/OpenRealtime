"""Real Bella-gateway ASR conformer — see CONTEXT.md: AsrEngine.

Speaks the company-internal Bella OpenAPI gateway's NLS-style streaming ASR
protocol (`wss://bella-openapi.ke.com/v1/audio/asr/stream`), a JSON
control-message-plus-raw-binary-audio WebSocket protocol, ported from
`../realtime/server/bridges/bella_stt.py` (voiceloop's real, pipecat-based
client for the same endpoint). Only the wire protocol is ported; OpenRealtime's
provider-neutral `AsrSnapshot` exposes both transcript revisions and
`SentenceEnd`, while the Semantic Endpoint Gate combines those observations
with VAD and semantic completeness.

The credential (`API_KEY`) is read from the environment and never logged or
printed — the same credential speech/doubao_tts.py already reads, per the
"one unified key/base_url across ASR/TTS/LLM" pattern used by the Bella
gateway.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from server.speech.asr import AsrSession, AsrSnapshot

DEFAULT_URL = "wss://bella-openapi.ke.com/v1/audio/asr/stream"
DEFAULT_MODEL = "huoshanLM-realtime-asr"

logger = logging.getLogger(__name__)


class BellaAsrError(RuntimeError):
    """Raised when the Bella gateway fails to start a transcription session."""


def _control_message(task_id: str, name: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "header": {
                "message_id": uuid.uuid4().hex,
                "task_id": task_id,
                "namespace": "SpeechTranscriber",
                "name": name,
                "appkey": "voiceagent",
            },
            "payload": payload,
        },
        ensure_ascii=False,
    )


class BellaAsrSession:
    def __init__(self, connection: ClientConnection, task_id: str, api_key: str = "") -> None:
        self._connection = connection
        self._task_id = task_id
        self._transcript = ""
        self._revision = 0
        self._sentence_end_revision = 0
        self._alive = True
        self._api_key = api_key
        self._provider_failure: BellaAsrError | None = None
        self._updates = asyncio.Condition()
        self._started_at = time.monotonic()
        self._pushed_since_consume = False
        self._reader_task = asyncio.ensure_future(self._read_loop())

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None:
        if self._provider_failure is not None:
            raise self._provider_failure
        if not self._alive:
            return
        if not self._pushed_since_consume:
            # Bella's finalize for the prior turn can arrive after that turn's
            # consume_transcript() already drained it (network/processing lag
            # past Turn Policy's own, content-independent EOT). Discard any such
            # leftover here rather than let it get handed to this new turn.
            async with self._updates:
                self._transcript = ""
                self._pushed_since_consume = True
        try:
            await self._connection.send(pcm16)
        except ConnectionClosed:
            async with self._updates:
                self._alive = False
                self._updates.notify_all()

    async def consume_transcript(self) -> str:
        async with self._updates:
            if self._provider_failure is not None:
                raise self._provider_failure
            transcript, self._transcript = self._transcript, ""
            self._pushed_since_consume = False
            return transcript

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
        with contextlib.suppress(ConnectionClosed):
            await self._connection.send(_control_message(self._task_id, "StopTranscription", {}))
        self._reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader_task
        await self._connection.close()

    async def _read_loop(self) -> None:
        try:
            async for raw in self._connection:
                if isinstance(raw, bytes):
                    continue
                event = json.loads(raw)
                header = event.get("header", {})
                name = header.get("name", "")
                payload = event.get("payload", {})
                if name in ("TranscriptionResultChanged", "SentenceEnd"):
                    text = payload.get("result", "")
                    if text:
                        async with self._updates:
                            if text != self._transcript:
                                self._revision += 1
                            self._transcript = text
                            if name == "SentenceEnd":
                                self._sentence_end_revision = self._revision
                            self._updates.notify_all()
                elif name == "TaskFailed":
                    detail = str(payload.get("message", ""))[:1024]
                    if self._api_key:
                        detail = detail.replace(self._api_key, "[redacted]")
                    self._provider_failure = BellaAsrError(detail)
                    logger.warning(
                        "Bella ASR TaskFailed after %.1fms: %s",
                        (time.monotonic() - self._started_at) * 1000,
                        detail,
                    )
                    self._alive = False
                    break
        except ConnectionClosed as exc:
            logger.warning(
                "Bella ASR session closed after %.1fms: %s",
                (time.monotonic() - self._started_at) * 1000,
                exc,
            )
        except Exception:
            logger.exception(
                "Bella ASR session read loop failed after %.1fms",
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


class BellaAsrEngine:
    """Real conformer: opens one WebSocket session per `start_session()` call
    against the Bella OpenAPI gateway's streaming ASR endpoint.
    """

    def __init__(
        self,
        api_key: str | None = None,
        ws_url: str = DEFAULT_URL,
        model: str = DEFAULT_MODEL,
        *,
        sample_rate_hz: int = 16000,
        end_window_size_ms: int = 200,
    ) -> None:
        self._api_key = api_key or os.environ["API_KEY"]
        self._ws_url = ws_url
        self._model = model
        self._sample_rate_hz = sample_rate_hz
        self._end_window_size_ms = end_window_size_ms

    async def start_session(self) -> AsrSession:
        connection = await connect(
            f"{self._ws_url}?model={self._model}",
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
                "format": "pcm",
                "sample_rate": str(self._sample_rate_hz),
            },
        )
        task_id = uuid.uuid4().hex
        await connection.send(
            _control_message(
                task_id,
                "StartTranscription",
                {
                    "format": "pcm",
                    "sample_rate": self._sample_rate_hz,
                    "enable_intermediate_result": True,
                    "enable_punctuation_prediction": True,
                    "enable_inverse_text_normalization": True,
                    "end_window_size": self._end_window_size_ms,
                },
            )
        )
        started_task_id = await self._await_started(connection)
        return BellaAsrSession(connection, started_task_id, self._api_key)

    async def _await_started(self, connection: ClientConnection) -> str:
        async for raw in connection:
            if isinstance(raw, bytes):
                continue
            event = json.loads(raw)
            header = event.get("header", {})
            if header.get("name") == "TranscriptionStarted":
                return str(header.get("task_id", ""))
            if header.get("name") == "TaskFailed":
                detail = str(event.get("payload", {}).get("message", ""))[:1024]
                raise BellaAsrError(detail.replace(self._api_key, "[redacted]"))
        raise BellaAsrError("connection closed before TranscriptionStarted")
