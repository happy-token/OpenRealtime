"""Durable callback identity and cursor contract for canonical Agent events."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from server.agent_session.driver_protocol import (
    AgentArtifactPublished,
    AgentEvent,
    AgentInputRequested,
    AgentMessageDelta,
    AgentPermissionRequested,
    AgentPlanUpdated,
    AgentProgressUpdated,
    AgentRunLocator,
    AgentRunPhase,
    AgentRunStarted,
    AgentRunTerminal,
    AgentRunWaiting,
    AgentUsageUpdated,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class AgentEventRecord:
    event: AgentEvent
    event_digest: str
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class AgentEventAppendResult:
    record: AgentEventRecord
    created: bool


class AgentEventConflict(RuntimeError):
    pass


class AgentEventGap(RuntimeError):
    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"expected Agent event sequence {expected}, found {actual}")


class AgentEventStore(Protocol):
    async def append(self, event: AgentEvent) -> AgentEventAppendResult: ...

    async def last_sequence(self, worker_id: str) -> int: ...

    async def list_events(
        self,
        worker_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> tuple[AgentEventRecord, ...]: ...


class InMemoryAgentEventStore:
    def __init__(self) -> None:
        self._events: dict[str, list[AgentEventRecord]] = {}
        self._event_ids: dict[tuple[str, str], AgentEventRecord] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: AgentEvent) -> AgentEventAppendResult:
        _validate_event_identity(event)
        digest = agent_event_digest(event)
        async with self._lock:
            key = (event.worker_id, event.event_id)
            existing = self._event_ids.get(key)
            if existing is not None:
                if existing.event_digest != digest:
                    raise AgentEventConflict(
                        f"Agent event {event.event_id!r} was reused with different content"
                    )
                return AgentEventAppendResult(existing, created=False)
            events = self._events.setdefault(event.worker_id, [])
            expected = len(events) + 1
            if event.sequence != expected:
                raise AgentEventGap(expected=expected, actual=event.sequence)
            record = AgentEventRecord(
                event=event,
                event_digest=digest,
                ingested_at=utc_now(),
            )
            events.append(record)
            self._event_ids[key] = record
            return AgentEventAppendResult(record, created=True)

    async def last_sequence(self, worker_id: str) -> int:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        async with self._lock:
            return len(self._events.get(worker_id, ()))

    async def list_events(
        self,
        worker_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> tuple[AgentEventRecord, ...]:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        _validate_window(after_sequence, limit)
        async with self._lock:
            return tuple(
                record
                for record in self._events.get(worker_id, ())
                if record.event.sequence > after_sequence
            )[:limit]


def encode_agent_event(event: AgentEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": agent_event_kind(event),
        "worker_id": event.worker_id,
        "event_id": event.event_id,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at.isoformat(),
        "locator": {
            "driver_kind": event.locator.driver_kind,
            "backend_session_id": event.locator.backend_session_id,
            "backend_run_id": event.locator.backend_run_id,
        },
    }
    if isinstance(event, AgentProgressUpdated):
        payload.update(text=event.text, progress_version=event.progress_version)
    elif isinstance(event, (AgentMessageDelta, AgentPlanUpdated)):
        payload["text"] = event.text
    elif isinstance(event, AgentPermissionRequested):
        payload.update(
            request_id=event.request_id,
            method=event.method,
            payload=dict(event.payload),
        )
    elif isinstance(event, AgentInputRequested):
        payload.update(request_id=event.request_id, prompt=event.prompt)
    elif isinstance(event, AgentArtifactPublished):
        payload.update(artifact_id=event.artifact_id, logical_name=event.logical_name)
    elif isinstance(event, AgentUsageUpdated):
        payload.update(
            input_tokens=event.input_tokens,
            cached_input_tokens=event.cached_input_tokens,
            output_tokens=event.output_tokens,
            cost_usd=event.cost_usd,
        )
    elif isinstance(event, AgentRunWaiting):
        payload["reason"] = event.reason
    elif isinstance(event, AgentRunTerminal):
        payload.update(phase=event.phase.value, result=event.result, error=event.error)
    return payload


def decode_agent_event(payload: dict[str, Any]) -> AgentEvent:
    common = {
        "worker_id": payload["worker_id"],
        "event_id": payload["event_id"],
        "sequence": payload["sequence"],
        "occurred_at": datetime.fromisoformat(payload["occurred_at"]),
        "locator": AgentRunLocator(**payload["locator"]),
    }
    kind = payload["kind"]
    if kind == "run.started":
        return AgentRunStarted(**common)
    if kind == "progress.updated":
        return AgentProgressUpdated(
            **common,
            text=payload["text"],
            progress_version=payload["progress_version"],
        )
    if kind == "message.delta":
        return AgentMessageDelta(**common, text=payload["text"])
    if kind == "plan.updated":
        return AgentPlanUpdated(**common, text=payload["text"])
    if kind == "permission.requested":
        return AgentPermissionRequested(
            **common,
            request_id=payload["request_id"],
            method=payload["method"],
            payload=payload["payload"],
        )
    if kind == "input.requested":
        return AgentInputRequested(
            **common,
            request_id=payload["request_id"],
            prompt=payload["prompt"],
        )
    if kind == "artifact.published":
        return AgentArtifactPublished(
            **common,
            artifact_id=payload["artifact_id"],
            logical_name=payload["logical_name"],
        )
    if kind == "usage.updated":
        return AgentUsageUpdated(
            **common,
            input_tokens=payload["input_tokens"],
            cached_input_tokens=payload["cached_input_tokens"],
            output_tokens=payload["output_tokens"],
            cost_usd=payload["cost_usd"],
        )
    if kind == "run.waiting":
        return AgentRunWaiting(**common, reason=payload["reason"])
    if kind == "run.terminal":
        return AgentRunTerminal(
            **common,
            phase=AgentRunPhase(payload["phase"]),
            result=payload["result"],
            error=payload["error"],
        )
    raise ValueError(f"unsupported Agent event kind: {kind!r}")


def agent_event_kind(event: AgentEvent) -> str:
    for event_type, kind in _EVENT_KINDS:
        if isinstance(event, event_type):
            return kind
    raise TypeError(f"unsupported Agent event type: {type(event).__name__}")


def agent_event_digest(event: AgentEvent) -> str:
    try:
        encoded = json.dumps(
            encode_agent_event(event),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Agent event must be JSON serializable") from error
    return hashlib.sha256(encoded.encode()).hexdigest()


def _validate_event_identity(event: AgentEvent) -> None:
    if not event.worker_id or not event.event_id:
        raise ValueError("Agent event worker_id and event_id must be non-empty")
    agent_event_kind(event)


def _validate_window(after_sequence: int, limit: int) -> None:
    if after_sequence < 0:
        raise ValueError("after_sequence must be non-negative")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")


_EVENT_KINDS: tuple[tuple[type[Any], str], ...] = (
    (AgentRunStarted, "run.started"),
    (AgentProgressUpdated, "progress.updated"),
    (AgentMessageDelta, "message.delta"),
    (AgentPlanUpdated, "plan.updated"),
    (AgentPermissionRequested, "permission.requested"),
    (AgentInputRequested, "input.requested"),
    (AgentArtifactPublished, "artifact.published"),
    (AgentUsageUpdated, "usage.updated"),
    (AgentRunWaiting, "run.waiting"),
    (AgentRunTerminal, "run.terminal"),
)
