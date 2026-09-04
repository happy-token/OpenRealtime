"""Voiceprint enrollment: static (one recording, explicit) and adaptive
(the first N turns, no explicit enrollment step) profile creation.

See CONTEXT.md — Voiceprint, and ADR-0022.
"""

from __future__ import annotations

import asyncio
import uuid

from server.voiceprint.embedding import SpeakerEmbedder
from server.voiceprint.matching import VoiceprintProfile, VoiceprintRepository, cosine_distance


class VoiceprintEnrollmentError(RuntimeError):
    """Raised when an enrollment recording can't be embedded."""


async def enroll_recording(
    embedder: SpeakerEmbedder,
    pcm16: bytes,
    *,
    sample_rate_hz: int,
    display_name: str,
    repository: VoiceprintRepository,
    profile_id: str | None = None,
) -> VoiceprintProfile:
    """Static enrollment: embed one recording and activate it immediately.
    Unlike fail-open runtime plugins, this is an explicit,
    host-invoked action — an embedding failure here is reported rather than
    silently swallowed, so the host can retry or ask for another recording."""
    embedding = await embedder.embed(pcm16, sample_rate_hz=sample_rate_hz)
    if embedding is None:
        raise VoiceprintEnrollmentError("embedder returned no embedding for the enrollment recording")

    profile = VoiceprintProfile(
        profile_id=profile_id or uuid.uuid4().hex,
        display_name=display_name,
        centroid=embedding,
    )
    await repository.upsert_profile(profile)
    await repository.set_active_profile(profile.profile_id)
    return profile


def _audio_duration_ms(pcm16: bytes, sample_rate_hz: int) -> float:
    if sample_rate_hz <= 0:
        return 0.0
    return (len(pcm16) // 2 / sample_rate_hz) * 1000.0


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    length = len(vectors[0])
    sums = [0.0] * length
    for vector in vectors:
        for index, value in enumerate(vector):
            sums[index] += value
    return [total / len(vectors) for total in sums]


def _dominant_cluster_centroid(samples: list[tuple[list[float], float]]) -> list[float]:
    """Minimal pure-Python 2-means split, run to separate a single dominant
    speaker's samples from any incidental second-speaker audio captured
    during adaptive enrollment (e.g. a brief interjection from someone
    else). Keeps whichever cluster has the greater total captured duration.
    Falls back to averaging everything when there isn't enough data to
    split meaningfully."""
    embeddings = [embedding for embedding, _duration_ms in samples]
    if len(samples) < 4:
        return _mean_vector(embeddings)

    centroid_a, centroid_b = embeddings[0], embeddings[-1]
    assignment = [0] * len(samples)
    for _iteration in range(10):
        changed = False
        for index, embedding in enumerate(embeddings):
            distance_a = cosine_distance(embedding, centroid_a)
            distance_b = cosine_distance(embedding, centroid_b)
            new_assignment = 0 if distance_a <= distance_b else 1
            if new_assignment != assignment[index]:
                changed = True
            assignment[index] = new_assignment

        cluster_a = [embeddings[i] for i in range(len(samples)) if assignment[i] == 0]
        cluster_b = [embeddings[i] for i in range(len(samples)) if assignment[i] == 1]
        if not cluster_a or not cluster_b:
            return _mean_vector(embeddings)
        centroid_a = _mean_vector(cluster_a)
        centroid_b = _mean_vector(cluster_b)
        if not changed:
            break

    duration_a = sum(samples[i][1] for i in range(len(samples)) if assignment[i] == 0)
    duration_b = sum(samples[i][1] for i in range(len(samples)) if assignment[i] == 1)
    dominant = cluster_a if duration_a >= duration_b else cluster_b
    return _mean_vector(dominant)


class AdaptiveEnrollment:
    """Passive, opt-in speaker enrollment: capture the first `target_turns`
    turns' audio via `observe_turn`, embed each, split into (at most) two
    clusters, and activate the dominant one (by total captured duration) as
    the enrolled profile — no explicit "start enrollment" recording needed.

    Decoupled from any connection/session lifetime: a host application
    drives it by calling `observe_turn` once per completed turn (e.g. from
    its own per-turn audio capture), and activation runs as a background
    task once enough turns have been captured — mirroring voiceloop's own
    "decoupled from connection lifetime, activates at the next turn
    boundary" property without this needing a dependency on any
    transport/session object.
    """

    def __init__(
        self,
        embedder: SpeakerEmbedder,
        repository: VoiceprintRepository,
        *,
        display_name: str,
        target_turns: int = 5,
        profile_id: str | None = None,
    ) -> None:
        self._embedder = embedder
        self._repository = repository
        self._display_name = display_name
        self._target_turns = target_turns
        self._profile_id = profile_id or uuid.uuid4().hex
        self._samples: list[tuple[list[float], float]] = []
        self._activation_task: asyncio.Task[None] | None = None
        self._done = False

    @property
    def is_in_progress(self) -> bool:
        return not self._done

    async def observe_turn(self, pcm16: bytes, *, sample_rate_hz: int) -> None:
        if self._done:
            return
        embedding = await self._embedder.embed(pcm16, sample_rate_hz=sample_rate_hz)
        if embedding is None:
            return

        self._samples.append((embedding, _audio_duration_ms(pcm16, sample_rate_hz)))
        if len(self._samples) >= self._target_turns:
            self._done = True
            self._activation_task = asyncio.ensure_future(self._activate())

    async def _activate(self) -> None:
        centroid = _dominant_cluster_centroid(self._samples)
        profile = VoiceprintProfile(
            profile_id=self._profile_id, display_name=self._display_name, centroid=centroid
        )
        await self._repository.upsert_profile(profile)
        await self._repository.set_active_profile(profile.profile_id)

    async def wait_until_activated(self) -> None:
        """Test/host helper: block until the background activation task (if
        one has started) completes."""
        if self._activation_task is not None:
            await self._activation_task
