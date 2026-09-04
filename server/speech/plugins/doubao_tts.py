"""Real Doubao (火山引擎) TTS conformer — see CONTEXT.md: TtsEngine.

Speaks doubao-seed-tts-2.0 through the company-internal Bella OpenAPI
gateway (`wss://bella-openapi.ke.com/v1/audio/tts/stream`), a plain
JSON-over-WebSocket protocol, documented in ../bench/docs/apis/doubao-tts.md.

The *direct* Volcengine V3 TTS endpoint is deliberately not used here — it
is confirmed broken (connects, but never responds to any binary-protocol
variant tried; see ../bench/docs/issues/tts-protocol-debug.md and
docs/adr/0011-doubao-asr-tts-as-swappable-speech-seam.md). `.env`'s
`DOUBAO_TTS_WS_URL`/`DOUBAO_RESOURCE_ID` point at that broken endpoint and
are intentionally unused by this module.

The credential (`API_KEY`) is read from the environment and never logged
or printed.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from websockets.asyncio.client import connect

from server.speech.tts import SynthesizedAudio, SynthesizedAudioChunk

DEFAULT_URL = "wss://bella-openapi.ke.com/v1/audio/tts/stream"
DEFAULT_VOICE = "zh_male_yuanboxiaoshu_uranus_bigtts"
DEFAULT_SAMPLE_RATE_HZ = 24000


class DoubaoTtsError(RuntimeError):
    """Raised when the Bella gateway reports a SpeechFailed event."""


def _event(task_id: str, name: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "header": {
                "message_id": uuid.uuid4().hex,
                "task_id": task_id,
                "namespace": "TTS",
                "name": name,
            },
            "payload": payload,
        },
        ensure_ascii=False,
    )


class DoubaoTtsEngine:
    """Real conformer: opens one WebSocket per `synthesize()` call, matching
    Bella's event sequence being a single request/response cycle rather than
    a persistent session.
    """

    def __init__(
        self,
        api_key: str | None = None,
        ws_url: str = DEFAULT_URL,
        voice: str = DEFAULT_VOICE,
        *,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    ) -> None:
        self._api_key = api_key or os.environ["API_KEY"]
        self._ws_url = ws_url
        self._voice = voice
        self._sample_rate_hz = sample_rate_hz

    async def synthesize(self, text: str) -> SynthesizedAudio:
        chunks = [chunk.pcm16 async for chunk in self.synthesize_stream(text)]
        return SynthesizedAudio(pcm16=b"".join(chunks), sample_rate_hz=self._sample_rate_hz)

    async def synthesize_stream(self, text: str) -> AsyncIterator[SynthesizedAudioChunk]:
        task_id = uuid.uuid4().hex
        async with connect(
            self._ws_url,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
                "X-Api-Connect-Id": str(uuid.uuid4()),
            },
        ) as connection:
            await connection.send(
                _event(
                    task_id,
                    "StartSpeech",
                    {
                        "model": "doubao-seed-tts-2.0",
                        "voice": self._voice,
                        "format": "pcm",
                        "sample_rate": self._sample_rate_hz,
                        "channels": 1,
                        "encoding": "s16le",
                    },
                )
            )
            await self._wait_for(connection, "SpeechStarted")

            await connection.send(_event(task_id, "InputText", {"text": text}))
            await connection.send(_event(task_id, "FinishSpeech", {}))

            async for chunk in self._stream_audio(connection):
                yield chunk
            yield SynthesizedAudioChunk(pcm16=b"", sample_rate_hz=self._sample_rate_hz, is_final=True)

    async def _wait_for(self, connection: Any, event_name: str) -> None:
        async for raw in connection:
            if isinstance(raw, bytes):
                continue
            if json.loads(raw).get("header", {}).get("name") == event_name:
                return

    async def _stream_audio(self, connection: Any) -> AsyncIterator[SynthesizedAudioChunk]:
        async for raw in connection:
            if isinstance(raw, bytes):
                yield SynthesizedAudioChunk(pcm16=raw, sample_rate_hz=self._sample_rate_hz, is_final=False)
                continue
            event = json.loads(raw)
            name = event.get("header", {}).get("name", "")
            if name == "SpeechAudioDelta":
                encoded = event.get("payload", {}).get("audio") or event.get("payload", {}).get("data")
                if encoded:
                    yield SynthesizedAudioChunk(
                        pcm16=base64.b64decode(encoded),
                        sample_rate_hz=self._sample_rate_hz,
                        is_final=False,
                    )
            elif name in ("SpeechCompleted", "SpeechFinished"):
                return
            elif name == "SpeechFailed":
                raise DoubaoTtsError(str(event.get("payload", {})))
