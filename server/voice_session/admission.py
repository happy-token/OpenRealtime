"""Process-local capacity admission for live Cascaded Voice Sessions."""

from __future__ import annotations

import asyncio
import logging
import math
import resource
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from server.voice_session.models import VoiceSessionIdentity
from server.voice_session.runtime import VoiceSessionAdmissionRejected

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionCapacityLimits:
    max_active_sessions: int = 8
    max_asr_sessions: int = 8
    max_tts_sessions: int = 8
    max_event_loop_lag_ms: float = 200.0
    max_process_memory_bytes: int = 1_073_741_824
    max_audio_queue_bytes: int = 67_108_864
    audio_queue_reservation_bytes: int = 4_194_304
    retry_after_ms: int = 1_000

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_active_sessions,
            self.max_asr_sessions,
            self.max_tts_sessions,
            self.max_process_memory_bytes,
            self.max_audio_queue_bytes,
            self.audio_queue_reservation_bytes,
        )
        if any(value <= 0 for value in integer_limits):
            raise ValueError("Voice Session capacity limits must be positive")
        if not math.isfinite(self.max_event_loop_lag_ms) or self.max_event_loop_lag_ms <= 0:
            raise ValueError("Voice Session event-loop lag limit must be positive")
        if self.retry_after_ms < 0:
            raise ValueError("Voice Session retry delay must not be negative")
        if self.audio_queue_reservation_bytes > self.max_audio_queue_bytes:
            raise ValueError("audio queue reservation must fit within its capacity")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionResourceSnapshot:
    event_loop_lag_ms: float
    process_memory_bytes: int
    audio_queue_bytes: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.event_loop_lag_ms) or self.event_loop_lag_ms < 0:
            raise ValueError("event-loop lag must be finite and non-negative")
        if self.process_memory_bytes < 0 or self.audio_queue_bytes < 0:
            raise ValueError("resource usage must not be negative")


class VoiceSessionResourceProbe(Protocol):
    async def snapshot(self) -> VoiceSessionResourceSnapshot: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSessionAdmissionObservation:
    identity: VoiceSessionIdentity
    decision: Literal["accepted", "rejected", "released"]
    reasons: tuple[str, ...]
    active_sessions: int
    projected_sessions: int
    event_loop_lag_ms: float | None
    process_memory_bytes: int | None
    observed_audio_queue_bytes: int | None
    projected_audio_queue_bytes: int | None


class VoiceSessionAdmissionObserver(Protocol):
    def __call__(self, observation: VoiceSessionAdmissionObservation) -> None: ...


class ProcessVoiceSessionResourceProbe:
    """Read process pressure without retaining user media or transcript data."""

    def __init__(self, *, audio_queue_bytes: Callable[[], int] | None = None) -> None:
        self._audio_queue_bytes = audio_queue_bytes or (lambda: 0)

    async def snapshot(self) -> VoiceSessionResourceSnapshot:
        loop = asyncio.get_running_loop()
        before = loop.time()
        await asyncio.sleep(0)
        lag_ms = max(0.0, (loop.time() - before) * 1000)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux and most BSD consumers report KiB.
        process_memory_bytes = int(rss if sys.platform == "darwin" else rss * 1024)
        return VoiceSessionResourceSnapshot(
            event_loop_lag_ms=lag_ms,
            process_memory_bytes=process_memory_bytes,
            audio_queue_bytes=self._audio_queue_bytes(),
        )


class _LocalAdmissionLease:
    def __init__(
        self,
        controller: LocalVoiceSessionAdmissionController,
        lease_id: str,
        identity: VoiceSessionIdentity,
    ) -> None:
        self._controller = controller
        self._lease_id = lease_id
        self._identity = identity

    async def release(self) -> None:
        await self._controller._release(self._lease_id, self._identity)


class LocalVoiceSessionAdmissionController:
    """Reserve bounded process/provider/audio capacity with an idempotent lease."""

    def __init__(
        self,
        *,
        limits: VoiceSessionCapacityLimits | None = None,
        probe: VoiceSessionResourceProbe | None = None,
        observer: VoiceSessionAdmissionObserver | None = None,
    ) -> None:
        self._limits = limits or VoiceSessionCapacityLimits()
        self._probe = probe or ProcessVoiceSessionResourceProbe()
        self._observer = observer
        self._lock = asyncio.Lock()
        self._leases: set[str] = set()

    @property
    def active_sessions(self) -> int:
        return len(self._leases)

    async def acquire(self, identity: VoiceSessionIdentity) -> _LocalAdmissionLease:
        observed = await self._probe.snapshot()
        async with self._lock:
            projected_sessions = len(self._leases) + 1
            projected_audio_bytes = (
                observed.audio_queue_bytes
                + projected_sessions * self._limits.audio_queue_reservation_bytes
            )
            reasons = tuple(
                reason
                for reason, exhausted in (
                    (
                        "active_sessions",
                        projected_sessions > self._limits.max_active_sessions,
                    ),
                    ("asr_sessions", projected_sessions > self._limits.max_asr_sessions),
                    ("tts_sessions", projected_sessions > self._limits.max_tts_sessions),
                    (
                        "event_loop_lag",
                        observed.event_loop_lag_ms
                        > self._limits.max_event_loop_lag_ms,
                    ),
                    (
                        "process_memory",
                        observed.process_memory_bytes
                        > self._limits.max_process_memory_bytes,
                    ),
                    (
                        "audio_queue",
                        projected_audio_bytes > self._limits.max_audio_queue_bytes,
                    ),
                )
                if exhausted
            )
            if reasons:
                self._observe(
                    VoiceSessionAdmissionObservation(
                        identity=identity,
                        decision="rejected",
                        reasons=reasons,
                        active_sessions=len(self._leases),
                        projected_sessions=projected_sessions,
                        event_loop_lag_ms=observed.event_loop_lag_ms,
                        process_memory_bytes=observed.process_memory_bytes,
                        observed_audio_queue_bytes=observed.audio_queue_bytes,
                        projected_audio_queue_bytes=projected_audio_bytes,
                    )
                )
                raise VoiceSessionAdmissionRejected(
                    retry_after_ms=self._limits.retry_after_ms
                )
            lease_id = str(uuid.uuid4())
            self._leases.add(lease_id)
            self._observe(
                VoiceSessionAdmissionObservation(
                    identity=identity,
                    decision="accepted",
                    reasons=(),
                    active_sessions=len(self._leases),
                    projected_sessions=projected_sessions,
                    event_loop_lag_ms=observed.event_loop_lag_ms,
                    process_memory_bytes=observed.process_memory_bytes,
                    observed_audio_queue_bytes=observed.audio_queue_bytes,
                    projected_audio_queue_bytes=projected_audio_bytes,
                )
            )
        return _LocalAdmissionLease(self, lease_id, identity)

    async def _release(
        self,
        lease_id: str,
        identity: VoiceSessionIdentity,
    ) -> None:
        async with self._lock:
            if lease_id not in self._leases:
                return
            self._leases.remove(lease_id)
            self._observe(
                VoiceSessionAdmissionObservation(
                    identity=identity,
                    decision="released",
                    reasons=(),
                    active_sessions=len(self._leases),
                    projected_sessions=len(self._leases),
                    event_loop_lag_ms=None,
                    process_memory_bytes=None,
                    observed_audio_queue_bytes=None,
                    projected_audio_queue_bytes=None,
                )
            )

    def _observe(self, observation: VoiceSessionAdmissionObservation) -> None:
        if self._observer is None:
            return
        try:
            self._observer(observation)
        except Exception:
            logger.exception("Voice Session admission observer failed")
