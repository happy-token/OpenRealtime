"""Qwen-ASR-Realtime adapter for the shared streaming ASR contract."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import uuid
from urllib.parse import urlencode, urlsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from server.speech.asr import AsrSession, AsrSnapshot

DEFAULT_MODEL = "qwen3-asr-flash-realtime"
_HOST = re.compile(r"(?:[a-z0-9][a-z0-9-]{1,127}\.(?:cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com|dashscope(?:-intl)?\.aliyuncs\.com)\Z")


def realtime_url(base_url: str, model: str = DEFAULT_MODEL) -> str:
    """Validate the vendor origin again at the Python network boundary."""
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not _HOST.fullmatch(parsed.hostname or "")
            or parsed.path.rstrip("/") or parsed.port or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not re.fullmatch(r"qwen[\w.-]*asr[\w.-]*realtime", model)):
        raise ValueError("invalid Bailian ASR endpoint or model")
    return f"wss://{parsed.hostname}/api-ws/v1/realtime?{urlencode({'model': model})}"


class BailianAsrSession:
    def __init__(self, connection) -> None:
        self._connection = connection
        self._committed = ""
        self._preview = ""
        self._revision = 0
        self._sentence_end_revision = 0
        self._alive = True
        self._failure: RuntimeError | None = None
        self._updates = asyncio.Condition()
        self._reader = asyncio.create_task(self._read_loop())

    @property
    def is_alive(self) -> bool:
        return self._alive

    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None:
        if sample_rate_hz != 16000 or len(pcm16) % 2:
            raise ValueError("Bailian ASR requires 16 kHz mono PCM16")
        if self._failure:
            raise self._failure
        if not self._alive:
            raise RuntimeError("Bailian ASR session is closed")
        if pcm16:
            await self._connection.send(json.dumps({
                "event_id": str(uuid.uuid4()), "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm16).decode("ascii"),
            }))

    async def peek_transcript(self) -> str:
        return (await self.snapshot()).text

    async def consume_transcript(self) -> str:
        async with self._updates:
            if self._failure:
                raise self._failure
            text = self._committed + self._preview
            self._committed = self._preview = ""
            return text

    def _snapshot(self) -> AsrSnapshot:
        return AsrSnapshot(self._committed + self._preview, self._revision,
                           self._sentence_end_revision, supports_sentence_end=True)

    async def snapshot(self) -> AsrSnapshot:
        async with self._updates:
            if self._failure:
                raise self._failure
            return self._snapshot()

    async def wait_for_update(self, *, after_revision: int,
                              after_sentence_end_revision: int) -> AsrSnapshot:
        async with self._updates:
            while self._alive and self._revision <= after_revision \
                    and self._sentence_end_revision <= after_sentence_end_revision:
                await self._updates.wait()
            if self._failure:
                raise self._failure
            return self._snapshot()

    async def close(self) -> None:
        if self._alive:
            with contextlib.suppress(ConnectionClosed):
                await self._connection.send(json.dumps({"event_id": str(uuid.uuid4()), "type": "session.finish"}))
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
        await self._connection.close()

    async def _read_loop(self) -> None:
        try:
            async for raw in self._connection:
                if not isinstance(raw, str):
                    continue
                event = json.loads(raw)
                kind = event.get("type")
                if kind in {"error", "conversation.item.input_audio_transcription.failed"}:
                    self._failure = RuntimeError("Bailian ASR rejected the session")
                    break
                async with self._updates:
                    if kind == "conversation.item.input_audio_transcription.text":
                        preview = str(event.get("text") or "") + str(event.get("stash") or "")
                        if preview != self._preview:
                            self._preview = preview
                            self._revision += 1
                            self._updates.notify_all()
                    elif kind == "conversation.item.input_audio_transcription.completed":
                        final = str(event.get("transcript") or "")
                        if final:
                            self._committed += final
                            self._preview = ""
                            self._revision += 1
                            self._sentence_end_revision = self._revision
                            self._updates.notify_all()
        except (ConnectionClosed, ValueError):
            self._failure = RuntimeError("Bailian ASR connection ended")
        finally:
            async with self._updates:
                self._alive = False
                self._updates.notify_all()


class BailianAsrEngine:
    provider_name = "dashscope"

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None,
                 model: str = DEFAULT_MODEL) -> None:
        self._api_key = api_key or os.environ["DASHSCOPE_API_KEY"]
        workspace = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
        default_url = (f"https://{workspace}.cn-beijing.maas.aliyuncs.com" if workspace
                       else "https://dashscope.aliyuncs.com")
        self._url = realtime_url(base_url or default_url, model)

    async def start_session(self) -> AsrSession:
        async with asyncio.timeout(8):
            connection = await connect(self._url, additional_headers={
                "Authorization": f"Bearer {self._api_key}",
            })
            await connection.send(json.dumps({
                "event_id": str(uuid.uuid4()), "type": "session.update",
                "session": {"input_audio_format": "pcm", "sample_rate": 16000,
                            "turn_detection": {"type": "server_vad", "threshold": 0.0,
                                               "silence_duration_ms": 400}},
            }))
        return BailianAsrSession(connection)
