"""VoiceprintProfile matching: the real VoiceprintMatcher conformer.

See CONTEXT.md — Voiceprint, and ADR-0005/ADR-0022.
server/signals/voiceprint.py's VoiceprintMatcher Protocol and
NoVoiceprintMatching default stay exactly where they are — this module
supplies EnrolledSpeakerVoiceprintMatcher, the profile/repository types it
compares against, and the cosine-distance helper it uses to compare them.

`add_audio` buffers pcm16 per generation and, once enough audio has
accumulated, eagerly computes and caches a match result. This lets an opt-in
HookPoint middleware (see
signals/voiceprint_gate.py's VoiceprintGate) read a same-turn result
synchronously: HookPoint's Middleware Protocol is a sync
`__call__(value: str) -> str | None` with no `generation` parameter and no
`await`, so without this eager computation no result would exist for the gate
to read synchronously.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from server.core.turn_content import VoiceprintResult
from server.voiceprint.embedding import SpeakerEmbedder

DEFAULT_DISTANCE_THRESHOLD = 0.5
DEFAULT_MIN_AUDIO_MS = 300.0


@dataclass(frozen=True)
class VoiceprintProfile:
    profile_id: str
    display_name: str
    centroid: list[float]


def cosine_distance(a: list[float], b: list[float]) -> float:
    """1 - cosine similarity. Degenerate inputs (empty, mismatched length,
    or zero-norm) read as maximally distant (1.0) rather than raising —
    matching's caller already treats "no usable signal" as `unavailable`,
    not an error."""
    if not a or not b or len(a) != len(b):
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - (dot / (norm_a * norm_b))


class VoiceprintRepository(Protocol):
    async def get_active_profile(self) -> VoiceprintProfile | None: ...
    async def upsert_profile(self, profile: VoiceprintProfile) -> None: ...
    async def set_active_profile(self, profile_id: str) -> None: ...


class InMemoryVoiceprintRepository:
    """Default, in-process repository — no persistence, mirrors the other
    InMemory* defaults shipped elsewhere in this framework."""

    def __init__(self) -> None:
        self._profiles: dict[str, VoiceprintProfile] = {}
        self._active_profile_id: str | None = None

    async def get_active_profile(self) -> VoiceprintProfile | None:
        if self._active_profile_id is None:
            return None
        return self._profiles.get(self._active_profile_id)

    async def upsert_profile(self, profile: VoiceprintProfile) -> None:
        self._profiles[profile.profile_id] = profile

    async def set_active_profile(self, profile_id: str) -> None:
        if profile_id not in self._profiles:
            raise KeyError(profile_id)
        self._active_profile_id = profile_id


def _pcm16_duration_ms(pcm16: bytes, sample_rate_hz: int) -> float:
    if sample_rate_hz <= 0:
        return 0.0
    sample_count = len(pcm16) // 2
    return (sample_count / sample_rate_hz) * 1000.0


class EnrolledSpeakerVoiceprintMatcher:
    """Real VoiceprintMatcher conformer. Buffers audio per generation via
    `add_audio`, embeds it once `min_audio_ms` has accumulated, and compares
    (cosine distance) against the repository's active profile."""

    def __init__(
        self,
        embedder: SpeakerEmbedder,
        repository: VoiceprintRepository,
        *,
        distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
        min_audio_ms: float = DEFAULT_MIN_AUDIO_MS,
        enrollment_in_progress: Callable[[], bool] | None = None,
    ) -> None:
        self._embedder = embedder
        self._repository = repository
        self._distance_threshold = distance_threshold
        self._min_audio_ms = min_audio_ms
        self._enrollment_in_progress = enrollment_in_progress or (lambda: False)

        self._buffer = bytearray()
        self._buffer_ms = 0.0
        self._buffer_generation: int | None = None
        self._buffer_sample_rate_hz: int | None = None
        self._cached_result: tuple[int, VoiceprintResult] | None = None

    @property
    def last_result(self) -> tuple[int, VoiceprintResult] | None:
        """The most recently computed (generation, result) pair, if any —
        read by VoiceprintGate, which cannot itself await `match()`."""
        return self._cached_result

    async def add_audio(self, pcm16: bytes, *, sample_rate_hz: int, generation: int) -> None:
        if generation != self._buffer_generation:
            self._buffer = bytearray()
            self._buffer_ms = 0.0
            self._buffer_generation = generation
            self._cached_result = None
        self._buffer += pcm16
        self._buffer_sample_rate_hz = sample_rate_hz
        self._buffer_ms += _pcm16_duration_ms(pcm16, sample_rate_hz)

        if self._cached_result is None and self._buffer_ms >= self._min_audio_ms:
            result = await self._compute_result(bytes(self._buffer), sample_rate_hz)
            self._cached_result = (generation, result)

    async def match(self, *, generation: int) -> VoiceprintResult | None:
        if self._cached_result is not None and self._cached_result[0] == generation:
            return self._cached_result[1]
        if self._buffer_generation != generation or not self._buffer:
            return "unavailable"
        result = await self._compute_result(
            bytes(self._buffer), self._buffer_sample_rate_hz or 16000
        )
        self._cached_result = (generation, result)
        return result

    async def _compute_result(self, pcm16: bytes, sample_rate_hz: int) -> VoiceprintResult:
        if self._enrollment_in_progress():
            return "adaptive"
        profile = await self._repository.get_active_profile()
        if profile is None:
            return "unavailable"
        embedding = await self._embedder.embed(pcm16, sample_rate_hz=sample_rate_hz)
        if embedding is None:
            return "unavailable"
        distance = cosine_distance(embedding, profile.centroid)
        return "match" if distance <= self._distance_threshold else "no_match"
