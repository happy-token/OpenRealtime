"""Bounded dual-track recording; IO evidence only, never turn or playback authority."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import uuid
import wave
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal

from server.artifacts import ArtifactCreateRequest, ArtifactPhase, ArtifactStore
from server.conversation_journal import (
    ArtifactReferenceContent,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationJournal,
    ConversationVisibility,
    JournalScope,
    StructuredContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime.protocol.audio import AudioEncoding, AudioFrame

logger = logging.getLogger(__name__)

Direction = Literal["input", "sent"]


def recording_scope(context: InteractionContext) -> JournalScope:
    return JournalScope(
        context.tenant_id,
        context.user_id,
        f"{context.thread_id}::recording:{context.voice_session_id}",
    )


@dataclass(slots=True)
class _Segment:
    direction: Direction
    context: InteractionContext
    epoch: str
    speech_id: str | None
    stream_id: str
    sample_rate_hz: int
    channels: int
    start_sample: int
    captured_at: datetime
    discontinuity: bool
    frames: list[tuple[int, int, int]] = field(default_factory=list)
    chunks: list[bytes] = field(default_factory=list)
    size: int = 0
    samples: int = 0


class SessionAudioRecorder:
    """One bounded storage worker. Capture never awaits storage on the media path."""

    def __init__(
        self,
        *,
        context: InteractionContext,
        artifacts: ArtifactStore,
        journal: ConversationJournal,
        on_failure: Callable[[str], None],
        segment_bytes: int = 262144,
        max_buffered_bytes: int = 4194304,
        max_pending_segments: int = 8,
        max_segments: int = 4096,
        write_timeout_s: float = 3,
        storage_durable: bool = False,
        on_settled: Callable[[], None] | None = None,
    ) -> None:
        for value in (segment_bytes, max_buffered_bytes, max_pending_segments, max_segments):
            if type(value) is not int or value < 1:
                raise ValueError("recording budgets must be positive integers")
        if not math.isfinite(write_timeout_s) or write_timeout_s <= 0:
            raise ValueError("recording write timeout must be finite and positive")
        self._context = context
        self._artifacts = artifacts
        self._journal = journal
        self._on_failure = on_failure
        self._on_settled = on_settled
        self._storage_durable = storage_durable
        self._segment_bytes = segment_bytes
        self._max_bytes = max_buffered_bytes
        self._max_pending = max_pending_segments
        self._max_segments = max_segments
        self._timeout = write_timeout_s
        self._instance = uuid.uuid4().hex
        self._buffers: dict[Direction, _Segment] = {}
        self._jobs: deque[tuple[int, _Segment]] = deque()
        self._write_tasks: set[asyncio.Task[None]] = set()
        self._buffered_bytes = 0
        self._segments = 0
        self.completed_segments = 0
        self.failure: str | None = None
        self._closed = False
        self._wake = asyncio.Event()
        self._settled = asyncio.Event()
        self._worker = asyncio.create_task(
            self._run(), name=f"recording:{context.voice_session_id}"
        )
        self._worker.add_done_callback(self._worker_done)

    @property
    def settled(self) -> bool:
        return self._settled.is_set()

    @property
    def pending_writes(self) -> int:
        return len(self._write_tasks)

    def capture(
        self,
        direction: Direction,
        frame: AudioFrame,
        *,
        context: InteractionContext,
        epoch: str,
        speech_id: str | None = None,
    ) -> None:
        if self._closed or self.failure:
            return
        if (
            context.tenant_id,
            context.user_id,
            context.device_id,
            context.voice_session_id,
            context.thread_id,
        ) != (
            self._context.tenant_id,
            self._context.user_id,
            self._context.device_id,
            self._context.voice_session_id,
            self._context.thread_id,
        ):
            self._fail("identity_mismatch")
            return
        if (
            direction not in {"input", "sent"}
            or not epoch
            or len(epoch.encode()) > 512
            or len(frame.stream_id.encode()) > 512
            or speech_id is not None
            and len(speech_id.encode()) > 512
        ):
            self._fail("recording_identity_budget")
            return
        if (
            frame.encoding is not AudioEncoding.PCM_S16LE
            or type(frame.channels) is not int
            or frame.channels not in {1, 2}
            or type(frame.sample_rate_hz) is not int
            or not 1 <= frame.sample_rate_hz <= 192000
            or len(frame.data) % (2 * frame.channels)
            or len(frame.data) > min(self._segment_bytes, 262144)
        ):
            self._fail("recording_audio_format")
            return
        samples = len(frame.data) // (2 * frame.channels)
        if samples > frame.sample_rate_hz * 5:
            self._fail("recording_audio_format")
            return
        if any(
            type(value) is not int or not 0 <= value <= 2**53 - 1
            for value in (frame.sequence, frame.timestamp_us, frame.duration_us)
        ):
            self._fail("recording_audio_clock")
            return
        if frame.duration_us != round(samples * 1000000 / frame.sample_rate_hz):
            self._fail("recording_audio_clock")
            return
        if self._buffered_bytes + len(frame.data) > self._max_bytes:
            self._fail("recording_byte_budget")
            return
        start = (frame.timestamp_us * frame.sample_rate_hz + 500000) // 1000000
        if start + samples > 2**53 - 1:
            self._fail("recording_audio_clock")
            return
        segment = self._buffers.get(direction)
        same = segment is not None and (
            segment.context,
            segment.epoch,
            segment.speech_id,
            segment.stream_id,
            segment.sample_rate_hz,
            segment.channels,
        ) == (context, epoch, speech_id, frame.stream_id, frame.sample_rate_hz, frame.channels)
        contiguous = (
            same
            and segment is not None
            and segment.start_sample + segment.samples == start
            and (direction == "sent" or segment.frames[-1][0] + 1 == frame.sequence)
        )
        if segment is not None and (
            not contiguous
            or segment.size + len(frame.data) > self._segment_bytes
            or segment.samples + samples > frame.sample_rate_hz * 5
        ):
            self._flush(direction)
            if self.failure:
                return
            segment = None
        if segment is None:
            segment = _Segment(
                direction,
                context,
                epoch,
                speech_id,
                frame.stream_id,
                frame.sample_rate_hz,
                frame.channels,
                start,
                datetime.now(UTC),
                bool(same and not contiguous),
            )
            self._buffers[direction] = segment
        segment.chunks.append(bytes(frame.data))
        segment.frames.append((frame.sequence, start, samples))
        segment.size += len(frame.data)
        segment.samples += samples
        self._buffered_bytes += len(frame.data)
        if (
            segment.size >= self._segment_bytes
            or len(segment.frames) >= 256
            or segment.samples >= frame.sample_rate_hz * 5
        ):
            self._flush(direction)

    def _flush(self, direction: Direction) -> None:
        segment = self._buffers.pop(direction, None)
        if segment is None:
            return
        if (
            len(self._jobs) + len(self._write_tasks) >= self._max_pending
            or self._segments >= self._max_segments
        ):
            self._buffered_bytes -= segment.size
            self._fail("recording_segment_budget")
            return
        self._segments += 1
        self._jobs.append((self._segments, segment))
        self._wake.set()

    def _fail(self, reason: str) -> None:
        if self.failure is not None:
            return
        self.failure = reason
        for segment in self._buffers.values():
            self._buffered_bytes -= segment.size
        self._buffers.clear()
        self._wake.set()
        try:
            self._on_failure(reason)
        except (Exception, asyncio.CancelledError):  # noqa: BLE001 - isolate optional observers
            # A diagnostic observer cannot become a media-path failure.
            logger.warning("Recording failure observer raised")

    async def _run(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._jobs:
                    number, segment = self._jobs.popleft()
                    task = asyncio.create_task(
                        self._persist(number, segment),
                        name=f"recording-write:{self._context.voice_session_id}:{number}",
                    )
                    self._write_tasks.add(task)
                    task.add_done_callback(partial(self._written, segment=segment))
                    done, _ = await asyncio.wait((task,), timeout=self._timeout)
                    if not done:
                        self._fail("storage_timeout")
                        return
                    if task.cancelled() or task.exception() is not None:
                        self._fail("storage_write_failed")
                        return
                if self._closed or self.failure:
                    return
        finally:
            while self._jobs:
                _, segment = self._jobs.popleft()
                self._buffered_bytes -= segment.size

    async def _persist(self, number: int, segment: _Segment) -> None:
        encoded = io.BytesIO()
        with wave.open(encoded, "wb") as wav:
            wav.setnchannels(segment.channels)
            wav.setsampwidth(2)
            wav.setframerate(segment.sample_rate_hz)
            wav.writeframes(b"".join(segment.chunks))
        payload = encoded.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        request = ArtifactCreateRequest(
            tenant_id=self._context.tenant_id,
            owner_id=self._context.user_id,
            source_kind="voice_session_recording",
            source_id=self._context.voice_session_id,
            logical_name=f"{segment.direction}-{number}.wav",
            media_type="audio/wav",
            classification="restricted",
            idempotency_key=f"recording:{self._instance}:{number}",
            expected_size=len(payload),
            expected_sha256=digest,
            retention_until=segment.captured_at + timedelta(days=7),
        )
        record = await self._artifacts.create_staging(request)
        if record.request != request:
            raise ValueError("recording Artifact identity mismatch")
        artifact_id = record.artifact_id
        uploaded = await self._artifacts.upload(artifact_id, payload)
        if uploaded.artifact_id != artifact_id or uploaded.request != request:
            raise ValueError("recording upload identity mismatch")
        record = await self._artifacts.finalize(artifact_id)
        if (
            record.artifact_id != artifact_id
            or record.request != request
            or record.phase is not ArtifactPhase.AVAILABLE
            or record.receipt is None
            or record.receipt.size != len(payload)
            or record.receipt.sha256 != digest
        ):
            raise ValueError("recording Artifact verification failed")
        scope = recording_scope(self._context)
        manifest = {
            "type": "voice_recording.segment",
            "schema_version": 1,
            "voice_session_id": self._context.voice_session_id,
            "source_thread_id": self._context.thread_id,
            "direction": segment.direction,
            "epoch": segment.epoch,
            "speech_id": segment.speech_id,
            "stream_id": segment.stream_id,
            "artifact_id": record.artifact_id,
            "sample_rate_hz": segment.sample_rate_hz,
            "channels": segment.channels,
            "start_sample": segment.start_sample,
            "sample_count": segment.samples,
            "frames": segment.frames,
            "discontinuity": segment.discontinuity,
            "captured_at": segment.captured_at.isoformat(),
            "retention_until": (segment.captured_at + timedelta(days=7)).isoformat(),
            "storage_durable": self._storage_durable,
            "capture_boundary": "validated_input"
            if segment.direction == "input"
            else "transport_send_completed",
            "playback_confirmation": "not-inferred",
        }
        draft = ConversationItemDraft(
            item_id=f"recording:{self._instance}:{number}",
            context=replace(segment.context, thread_id=scope.thread_id),
            kind=ConversationItemKind.CORRECTION,
            status=ConversationItemStatus.COMPLETED,
            producer="voice-session-recording",
            visibility=frozenset({ConversationVisibility.INTERNAL}),
            occurred_at=segment.captured_at,
            content=(
                StructuredContent(manifest),
                ArtifactReferenceContent(record.artifact_id, "audio/wav", len(payload), digest),
            ),
        )
        result = await self._journal.append(draft)
        item = result.item
        if item.item_id != draft.item_id or item.item_digest != draft.item_digest:
            raise ValueError("recording manifest commit mismatch")

    def _written(self, task: asyncio.Task[None], segment: _Segment) -> None:
        self._write_tasks.discard(task)
        self._buffered_bytes -= segment.size
        if task.cancelled() or task.exception() is not None:
            self._fail("storage_write_failed")
        else:
            self.completed_segments += 1
        self._maybe_settled()

    def _worker_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled() or task.exception() is not None:
            self._fail("recording_worker_failed")
        self._maybe_settled()

    def _maybe_settled(self) -> None:
        if self._worker.done() and not self._write_tasks and not self._settled.is_set():
            self._settled.set()
            if self._on_settled:
                try:
                    self._on_settled()
                except (Exception, asyncio.CancelledError):  # noqa: BLE001 - isolate optional observers
                    logger.warning("Recording settlement observer raised")

    async def close(self, *, timeout_s: float = 1) -> bool:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("recording close timeout must be finite and positive")
        if not self._closed:
            if not self.failure:
                self._flush("input")
                self._flush("sent")
            self._closed = True
            self._wake.set()
        waiter = asyncio.create_task(self.wait_settled())
        try:
            done, _ = await asyncio.wait((waiter,), timeout=timeout_s)
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        if not done:
            self._fail("recording_close_timeout")
            return False
        return self.failure is None

    async def wait_settled(self) -> None:
        await self._settled.wait()
