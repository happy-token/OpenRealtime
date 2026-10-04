"""Non-blocking runtime telemetry and diagnostics query seam.

Call sites bind one :class:`TelemetryIdentity` and emit immutable records.
Persistence, batching, redaction, percentile calculation, and dashboard
projection remain behind this module's small interface so the realtime path
never waits for PostgreSQL or knows how diagnostics are queried.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from server.ledger.event_ledger import LedgerEvent
from server.observability.latency import LatencyMilestone, ResponseLatencyTrace

logger = logging.getLogger(__name__)
_TELEMETRY_GENERATION: ContextVar[int | None] = ContextVar(
    "voiceagent_telemetry_generation", default=None
)
_EXPECTED_INTERRUPTION_REASONS = frozenset(
    {"text_barge_in", "barge_in", "barge_in_floor_claim", "user_barge_in"}
)


@contextmanager
def telemetry_generation_scope(generation: int) -> Iterator[None]:
    """Correlate nested provider spans without shared mutable session state."""
    if generation < 0:
        raise ValueError("telemetry generation must be non-negative")
    token = _TELEMETRY_GENERATION.set(generation)
    try:
        yield
    finally:
        _TELEMETRY_GENERATION.reset(token)


class TelemetryKind(StrEnum):
    EVENT = "event"
    SPAN = "span"
    MILESTONE = "milestone"
    TERMINAL = "terminal"
    PROVIDER_CALL = "provider_call"


class TelemetryOutcome(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    DEGRADED = "degraded"
    NO_RESPONSE = "no_response"


class TelemetrySeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TelemetryIdentity:
    tenant_id: str
    user_id: str
    device_id: str
    voice_session_id: str
    thread_id: str

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.tenant_id,
                self.user_id,
                self.device_id,
                self.voice_session_id,
                self.thread_id,
            )
        ):
            raise ValueError("telemetry identity fields must be non-empty")


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    event_id: str
    sequence: int
    name: str
    kind: TelemetryKind
    outcome: TelemetryOutcome
    severity: TelemetrySeverity
    tenant_id: str
    user_id: str
    device_id: str
    voice_session_id: str
    thread_id: str
    generation: int | None
    turn_id: str | None
    response_id: str | None
    call_id: str | None
    worker_id: str | None
    occurred_at: datetime
    monotonic_ns: int
    duration_ms: float | None = None
    timeout_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["outcome"] = self.outcome.value
        payload["severity"] = self.severity.value
        payload["occurred_at"] = self.occurred_at.isoformat()
        return payload


@dataclass(slots=True)
class ProviderCallSpan:
    started_ns: int
    first_response_ns: int | None = None

    def mark_first_response(self) -> bool:
        if self.first_response_ns is not None:
            return False
        self.first_response_ns = time.monotonic_ns()
        return True

    @property
    def ttfb_ms(self) -> float | None:
        if self.first_response_ns is None:
            return None
        return (self.first_response_ns - self.started_ns) / 1_000_000


@dataclass(frozen=True, slots=True)
class DiagnosticsWindow:
    since: datetime
    until: datetime | None = None

    def __post_init__(self) -> None:
        if self.since.tzinfo is None:
            raise ValueError("diagnostics window must be timezone-aware")
        if self.until is not None:
            if self.until.tzinfo is None:
                raise ValueError("diagnostics window must be timezone-aware")
            if self.until < self.since:
                raise ValueError("diagnostics window cannot end before it starts")

    @classmethod
    def last(cls, duration: timedelta) -> DiagnosticsWindow:
        if duration <= timedelta(0):
            raise ValueError("diagnostics duration must be positive")
        return cls(since=datetime.now(UTC) - duration)

    def contains(self, occurred_at: datetime) -> bool:
        return occurred_at >= self.since and (
            self.until is None or occurred_at <= self.until
        )


@dataclass(frozen=True, slots=True)
class MetricAggregate:
    name: str
    sample_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    timeout_count: int
    error_count: int
    cancelled_count: int
    degraded_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DiagnosticsOverview:
    since: datetime
    until: datetime
    session_count: int
    turn_count: int
    successful_turn_count: int
    no_response_count: int
    timeout_count: int
    error_count: int
    cancelled_count: int
    interrupted_count: int
    degraded_count: int
    metrics: tuple[MetricAggregate, ...]
    capability_failures: tuple[dict[str, Any], ...] = ()

    @property
    def success_rate(self) -> float | None:
        eligible_turns = self.turn_count - self.interrupted_count
        return (
            None
            if eligible_turns == 0
            else self.successful_turn_count / eligible_turns
        )

    @property
    def no_response_rate(self) -> float | None:
        eligible_turns = self.turn_count - self.interrupted_count
        return None if eligible_turns == 0 else self.no_response_count / eligible_turns

    def to_dict(self) -> dict[str, Any]:
        return {
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "session_count": self.session_count,
            "turn_count": self.turn_count,
            "successful_turn_count": self.successful_turn_count,
            "success_rate": self.success_rate,
            "no_response_count": self.no_response_count,
            "no_response_rate": self.no_response_rate,
            "timeout_count": self.timeout_count,
            "error_count": self.error_count,
            "cancelled_count": self.cancelled_count,
            "interrupted_count": self.interrupted_count,
            "degraded_count": self.degraded_count,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "capability_failures": list(self.capability_failures),
        }


@dataclass(frozen=True, slots=True)
class SessionSummary:
    voice_session_id: str
    first_event_at: datetime
    last_event_at: datetime
    turn_count: int
    timeout_count: int
    error_count: int
    no_response_count: int
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["first_event_at"] = self.first_event_at.isoformat()
        payload["last_event_at"] = self.last_event_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class SessionDetail:
    summary: SessionSummary
    events: tuple[TelemetryRecord, ...]
    next_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_cursor": self.next_cursor,
            "summary": self.summary.to_dict(),
            "events": [event.to_dict() for event in self.events],
        }


class TelemetryWriter(Protocol):
    async def append_batch(self, records: Sequence[TelemetryRecord]) -> None: ...


@runtime_checkable
class DiagnosticsQuery(Protocol):
    async def overview(self, window: DiagnosticsWindow) -> DiagnosticsOverview: ...

    async def list_sessions(
        self,
        window: DiagnosticsWindow,
        *,
        limit: int = 50,
    ) -> tuple[SessionSummary, ...]: ...

    async def session_detail(self, voice_session_id: str, *, after_event_id: str | None = None) -> SessionDetail | None: ...


@runtime_checkable
class SessionTelemetryRetention(Protocol):
    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int: ...


class InMemoryTelemetryStore(TelemetryWriter, DiagnosticsQuery):
    """Deterministic adapter for local development and interface tests."""

    def __init__(self) -> None:
        self._records: list[TelemetryRecord] = []
        self._lock = asyncio.Lock()

    async def append_batch(self, records: Sequence[TelemetryRecord]) -> None:
        async with self._lock:
            self._records.extend(records)

    async def overview(self, window: DiagnosticsWindow) -> DiagnosticsOverview:
        records = await self._within(window)
        return _overview(records, window)

    async def list_sessions(
        self,
        window: DiagnosticsWindow,
        *,
        limit: int = 50,
    ) -> tuple[SessionSummary, ...]:
        if limit < 1:
            raise ValueError("session limit must be positive")
        records = await self._within(window)
        grouped: dict[str, list[TelemetryRecord]] = defaultdict(list)
        for record in records:
            grouped[record.voice_session_id].append(record)
        summaries = sorted(
            (_session_summary(session_records) for session_records in grouped.values()),
            key=lambda item: item.last_event_at,
            reverse=True,
        )
        return tuple(summaries[:limit])

    async def session_detail(self, voice_session_id: str, *, after_event_id: str | None = None) -> SessionDetail | None:
        if not voice_session_id:
            raise ValueError("voice_session_id must be non-empty")
        async with self._lock:
            records = tuple(
                record
                for record in self._records
                if record.voice_session_id == voice_session_id
            )
        if not records:
            return None
        ordered = tuple(
            sorted(
                records,
                key=lambda item: (
                    item.occurred_at,
                    item.monotonic_ns,
                    item.sequence,
                    item.event_id,
                ),
            )
        )
        start = 0
        if after_event_id is not None:
            matches = [index for index, record in enumerate(ordered) if record.event_id == after_event_id]
            if not matches:
                raise ValueError("unknown telemetry cursor")
            start = matches[0] + 1
        page = ordered[start:start + 5000]
        return SessionDetail(summary=_session_summary(ordered), events=page, next_cursor=page[-1].event_id if page and start + len(page) < len(ordered) else None)

    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int:
        selected = frozenset(voice_session_ids)
        if not selected:
            return 0
        async with self._lock:
            existing = {
                record.voice_session_id
                for record in self._records
                if record.voice_session_id in selected
            }
            self._records = [
                record
                for record in self._records
                if record.voice_session_id not in selected
            ]
        return len(existing)

    async def _within(self, window: DiagnosticsWindow) -> tuple[TelemetryRecord, ...]:
        async with self._lock:
            return tuple(record for record in self._records if window.contains(record.occurred_at))


class _Flush:
    def __init__(self, future: asyncio.Future[None]) -> None:
        self.future = future


class _Stop:
    pass


_QueueItem = TelemetryRecord | _Flush | _Stop


class RuntimeTelemetry:
    """Non-blocking write interface with one ordered background batch writer."""

    def __init__(
        self,
        store: TelemetryWriter,
        *,
        batch_size: int = 64,
        flush_interval_s: float = 0.25,
        max_queue_size: int = 10_000,
    ) -> None:
        if batch_size < 1:
            raise ValueError("telemetry batch_size must be positive")
        if flush_interval_s <= 0:
            raise ValueError("telemetry flush_interval_s must be positive")
        if max_queue_size < 1:
            raise ValueError("telemetry max_queue_size must be positive")
        self._store = store
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._writer_task: asyncio.Task[None] | None = None
        self._closed = False
        self._last_error: str | None = None
        self._pending_events = 0
        self._last_successful_write_at: str | None = None
        self._dropped_records = 0

    def collection_health(self) -> dict[str, Any]:
        return {
            "status": "degraded" if self._last_error or self._dropped_records else "ok",
            "storage_backend": "postgres" if type(self._store).__name__.startswith("Postgres") else "memory",
            "write_error": self._last_error is not None,
            "pending_events": self._pending_events,
            "dropped_events": self._dropped_records,
            "last_successful_write_at": self._last_successful_write_at,
        }

    @property
    def diagnostics(self) -> DiagnosticsQuery:
        if not isinstance(self._store, DiagnosticsQuery):
            raise TypeError("configured telemetry store does not support diagnostics queries")
        return self._store

    @property
    def pending_records(self) -> int:
        return self._queue.qsize()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def dropped_records(self) -> int:
        return self._dropped_records

    @property
    def supports_session_deletion(self) -> bool:
        return isinstance(self._store, SessionTelemetryRetention)

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("runtime telemetry is closed")
        if self._writer_task is None:
            self._writer_task = asyncio.create_task(
                self._run_writer(),
                name="runtime-telemetry-writer",
            )

    def bind(self, identity: TelemetryIdentity) -> SessionTelemetry:
        if self._closed:
            raise RuntimeError("runtime telemetry is closed")
        return SessionTelemetry(self, identity)

    def _enqueue(self, record: TelemetryRecord) -> None:
        if self._closed:
            return
        if self._writer_task is None:
            raise RuntimeError("runtime telemetry must be started before recording")
        try:
            self._queue.put_nowait(record)
            self._pending_events += 1
        except asyncio.QueueFull:
            self._dropped_records += 1
            if self._dropped_records == 1 or not (
                self._dropped_records & (self._dropped_records - 1)
            ):
                logger.error(
                    "runtime telemetry queue full; dropped_records=%d",
                    self._dropped_records,
                )

    async def flush(self) -> None:
        if self._writer_task is None:
            return
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(_Flush(future))
        await future

    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int:
        await self.flush()
        if not isinstance(self._store, SessionTelemetryRetention):
            raise TypeError("configured telemetry store does not support session deletion")
        return await self._store.delete_sessions(voice_session_ids)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        task, self._writer_task = self._writer_task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(self._queue.put(_Stop()), timeout=2.0)
        except TimeoutError:
            logger.error("runtime telemetry queue did not accept shutdown within 2 seconds")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            logger.error("runtime telemetry writer did not stop within 2 seconds")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run_writer(self) -> None:
        batch: list[TelemetryRecord] = []

        async def persist() -> None:
            if not batch:
                return
            pending = tuple(batch)
            try:
                await self._store.append_batch(pending)
            except Exception as error:
                self._last_error = f"{type(error).__name__}: {error}"
                logger.exception("runtime telemetry batch write failed")
                raise
            else:
                self._last_error = None
                self._pending_events -= len(pending)
                self._last_successful_write_at = datetime.now(UTC).isoformat()
                batch.clear()

        while True:
            if len(batch) >= self._batch_size:
                try:
                    await persist()
                except Exception:  # noqa: BLE001 - retry the isolated telemetry writer
                    await asyncio.sleep(min(self._flush_interval_s, 1.0))
                    continue
            try:
                item = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._flush_interval_s,
                )
            except TimeoutError:
                try:
                    await persist()
                except Exception:  # noqa: BLE001 - retry the isolated telemetry writer
                    await asyncio.sleep(min(self._flush_interval_s, 1.0))
                continue

            if isinstance(item, TelemetryRecord):
                batch.append(item)
                if len(batch) >= self._batch_size:
                    try:
                        await persist()
                    except Exception:  # noqa: BLE001 - retry the isolated telemetry writer
                        await asyncio.sleep(min(self._flush_interval_s, 1.0))
                continue
            if isinstance(item, _Flush):
                try:
                    await persist()
                except Exception as error:  # noqa: BLE001 - report flush failure to caller
                    if not item.future.done():
                        item.future.set_exception(error)
                else:
                    if not item.future.done():
                        item.future.set_result(None)
                continue
            try:
                await persist()
            except Exception:  # noqa: BLE001 - shutdown cannot fail the voice runtime
                logger.error("runtime telemetry closed with unpersisted records")
            return


class SessionTelemetry:
    """Session-bound facade; callers never construct storage records."""

    def __init__(self, runtime: RuntimeTelemetry, identity: TelemetryIdentity) -> None:
        self._runtime = runtime
        self.identity = identity
        self._sequence = 0
        self._anchors: dict[int, dict[str, int]] = defaultdict(dict)
        self._latest_generation: int | None = None

    def record(
        self,
        name: str,
        *,
        generation: int | None = None,
        kind: TelemetryKind = TelemetryKind.EVENT,
        outcome: TelemetryOutcome = TelemetryOutcome.OK,
        severity: TelemetrySeverity | None = None,
        duration_ms: float | None = None,
        timeout_ms: float | None = None,
        turn_id: str | None = None,
        response_id: str | None = None,
        call_id: str | None = None,
        worker_id: str | None = None,
        error: BaseException | str | None = None,
        attributes: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
        monotonic_ns: int | None = None,
    ) -> TelemetryRecord:
        if not name:
            raise ValueError("telemetry record name must be non-empty")
        if generation is None:
            generation = _TELEMETRY_GENERATION.get()
        if generation is not None and generation < 0:
            raise ValueError("telemetry generation must be non-negative")
        if generation is not None:
            self._latest_generation = generation
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("telemetry duration_ms must be non-negative")
        if timeout_ms is not None and timeout_ms < 0:
            raise ValueError("telemetry timeout_ms must be non-negative")
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("telemetry occurred_at must be timezone-aware")
        self._sequence += 1
        error_type, error_message = _normalize_error(error)
        resolved_severity = severity or _severity_for(outcome)
        record = TelemetryRecord(
            event_id=str(uuid.uuid4()),
            sequence=self._sequence,
            name=name,
            kind=kind,
            outcome=outcome,
            severity=resolved_severity,
            tenant_id=self.identity.tenant_id,
            user_id=self.identity.user_id,
            device_id=self.identity.device_id,
            voice_session_id=self.identity.voice_session_id,
            thread_id=self.identity.thread_id,
            generation=generation,
            turn_id=turn_id,
            response_id=response_id,
            call_id=call_id,
            worker_id=worker_id,
            occurred_at=timestamp,
            monotonic_ns=(
                monotonic_ns if monotonic_ns is not None else time.monotonic_ns()
            ),
            duration_ms=float(duration_ms) if duration_ms is not None else None,
            timeout_ms=float(timeout_ms) if timeout_ms is not None else None,
            error_type=error_type,
            error_message=error_message,
            attributes=redact_attributes(attributes or {}),
        )
        self._runtime._enqueue(record)
        return record

    @asynccontextmanager
    async def provider_call(
        self,
        *,
        provider: str,
        operation: str,
        model: str | None = None,
        timeout_ms: float | None = None,
        generation: int | None = None,
        attempt: int = 1,
        attributes: Mapping[str, Any] | None = None,
    ):
        if not provider or not operation:
            raise ValueError("provider and operation must be non-empty")
        if attempt < 1:
            raise ValueError("provider attempt must be positive")
        scoped_generation = _TELEMETRY_GENERATION.get()
        resolved_generation = (
            generation
            if generation is not None
            else scoped_generation
            if scoped_generation is not None
            else self._latest_generation
        )
        started_ns = time.monotonic_ns()
        span = ProviderCallSpan(started_ns=started_ns)
        outcome = TelemetryOutcome.OK
        error: BaseException | None = None
        try:
            yield span
        except asyncio.CancelledError as caught:
            outcome = TelemetryOutcome.CANCELLED
            error = caught
            raise
        except TimeoutError as caught:
            outcome = TelemetryOutcome.TIMEOUT
            error = caught
            raise
        except Exception as caught:
            outcome = _provider_error_outcome(caught)
            error = caught
            raise
        finally:
            ended_ns = time.monotonic_ns()
            details = dict(attributes or {})
            details.update(
                {
                    "provider": provider,
                    "operation": operation,
                    "model": model,
                    "attempt": attempt,
                    "ttfb_ms": span.ttfb_ms,
                }
            )
            self.record(
                f"provider.{_metric_segment(provider)}.{_metric_segment(operation)}",
                generation=resolved_generation,
                kind=TelemetryKind.PROVIDER_CALL,
                outcome=outcome,
                duration_ms=(ended_ns - started_ns) / 1_000_000,
                timeout_ms=timeout_ms,
                error=error,
                attributes=details,
                monotonic_ns=ended_ns,
            )

    def turn_terminal(
        self,
        generation: int,
        *,
        outcome: TelemetryOutcome,
        duration_ms: float | None = None,
        turn_id: str | None = None,
        response_id: str | None = None,
        error: BaseException | str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TelemetryRecord:
        return self.record(
            "turn.total",
            generation=generation,
            kind=TelemetryKind.TERMINAL,
            outcome=outcome,
            duration_ms=duration_ms,
            turn_id=turn_id,
            response_id=response_id,
            error=error,
            attributes=attributes,
        )

    async def observe_ledger(self, event: LedgerEvent) -> None:
        """Adapt one Event Ledger fact without awaiting telemetry storage."""

        payload = dict(event.payload)
        monotonic_ns = int(payload.pop("_monotonic_ns", time.monotonic_ns()))
        if event.name == "stage_span":
            stage = str(payload.pop("stage", "unknown"))
            raw_outcome = str(payload.pop("status", TelemetryOutcome.OK.value))
            error = payload.pop("error", None)
            duration_ms = payload.pop("duration_ms", None)
            timeout_ms = payload.pop("timeout_ms", None)
            self.record(
                stage,
                generation=event.generation,
                kind=TelemetryKind.SPAN,
                outcome=_outcome_from_value(raw_outcome),
                duration_ms=duration_ms,
                timeout_ms=timeout_ms,
                error=error,
                attributes=payload,
                monotonic_ns=monotonic_ns,
            )
            return

        outcome = _ledger_outcome(event.name, payload)
        error = payload.pop("error", None)
        duration_ms = payload.pop("duration_ms", None)
        timeout_ms = payload.pop("timeout_ms", None)
        self.record(
            event.name,
            generation=event.generation,
            kind=(TelemetryKind.SPAN if duration_ms is not None else TelemetryKind.EVENT),
            outcome=outcome,
            duration_ms=duration_ms,
            timeout_ms=timeout_ms,
            error=error,
            attributes=payload,
            monotonic_ns=monotonic_ns,
        )
        self._capture_ledger_timing(event.name, event.generation, monotonic_ns)

    def observe_latency(self, trace: ResponseLatencyTrace) -> None:
        """Subscribe once and project milestones into stable named metrics."""

        trace.subscribe(self._record_latency_milestone)

    def _record_latency_milestone(
        self,
        trace: ResponseLatencyTrace,
        milestone: LatencyMilestone,
        at: float,
    ) -> None:
        self.record(
            f"engine.{milestone.value}",
            generation=trace.generation,
            kind=TelemetryKind.MILESTONE,
            response_id=trace.response_id,
            monotonic_ns=round(at * 1_000_000_000),
        )
        projection = _LATENCY_PROJECTIONS.get(milestone)
        if projection is None:
            return
        anchor, metric_name = projection
        duration_ms = trace.duration_ms(anchor, milestone)
        if duration_ms is None:
            return
        self.record(
            metric_name,
            generation=trace.generation,
            kind=TelemetryKind.SPAN,
            duration_ms=duration_ms,
            response_id=trace.response_id,
            monotonic_ns=round(at * 1_000_000_000),
            attributes={"start": anchor.value, "end": milestone.value},
        )
        if trace.generation is None:
            return
        endpoint_metric = _ENDPOINT_LATENCY_PROJECTIONS.get(milestone)
        if endpoint_metric is not None:
            self._record_from_anchor(
                endpoint_metric,
                generation=trace.generation,
                anchor="endpoint_candidate",
                ended_ns=round(at * 1_000_000_000),
                response_id=trace.response_id,
            )

    def _capture_ledger_timing(
        self,
        name: str,
        generation: int,
        monotonic_ns: int,
    ) -> None:
        anchors = self._anchors[generation]
        if name == "user_speech_started":
            anchors["user_speech_started"] = monotonic_ns
            return
        if name == "endpoint_candidate_started":
            anchors["endpoint_candidate"] = monotonic_ns
            if "vad_endpoint_confirmed" in anchors:
                self._record_from_anchor(
                    "asr.final_tail",
                    generation=generation,
                    anchor="vad_endpoint_confirmed",
                    ended_ns=monotonic_ns,
                )
            return
        if name == "vad_endpoint_confirmed":
            anchors["vad_endpoint_confirmed"] = monotonic_ns
            endpoint_ns = anchors.get("endpoint_candidate")
            if endpoint_ns is not None and endpoint_ns <= monotonic_ns:
                self.record(
                    "asr.final_tail",
                    generation=generation,
                    kind=TelemetryKind.SPAN,
                    duration_ms=0,
                    monotonic_ns=monotonic_ns,
                    attributes={"final_before_vad": True},
                )
            return
        if name == "asr_partial":
            if "asr_first_partial" not in anchors:
                anchors["asr_first_partial"] = monotonic_ns
                self._record_from_anchor(
                    "asr.time_to_first_partial",
                    generation=generation,
                    anchor="user_speech_started",
                    ended_ns=monotonic_ns,
                )
            return
        if name == "endpoint_committed":
            self._record_from_anchor(
                "endpoint.commit_wait",
                generation=generation,
                anchor="endpoint_candidate",
                ended_ns=monotonic_ns,
            )
            self._record_from_anchor(
                "turn.speech_to_endpoint_commit",
                generation=generation,
                anchor="user_speech_started",
                ended_ns=monotonic_ns,
            )
            anchors["endpoint_committed"] = monotonic_ns
            return
        if name == "client_playback_started":
            anchors["client_playback_started"] = monotonic_ns
            self._record_from_anchor(
                "turn.endpoint_to_client_playback",
                generation=generation,
                anchor="endpoint_candidate",
                ended_ns=monotonic_ns,
            )
            return
        if name == "client_playback_finished":
            self._record_from_anchor(
                "client.playback_duration",
                generation=generation,
                anchor="client_playback_started",
                ended_ns=monotonic_ns,
            )
            return
        if name == "barge_in_confirmed":
            anchors["barge_in_confirmed"] = monotonic_ns
            return
        if name == "assistant_speech_cancelled":
            self._record_from_anchor(
                "barge_in.time_to_cancel_sent",
                generation=generation,
                anchor="barge_in_confirmed",
                ended_ns=monotonic_ns,
            )
            return
        if name == "client_playback_stopped":
            self._record_from_anchor(
                "barge_in.time_to_client_stop",
                generation=generation,
                anchor="barge_in_confirmed",
                ended_ns=monotonic_ns,
            )

    def _record_from_anchor(
        self,
        metric_name: str,
        *,
        generation: int,
        anchor: str,
        ended_ns: int,
        response_id: str | None = None,
    ) -> None:
        started_ns = self._anchors[generation].get(anchor)
        if started_ns is None or ended_ns < started_ns:
            return
        self.record(
            metric_name,
            generation=generation,
            kind=TelemetryKind.SPAN,
            duration_ms=(ended_ns - started_ns) / 1_000_000,
            response_id=response_id,
            monotonic_ns=ended_ns,
            attributes={"anchor": anchor},
        )


@dataclass(frozen=True, slots=True)
class DebugLogEntry:
    """One human-readable troubleshooting fact for a voice session.

    Separate from :class:`TelemetryRecord`: this is a narrative ("EOT=complete
    via llm_eot_classifier") for an operator or an AI diagnosing one session,
    not a numeric sample destined for percentile aggregation. The two stores
    fail independently — a debug-log write failure must never affect latency
    telemetry, and vice versa.
    """

    event_id: str
    voice_session_id: str
    sequence: int
    stage: str
    event: str
    summary: str
    occurred_at: datetime
    generation: int | None = None
    turn_id: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.voice_session_id or not self.stage or not self.event or not self.summary:
            raise ValueError("debug log entry identity and summary must be non-empty")
        if self.sequence < 1:
            raise ValueError("debug log sequence must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("debug log occurred_at must be timezone-aware")
        if self.generation is not None and self.generation < 0:
            raise ValueError("debug log generation must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "voice_session_id": self.voice_session_id,
            "sequence": self.sequence,
            "stage": self.stage,
            "event": self.event,
            "summary": self.summary,
            "occurred_at": self.occurred_at.isoformat(),
            "generation": self.generation,
            "turn_id": self.turn_id,
            "detail": dict(self.detail),
        }


class DebugLogWriter(Protocol):
    async def append_batch(self, entries: Sequence[DebugLogEntry]) -> None: ...


@runtime_checkable
class DebugLogQuery(Protocol):
    async def session_timeline(
        self, voice_session_id: str, *, limit: int = 2000, after_event_id: str | None = None
    ) -> tuple[DebugLogEntry, ...]: ...


@runtime_checkable
class DebugLogRetention(Protocol):
    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int: ...


class InMemoryDebugLogStore(DebugLogWriter, DebugLogQuery):
    """Deterministic adapter for local development and interface tests."""

    def __init__(self) -> None:
        self._entries: list[DebugLogEntry] = []
        self._lock = asyncio.Lock()

    async def append_batch(self, entries: Sequence[DebugLogEntry]) -> None:
        async with self._lock:
            self._entries.extend(entries)

    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int:
        selected = set(voice_session_ids)
        async with self._lock:
            deleted = {entry.voice_session_id for entry in self._entries if entry.voice_session_id in selected}
            self._entries = [entry for entry in self._entries if entry.voice_session_id not in selected]
        return len(deleted)

    async def session_timeline(
        self, voice_session_id: str, *, limit: int = 2000, after_event_id: str | None = None
    ) -> tuple[DebugLogEntry, ...]:
        if not voice_session_id:
            raise ValueError("voice_session_id must be non-empty")
        if limit < 1:
            raise ValueError("debug log limit must be positive")
        async with self._lock:
            matched = tuple(
                entry
                for entry in self._entries
                if entry.voice_session_id == voice_session_id
            )
        ordered = sorted(matched, key=lambda entry: (entry.sequence, entry.event_id))
        if after_event_id is not None:
            matches = [index for index, entry in enumerate(ordered) if entry.event_id == after_event_id]
            if not matches:
                raise ValueError("unknown debug log cursor")
            ordered = ordered[matches[0] + 1:]
        return ordered[:limit]


class _DebugLogFlush:
    def __init__(self, future: asyncio.Future[None]) -> None:
        self.future = future


class _DebugLogStop:
    pass


_DebugLogQueueItem = DebugLogEntry | _DebugLogFlush | _DebugLogStop


class RuntimeDebugLog:
    """Non-blocking write interface with its own ordered background writer.

    Deliberately does not share a queue, batch size, or writer task with
    :class:`RuntimeTelemetry` — the two subsystems answer different
    questions (what happened vs. how long did it take) and must not be able
    to back-pressure or fail each other.
    """

    def __init__(
        self,
        store: DebugLogWriter,
        *,
        batch_size: int = 64,
        flush_interval_s: float = 0.25,
        max_queue_size: int = 10_000,
    ) -> None:
        if batch_size < 1:
            raise ValueError("debug log batch_size must be positive")
        if flush_interval_s <= 0:
            raise ValueError("debug log flush_interval_s must be positive")
        if max_queue_size < 1:
            raise ValueError("debug log max_queue_size must be positive")
        self._store = store
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._queue: asyncio.Queue[_DebugLogQueueItem] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._writer_task: asyncio.Task[None] | None = None
        self._closed = False
        self._last_error: str | None = None
        self._pending_events = 0
        self._last_successful_write_at: str | None = None
        self._dropped_entries = 0

    def collection_health(self) -> dict[str, Any]:
        return {
            "status": "degraded" if self._last_error or self._dropped_entries else "ok",
            "storage_backend": "postgres" if type(self._store).__name__.startswith("Postgres") else "memory",
            "write_error": self._last_error is not None,
            "pending_events": self._pending_events,
            "dropped_events": self._dropped_entries,
            "last_successful_write_at": self._last_successful_write_at,
        }

    @property
    def query(self) -> DebugLogQuery:
        if not isinstance(self._store, DebugLogQuery):
            raise TypeError("configured debug log store does not support queries")
        return self._store

    @property
    def supports_session_deletion(self) -> bool:
        return isinstance(self._store, DebugLogRetention)

    async def delete_sessions(self, voice_session_ids: Sequence[str]) -> int:
        if not isinstance(self._store, DebugLogRetention):
            raise TypeError("configured debug log store does not support deletion")
        await self.flush()
        return await self._store.delete_sessions(voice_session_ids)

    @property
    def pending_entries(self) -> int:
        return self._queue.qsize()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def dropped_entries(self) -> int:
        return self._dropped_entries

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("runtime debug log is closed")
        if self._writer_task is None:
            self._writer_task = asyncio.create_task(
                self._run_writer(),
                name="runtime-debug-log-writer",
            )

    def bind(self, voice_session_id: str) -> SessionDebugLog:
        if self._closed:
            raise RuntimeError("runtime debug log is closed")
        return SessionDebugLog(self, voice_session_id)

    def _enqueue(self, entry: DebugLogEntry) -> None:
        if self._closed:
            return
        if self._writer_task is None:
            raise RuntimeError("runtime debug log must be started before logging")
        try:
            self._queue.put_nowait(entry)
            self._pending_events += 1
        except asyncio.QueueFull:
            self._dropped_entries += 1
            if self._dropped_entries == 1 or not (
                self._dropped_entries & (self._dropped_entries - 1)
            ):
                logger.error(
                    "runtime debug log queue full; dropped_entries=%d",
                    self._dropped_entries,
                )

    async def flush(self) -> None:
        if self._writer_task is None:
            return
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(_DebugLogFlush(future))
        await future

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        task, self._writer_task = self._writer_task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(self._queue.put(_DebugLogStop()), timeout=2.0)
        except TimeoutError:
            logger.error("runtime debug log queue did not accept shutdown within 2 seconds")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError:
            logger.error("runtime debug log writer did not stop within 2 seconds")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run_writer(self) -> None:
        batch: list[DebugLogEntry] = []

        async def persist() -> None:
            if not batch:
                return
            pending = tuple(batch)
            try:
                await self._store.append_batch(pending)
            except Exception as error:
                self._last_error = f"{type(error).__name__}: {error}"
                logger.exception("runtime debug log batch write failed")
                raise
            else:
                self._last_error = None
                self._pending_events -= len(pending)
                self._last_successful_write_at = datetime.now(UTC).isoformat()
                batch.clear()

        while True:
            if len(batch) >= self._batch_size:
                try:
                    await persist()
                except Exception:  # noqa: BLE001 - retry the isolated writer
                    await asyncio.sleep(min(self._flush_interval_s, 1.0))
                    continue
            try:
                item = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._flush_interval_s,
                )
            except TimeoutError:
                try:
                    await persist()
                except Exception:  # noqa: BLE001 - retry the isolated writer
                    await asyncio.sleep(min(self._flush_interval_s, 1.0))
                continue

            if isinstance(item, DebugLogEntry):
                batch.append(item)
                if len(batch) >= self._batch_size:
                    try:
                        await persist()
                    except Exception:  # noqa: BLE001 - retry the isolated writer
                        await asyncio.sleep(min(self._flush_interval_s, 1.0))
                continue
            if isinstance(item, _DebugLogFlush):
                try:
                    await persist()
                except Exception as error:  # noqa: BLE001 - report flush failure to caller
                    if not item.future.done():
                        item.future.set_exception(error)
                else:
                    if not item.future.done():
                        item.future.set_result(None)
                continue
            try:
                await persist()
            except Exception:  # noqa: BLE001 - shutdown cannot fail the voice runtime
                logger.error("runtime debug log closed with unpersisted entries")
            return


class SessionDebugLog:
    """Session-bound facade; callers never construct storage entries."""

    def __init__(self, runtime: RuntimeDebugLog, voice_session_id: str) -> None:
        if not voice_session_id:
            raise ValueError("voice_session_id must be non-empty")
        self._runtime = runtime
        self._voice_session_id = voice_session_id
        self._sequence = 0

    def log(
        self,
        stage: str,
        event: str,
        summary: str,
        *,
        generation: int | None = None,
        turn_id: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> DebugLogEntry:
        self._sequence += 1
        entry = DebugLogEntry(
            event_id=str(uuid.uuid4()),
            voice_session_id=self._voice_session_id,
            sequence=self._sequence,
            stage=stage,
            event=event,
            summary=summary,
            occurred_at=datetime.now(UTC),
            generation=generation,
            turn_id=turn_id,
            detail=redact_attributes(detail or {}),
        )
        self._runtime._enqueue(entry)
        return entry


_SENSITIVE_ATTRIBUTE_MARKERS = (
    "api_key",
    "authorization",
    "credential",
    "access_token",
    "refresh_token",
    "secret",
    "pcm",
    "audio_bytes",
    "audio_base64",
    "raw_audio",
)
_SENSITIVE_ATTRIBUTE_NAMES = {"token"}
_TEXT_ATTRIBUTE_NAMES = {"text", "transcript", "prompt", "response"}

_LATENCY_PROJECTIONS = {
    LatencyMilestone.FIRST_TEXT_DELTA: (
        LatencyMilestone.TURN_ACCEPTED,
        "engine.time_to_first_text",
    ),
    LatencyMilestone.FIRST_SPEAKABLE_SEGMENT: (
        LatencyMilestone.TURN_ACCEPTED,
        "engine.time_to_first_speakable",
    ),
    LatencyMilestone.TTS_FIRST_AUDIO: (
        LatencyMilestone.TTS_REQUESTED,
        "tts.time_to_first_audio",
    ),
    LatencyMilestone.FIRST_AUDIO_DELTA: (
        LatencyMilestone.TURN_ACCEPTED,
        "engine.time_to_first_audio",
    ),
    LatencyMilestone.FIRST_AUDIO_SENT: (
        LatencyMilestone.TURN_ACCEPTED,
        "turn.time_to_first_audio_sent",
    ),
    LatencyMilestone.PLAYBACK_STOPPED: (
        LatencyMilestone.BARGE_IN_CONFIRMED,
        "barge_in.time_to_playback_stop",
    ),
    LatencyMilestone.RESPONSE_TERMINAL: (
        LatencyMilestone.TURN_ACCEPTED,
        "engine.total",
    ),
}

_ENDPOINT_LATENCY_PROJECTIONS = {
    LatencyMilestone.FIRST_TEXT_DELTA: "turn.endpoint_to_first_text",
    LatencyMilestone.FIRST_AUDIO_DELTA: "turn.endpoint_to_first_audio",
}


def redact_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Return log-safe, JSON-safe structured metadata."""

    redacted: dict[str, Any] = {}
    for key, value in attributes.items():
        normalized = key.lower()
        if normalized in _SENSITIVE_ATTRIBUTE_NAMES or any(
            marker in normalized for marker in _SENSITIVE_ATTRIBUTE_MARKERS
        ):
            continue
        if normalized in _TEXT_ATTRIBUTE_NAMES:
            redacted[f"{key}_length"] = len(str(value))
            continue
        redacted[key] = _json_safe(value)
    return redacted


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def _metric_segment(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip().lower())
    return normalized.strip("_.-") or "unknown"


def _normalize_error(error: BaseException | str | None) -> tuple[str | None, str | None]:
    if error is None:
        return None, None
    if isinstance(error, BaseException):
        return type(error).__name__, str(error)[:1000]
    text = str(error)[:1000]
    error_type, separator, message = text.partition(":")
    return (
        error_type.strip() if separator else "Error",
        message.strip() if separator else text,
    )


def _severity_for(outcome: TelemetryOutcome) -> TelemetrySeverity:
    if outcome in {TelemetryOutcome.ERROR, TelemetryOutcome.NO_RESPONSE}:
        return TelemetrySeverity.ERROR
    if outcome in {
        TelemetryOutcome.TIMEOUT,
        TelemetryOutcome.CANCELLED,
        TelemetryOutcome.SUPERSEDED,
        TelemetryOutcome.DEGRADED,
    }:
        return TelemetrySeverity.WARNING
    return TelemetrySeverity.INFO


def _outcome_from_value(value: str) -> TelemetryOutcome:
    try:
        return TelemetryOutcome(value)
    except ValueError:
        return TelemetryOutcome.ERROR


def _provider_error_outcome(error: Exception) -> TelemetryOutcome:
    """Map provider-specific typed failures without coupling to an adapter."""

    reason = getattr(error, "reason", None)
    normalized = getattr(reason, "value", reason)
    if isinstance(reason, TimeoutError) or normalized in {
        "timeout",
        "pipeline_timeout",
    }:
        return TelemetryOutcome.TIMEOUT
    return TelemetryOutcome.ERROR


def _record_is_timeout(record: TelemetryRecord) -> bool:
    return (
        record.outcome is TelemetryOutcome.TIMEOUT
        or (record.error_type or "").lower() in {"timeouterror", "asyncio.timeouterror"}
    )


def _record_is_error(record: TelemetryRecord) -> bool:
    return record.outcome is TelemetryOutcome.ERROR and not _record_is_timeout(record)


def _record_is_expected_interruption(record: TelemetryRecord) -> bool:
    return (
        record.kind is TelemetryKind.TERMINAL
        and record.outcome in {TelemetryOutcome.CANCELLED, TelemetryOutcome.SUPERSEDED}
        and (record.error_message or "").strip().lower()
        in _EXPECTED_INTERRUPTION_REASONS
    )


def _ledger_outcome(name: str, payload: Mapping[str, Any]) -> TelemetryOutcome:
    normalized = name.lower()
    error = payload.get("error")
    error_type = (
        type(error).__name__
        if isinstance(error, BaseException)
        else str(error).partition(":")[0].strip()
        if error is not None
        else ""
    )
    if "timeout" in normalized or "timed_out" in normalized:
        return TelemetryOutcome.TIMEOUT
    if error_type.lower() in {"timeouterror", "asyncio.timeouterror"}:
        return TelemetryOutcome.TIMEOUT
    if (
        normalized.endswith(("_failed", "_error"))
        or payload.get("error") is not None
    ):
        return TelemetryOutcome.ERROR
    if "superseded" in normalized or "discarded_stale" in normalized:
        return TelemetryOutcome.SUPERSEDED
    if "cancelled" in normalized or "invalidated" in normalized:
        return TelemetryOutcome.CANCELLED
    if "degraded" in normalized:
        return TelemetryOutcome.DEGRADED
    return TelemetryOutcome.OK


def _overview(
    records: Sequence[TelemetryRecord],
    window: DiagnosticsWindow,
) -> DiagnosticsOverview:
    durations: dict[str, list[TelemetryRecord]] = defaultdict(list)
    for record in records:
        if record.duration_ms is not None:
            durations[record.name].append(record)
    metrics = tuple(
        _metric_aggregate(name, samples)
        for name, samples in sorted(durations.items())
    )
    failures: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.name.startswith("realtime.capability.") and record.outcome in {TelemetryOutcome.ERROR, TelemetryOutcome.TIMEOUT}:
            capability = record.name.removeprefix("realtime.capability.")
            row = failures.setdefault(capability, {"capability": capability, "error_count": 0, "timeout_count": 0})
            row["timeout_count" if record.outcome is TelemetryOutcome.TIMEOUT else "error_count"] += 1
    terminals = [record for record in records if record.kind is TelemetryKind.TERMINAL]
    interrupted = [record for record in terminals if _record_is_expected_interruption(record)]
    now = window.until or datetime.now(UTC)
    return DiagnosticsOverview(
        since=window.since,
        until=now,
        session_count=len({record.voice_session_id for record in records}),
        turn_count=len(terminals),
        successful_turn_count=sum(
            record.outcome is TelemetryOutcome.OK for record in terminals
        ),
        no_response_count=sum(
            record.outcome is TelemetryOutcome.NO_RESPONSE for record in terminals
        ),
        timeout_count=sum(_record_is_timeout(record) for record in records),
        error_count=sum(_record_is_error(record) for record in records),
        cancelled_count=sum(
            record.outcome in {TelemetryOutcome.CANCELLED, TelemetryOutcome.SUPERSEDED}
            and not _record_is_expected_interruption(record)
            for record in terminals
        ),
        interrupted_count=len(interrupted),
        degraded_count=sum(
            record.outcome is TelemetryOutcome.DEGRADED for record in records
        ),
        metrics=metrics,
        capability_failures=tuple(failures[name] for name in sorted(failures)),
    )


def _metric_aggregate(
    name: str,
    records: Sequence[TelemetryRecord],
) -> MetricAggregate:
    durations = sorted(
        record.duration_ms for record in records if record.duration_ms is not None
    )
    return MetricAggregate(
        name=name,
        sample_count=len(durations),
        p50_ms=_percentile(durations, 0.50),
        p95_ms=_percentile(durations, 0.95),
        p99_ms=_percentile(durations, 0.99),
        max_ms=durations[-1],
        timeout_count=sum(_record_is_timeout(record) for record in records),
        error_count=sum(_record_is_error(record) for record in records),
        cancelled_count=sum(
            record.outcome in {TelemetryOutcome.CANCELLED, TelemetryOutcome.SUPERSEDED}
            for record in records
        ),
        degraded_count=sum(
            record.outcome is TelemetryOutcome.DEGRADED for record in records
        ),
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    index = max(0, math.ceil(quantile * len(values)) - 1)
    return round(float(values[index]), 3)


def _session_summary(records: Sequence[TelemetryRecord]) -> SessionSummary:
    ordered = sorted(records, key=lambda item: (item.occurred_at, item.sequence))
    terminals = [record for record in ordered if record.kind is TelemetryKind.TERMINAL]
    return SessionSummary(
        voice_session_id=ordered[0].voice_session_id,
        first_event_at=ordered[0].occurred_at,
        last_event_at=ordered[-1].occurred_at,
        turn_count=len(terminals),
        timeout_count=sum(_record_is_timeout(record) for record in ordered),
        error_count=sum(_record_is_error(record) for record in ordered),
        no_response_count=sum(
            record.outcome is TelemetryOutcome.NO_RESPONSE for record in terminals
        ),
        event_count=len(ordered),
    )
