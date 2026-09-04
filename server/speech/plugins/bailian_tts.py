"""Alibaba Cloud Bailian Qwen-Audio-TTS/CosyVoice duplex TTS adapter.

The adapter speaks DashScope's JSON-over-WebSocket protocol directly so the
Speech Seam does not need the vendor SDK. One connection is reused across
successful, serial synthesis tasks. Incremental LLM text is sent with
``continue-task`` while raw PCM16 audio arrives on the binary channel.

Credentials are read from ``DASHSCOPE_API_KEY`` and are never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from server.speech.tts import SynthesizedAudio, SynthesizedAudioChunk

DEFAULT_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
DEFAULT_MODEL = "cosyvoice-v3-flash"
DEFAULT_VOICE = "longanhuan_v3"
DEFAULT_SAMPLE_RATE_HZ = 24000
_INFERENCE_PATH = "/api-ws/v1/inference"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{2,128}$")
_CONNECTION_CLOSE_TIMEOUT_S = 0.1
_GRACEFUL_CLOSE_TIMEOUT_S = 1.0
logger = logging.getLogger(__name__)


class BailianTtsError(RuntimeError):
    """Raised when Bailian rejects or prematurely ends a synthesis task."""


def _resolve_ws_url(value: str) -> str:
    """Accept a workspace host, HTTPS API host, or complete WebSocket URL."""

    candidate = value.strip()
    if not candidate:
        raise ValueError("Bailian API host must not be empty")
    if "://" not in candidate:
        candidate = f"wss://{candidate}"
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"https", "wss"}:
        raise ValueError("Bailian TTS requires an https:// or wss:// endpoint")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("invalid Bailian API host")
    path = parsed.path.rstrip("/") or _INFERENCE_PATH
    scheme = "wss"
    return urlunsplit((scheme, parsed.netloc, path, parsed.query, ""))


def _message(action: str, task_id: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "header": {
                "action": action,
                "task_id": task_id,
                "streaming": "duplex",
            },
            "payload": payload,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


class BailianTtsEngine:
    """Reusable Bailian duplex TTS conformer emitting mono 24 kHz PCM16."""

    provider_name = "bailian"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_host: str | None = None,
        ws_url: str | None = None,
        workspace_id: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        speech_rate: int = 0,
        instruction: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["DASHSCOPE_API_KEY"]
        configured_url = (
            ws_url
            or os.environ.get("BAILIAN_TTS_WS_URL")
            or api_host
            or os.environ.get("BAILIAN_API_HOST")
            or DEFAULT_WS_URL
        )
        self._ws_url = _resolve_ws_url(configured_url)
        self._workspace_id = workspace_id or os.environ.get("DASHSCOPE_WORKSPACE_ID")
        self._model = model or os.environ.get("BAILIAN_TTS_MODEL", DEFAULT_MODEL)
        self._voice = voice or os.environ.get("BAILIAN_TTS_VOICE", DEFAULT_VOICE)
        self._instruction = instruction or os.environ.get("BAILIAN_TTS_INSTRUCTION")
        self._sample_rate_hz = sample_rate_hz
        self._speech_rate = speech_rate
        self._validate_configuration()
        self._connection: Any | None = None
        self._session_lock = asyncio.Lock()

    def _validate_configuration(self) -> None:
        if not _ID_PATTERN.fullmatch(self._model):
            raise ValueError("invalid Bailian TTS model")
        if not _ID_PATTERN.fullmatch(self._voice):
            raise ValueError("invalid Bailian TTS voice")
        if self._workspace_id and not _ID_PATTERN.fullmatch(self._workspace_id):
            raise ValueError("invalid Bailian workspace ID")
        if self._sample_rate_hz != DEFAULT_SAMPLE_RATE_HZ:
            raise ValueError("Bailian avatar output must use 24000 Hz PCM")
        if not -50 <= self._speech_rate <= 100:
            raise ValueError("speech_rate must be between -50 and 100")

    async def synthesize(self, text: str) -> SynthesizedAudio:
        chunks = [chunk.pcm16 async for chunk in self.synthesize_stream(text)]
        return SynthesizedAudio(pcm16=b"".join(chunks), sample_rate_hz=self._sample_rate_hz)

    async def warmup(self) -> None:
        async with self._session_lock:
            await self._ensure_connection()

    async def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]:
        async with self._session_lock:
            connection, task_id = await self._start_task_with_retry()
            task_finished = False
            try:
                if text:
                    await self._send_text(connection, task_id, text)
                await self._finish_task(connection, task_id)
                async for chunk in self._stream_task(connection, task_id):
                    yield chunk
                task_finished = True
            finally:
                if not task_finished:
                    await self._cancel_and_discard(connection, task_id)
            yield SynthesizedAudioChunk(
                pcm16=b"",
                sample_rate_hz=self._sample_rate_hz,
                is_final=True,
            )

    async def synthesize_duplex(
        self,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        async with self._session_lock:
            connection, task_id = await self._start_task_with_retry()
            task_finished = False
            task_stream = self._run_duplex_task(connection, task_id, text_stream)
            try:
                async for chunk in task_stream:
                    yield chunk
                task_finished = True
            finally:
                await _close_async_iterator(task_stream)
                if not task_finished:
                    await self._cancel_and_discard(connection, task_id)
            yield SynthesizedAudioChunk(
                pcm16=b"",
                sample_rate_hz=self._sample_rate_hz,
                is_final=True,
            )

    async def close(self) -> None:
        async with self._session_lock:
            connection, self._connection = self._connection, None
            if connection is None:
                return
            try:
                await asyncio.wait_for(
                    connection.close(),
                    timeout=_GRACEFUL_CLOSE_TIMEOUT_S,
                )
            except TimeoutError:
                transport = getattr(connection, "transport", None)
                abort = getattr(transport, "abort", None)
                if abort is not None:
                    abort()

    async def _ensure_connection(self) -> Any:
        if self._connection is not None:
            return self._connection
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "OpenRealtime/0.3",
        }
        if self._workspace_id:
            headers["X-DashScope-WorkSpace"] = self._workspace_id
        connection = await connect(self._ws_url, additional_headers=headers)
        self._connection = connection
        return connection

    async def _start_task_with_retry(self) -> tuple[Any, str]:
        for attempt in range(2):
            connection = await self._ensure_connection()
            task_id = str(uuid.uuid4())
            try:
                await self._start_task(connection, task_id)
                return connection, task_id
            except ConnectionClosed:
                await self._discard_connection(connection)
                if attempt == 1:
                    raise
            except BaseException:
                await self._discard_connection(connection)
                raise
        raise AssertionError("unreachable")

    async def _start_task(self, connection: Any, task_id: str) -> None:
        parameters: dict[str, Any] = {
            "text_type": "PlainText",
            "voice": self._voice,
            "format": "pcm",
            "sample_rate": self._sample_rate_hz,
            "volume": 50,
            "rate": 1.0 + self._speech_rate / 100,
            "pitch": 1.0,
            "enable_ssml": False,
        }
        if self._instruction:
            parameters["instruction"] = self._instruction
        await connection.send(
            _message(
                "run-task",
                task_id,
                {
                    "task_group": "audio",
                    "task": "tts",
                    "function": "SpeechSynthesizer",
                    "model": self._model,
                    "parameters": parameters,
                    "input": {},
                },
            )
        )
        raw = await connection.recv()
        event = self._parse_event(raw, task_id)
        if event != "task-started":
            raise BailianTtsError(f"expected task-started, got {event or 'binary audio'}")

    async def _send_text(self, connection: Any, task_id: str, text: str) -> None:
        await connection.send(_message("continue-task", task_id, {"input": {"text": text}}))

    async def _finish_task(
        self,
        connection: Any,
        task_id: str,
        *,
        cancel: bool = False,
    ) -> None:
        input_payload = {"directive": "cancel"} if cancel else {}
        await connection.send(_message("finish-task", task_id, {"input": input_payload}))

    async def _stream_task(
        self,
        connection: Any,
        task_id: str,
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        while True:
            raw = await connection.recv()
            if isinstance(raw, bytes):
                yield self._audio_chunk(raw)
                continue
            event = self._parse_event(raw, task_id)
            if event == "task-finished":
                return

    async def _run_duplex_task(
        self,
        connection: Any,
        task_id: str,
        text_stream: AsyncIterator[str],
    ) -> AsyncIterator[SynthesizedAudioChunk]:
        text_iterator = text_stream.__aiter__()
        text_task: asyncio.Task[str] | None = asyncio.create_task(anext(text_iterator))
        receive_task: asyncio.Task[str | bytes] | None = asyncio.create_task(connection.recv())
        input_finished = False
        try:
            while receive_task is not None:
                pending: set[asyncio.Task[Any]] = {receive_task}
                if text_task is not None:
                    pending.add(text_task)
                done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

                if text_task is not None and text_task in done:
                    try:
                        text = text_task.result()
                    except StopAsyncIteration:
                        input_finished = True
                        text_task = None
                        await self._finish_task(connection, task_id)
                    else:
                        if text:
                            await self._send_text(connection, task_id, text)
                        text_task = asyncio.create_task(anext(text_iterator))

                if receive_task not in done:
                    continue
                raw = receive_task.result()
                if isinstance(raw, bytes):
                    yield self._audio_chunk(raw)
                else:
                    event = self._parse_event(raw, task_id)
                    if event == "task-finished":
                        if not input_finished:
                            raise BailianTtsError("provider finished before text input completed")
                        receive_task = None
                        continue
                receive_task = asyncio.create_task(connection.recv())
        finally:
            tasks = [task for task in (text_task, receive_task) if task is not None]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await _close_async_iterator(text_iterator)

    def _parse_event(self, raw: str | bytes, task_id: str) -> str:
        if isinstance(raw, bytes):
            return ""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BailianTtsError("Bailian returned invalid JSON") from error
        header = message.get("header", {})
        response_task_id = header.get("task_id")
        if response_task_id and response_task_id != task_id:
            raise BailianTtsError("Bailian returned an event for another task")
        event = str(header.get("event", ""))
        if event == "task-failed":
            code = str(header.get("error_code", "provider_error"))
            detail = str(header.get("error_message", "TTS task failed"))
            if self._api_key:
                detail = detail.replace(self._api_key, "[redacted]")
            raise BailianTtsError(f"{code}: {detail}")
        return event

    def _audio_chunk(self, pcm16: bytes) -> SynthesizedAudioChunk:
        return SynthesizedAudioChunk(
            pcm16=pcm16,
            sample_rate_hz=self._sample_rate_hz,
            is_final=False,
        )

    async def _cancel_and_discard(self, connection: Any, task_id: str) -> None:
        try:
            await self._finish_task(connection, task_id, cancel=True)
        except Exception:
            logger.debug("Bailian TTS cancel event failed", exc_info=True)
        await self._discard_connection(connection)

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
            "Bailian TTS connection close exceeded %.0fms; aborting transport",
            _CONNECTION_CLOSE_TIMEOUT_S * 1000,
        )
        transport = getattr(connection, "transport", None)
        abort = getattr(transport, "abort", None)
        if abort is not None:
            abort()
        for task in pending:
            task.cancel()
            task.add_done_callback(_consume_task_result)


async def _close_async_iterator(iterator: AsyncIterator[object]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


def _consume_task_result(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    task.exception()
