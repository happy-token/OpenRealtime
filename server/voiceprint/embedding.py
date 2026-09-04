"""SpeakerEmbedder: turns raw PCM16 audio into a speaker-embedding vector.

See CONTEXT.md — Voiceprint, and ADR-0022. server/signals/voiceprint.py's
VoiceprintMatcher Protocol never had an audio-input method — matching.py's
EnrolledSpeakerVoiceprintMatcher is what finally needed one, and this is the
seam it embeds through. Unregistered/default behavior elsewhere is
unaffected: nothing here is wired into the Voice Session runtime by default.
"""

from __future__ import annotations

from typing import Protocol


class SpeakerEmbedder(Protocol):
    async def embed(self, pcm16: bytes, *, sample_rate_hz: int) -> list[float] | None: ...


class PreloadedSpeakerEmbedder:
    """Deterministic, no-network stand-in — mirrors PreloadedAsrEngine and
    EchoLlmClient elsewhere in this framework. Always returns the same fixed
    embedding (or None, to simulate an embedding failure), regardless of the
    audio it's given."""

    def __init__(self, embedding: list[float] | None) -> None:
        self._embedding = embedding

    async def embed(self, pcm16: bytes, *, sample_rate_hz: int) -> list[float] | None:
        del pcm16, sample_rate_hz  # unused by this conformer; part of the Protocol shape
        return self._embedding
