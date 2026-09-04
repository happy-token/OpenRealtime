"""Real Bella-gateway speaker-embedding conformer for the SpeakerEmbedder seam.

See CONTEXT.md — Voiceprint, and ADR-0022. Speaks the company-internal
Bella OpenAPI gateway's speaker-embedding
endpoint. Unlike speech/plugins/bella_asr.py (a persistent streaming
WebSocket session), a speaker embedding is a single request/response call
over one recording, so this follows web_search/plugins/byte_web_search.py's
pattern instead: stdlib urllib.request wrapped in asyncio.to_thread, no new
HTTP dependency.

The credential (`API_KEY`) is read from the environment and never logged or
printed — the same credential speech/plugins/bella_asr.py and
speech/doubao_tts.py already read.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import os
import urllib.error
import urllib.request
import wave

DEFAULT_URL = "https://bella-openapi.ke.com/v1/audio/speaker/embedding"


def _pcm16_to_wav(pcm16: bytes, *, sample_rate_hz: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(pcm16)
    return buffer.getvalue()


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


class BellaSpeakerEmbedder:
    """Real SpeakerEmbedder conformer. Never raises — any request, network,
    or response-shape failure yields `None`, matching
    PreloadedSpeakerEmbedder's "None means embedding failed" contract, so a
    gateway outage degrades EnrolledSpeakerVoiceprintMatcher to
    `"unavailable"` rather than taking down a turn."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self._api_key = api_key or os.environ["API_KEY"]
        self._base_url = base_url or DEFAULT_URL
        self._timeout_s = timeout_s

    async def embed(self, pcm16: bytes, *, sample_rate_hz: int) -> list[float] | None:
        return await asyncio.to_thread(self._embed_sync, pcm16, sample_rate_hz)

    def _embed_sync(self, pcm16: bytes, sample_rate_hz: int) -> list[float] | None:
        wav_bytes = _pcm16_to_wav(pcm16, sample_rate_hz=sample_rate_hz)
        request = urllib.request.Request(
            self._base_url,
            data=wav_bytes,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "audio/wav",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                parsed = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None

        embedding = parsed.get("embedding") if isinstance(parsed, dict) else None
        if not isinstance(embedding, list) or not embedding:
            return None
        try:
            values = [float(value) for value in embedding]
        except (TypeError, ValueError):
            return None
        return _l2_normalize(values)
