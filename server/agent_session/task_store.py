"""Agent Task Store protocol and deterministic in-memory conformer."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from server.agent_session.driver_protocol import AgentRunHandle, utc_now
from server.agent_session.task_models import (
    AgentTaskPhase,
    AgentTaskRecord,
    CreateTaskResult,
    DelegationRequest,
    IdempotencyConflict,
    InvalidTaskTransition,
    RevisionConflict,
    TaskCreateDisposition,
)


_ALLOWED_TRANSITIONS: dict[AgentTaskPhase, frozenset[AgentTaskPhase]] = {
    AgentTaskPhase.ACCEPTED: frozenset(
        {AgentTaskPhase.QUEUED, AgentTaskPhase.FAILED, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.QUEUED: frozenset(
        {AgentTaskPhase.STARTING, AgentTaskPhase.FAILED, AgentTaskPhase.CANCELLED}
    ),
    AgentTaskPhase.STARTING: frozenset(
        {
            AgentTaskPhase.RUNNING,
            AgentTaskPhase.WAITING,
            AgentTaskPhase.FAILED,
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.TIMED_OUT,
            AgentTaskPhase.UNKNOWN,
        }
    ),
    AgentTaskPhase.RUNNING: frozenset(
        {
            AgentTaskPhase.WAITING,
            AgentTaskPhase.CANCELLING,
            AgentTaskPhase.SUCCEEDED,
            AgentTaskPhase.FAILED,
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.TIMED_OUT,
            AgentTaskPhase.UNKNOWN,
        }
    ),
    AgentTaskPhase.WAITING: frozenset(
        {
            AgentTaskPhase.RUNNING,
            AgentTaskPhase.CANCELLING,
            AgentTaskPhase.FAILED,
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.TIMED_OUT,
            AgentTaskPhase.UNKNOWN,
        }
    ),
    AgentTaskPhase.CANCELLING: frozenset(
        {
            AgentTaskPhase.SUCCEEDED,
            AgentTaskPhase.FAILED,
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.UNKNOWN,
        }
    ),
    AgentTaskPhase.UNKNOWN: frozenset(
        {
            AgentTaskPhase.STARTING,
            AgentTaskPhase.RUNNING,
            AgentTaskPhase.WAITING,
            AgentTaskPhase.CANCELLING,
            AgentTaskPhase.SUCCEEDED,
            AgentTaskPhase.FAILED,
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.TIMED_OUT,
        }
    ),
    AgentTaskPhase.SUCCEEDED: frozenset(),
    AgentTaskPhase.FAILED: frozenset(),
    AgentTaskPhase.CANCELLED: frozenset(),
    AgentTaskPhase.TIMED_OUT: frozenset(),
}


def is_task_transition_allowed(current: AgentTaskPhase, target: AgentTaskPhase) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


class AgentTaskStore(Protocol):
    async def find_or_alias_existing(
        self, request: DelegationRequest
    ) -> CreateTaskResult | None: ...

    async def create_or_get(self, request: DelegationRequest) -> CreateTaskResult: ...

    async def get(self, worker_id: str) -> AgentTaskRecord | None: ...

    async def list_records(self) -> tuple[AgentTaskRecord, ...]: ...

    async def select_candidate(
        self,
        worker_id: str,
        *,
        expected_revision: int,
        agent_name: str,
        candidate_index: int,
    ) -> AgentTaskRecord: ...

    async def commit_backend(
        self, worker_id: str, *, expected_revision: int, dispatch_token: str
    ) -> AgentTaskRecord: ...

    async def attach_handle(
        self, worker_id: str, *, expected_revision: int, handle: AgentRunHandle
    ) -> AgentTaskRecord: ...

    async def begin_dispatch(
        self, worker_id: str, *, expected_revision: int
    ) -> AgentTaskRecord: ...

    async def transition(
        self,
        worker_id: str,
        *,
        expected_revision: int,
        phase: AgentTaskPhase,
        blocker: str | None = None,
        result: str | None = None,
        error: str | None = None,
    ) -> AgentTaskRecord: ...


class InMemoryAgentTaskStore:
    """Concurrency-safe reference store.

    It proves the state and idempotency contract without pretending to be a
    durable production backend. ADR-0055 assigns that role to PostgreSQL.
    """

    def __init__(self, *, worker_id_factory: Callable[[], str] | None = None) -> None:
        self._worker_id_factory = worker_id_factory or (lambda: str(uuid.uuid4()))
        self._records: dict[str, AgentTaskRecord] = {}
        self._request_index: dict[tuple[str, str, str], str] = {}
        self._active_fingerprints: dict[tuple[str, str, str], str] = {}
        self._lock = asyncio.Lock()

    async def find_or_alias_existing(
        self, request: DelegationRequest
    ) -> CreateTaskResult | None:
        request_key = self._request_key(request)
        fingerprint_key = self._fingerprint_key(request)
        async with self._lock:
            existing_worker_id = self._request_index.get(request_key)
            if existing_worker_id is not None:
                existing = self._records[existing_worker_id]
                if existing.request_digest != request.canonical_digest:
                    raise IdempotencyConflict(
                        "delegation_request_id was reused with different canonical content"
                    )
                return CreateTaskResult(
                    existing, TaskCreateDisposition.IDEMPOTENT_REUSE
                )
            if request.force_new:
                return None
            duplicate_worker_id = self._active_fingerprints.get(fingerprint_key)
            if duplicate_worker_id is None:
                return None
            duplicate = self._records[duplicate_worker_id]
            if duplicate.phase.terminal:
                self._active_fingerprints.pop(fingerprint_key, None)
                return None
            self._request_index[request_key] = duplicate_worker_id
            return CreateTaskResult(duplicate, TaskCreateDisposition.SEMANTIC_REUSE)

    async def create_or_get(self, request: DelegationRequest) -> CreateTaskResult:
        request_key = self._request_key(request)
        fingerprint_key = self._fingerprint_key(request)
        async with self._lock:
            existing_worker_id = self._request_index.get(request_key)
            if existing_worker_id is not None:
                existing = self._records[existing_worker_id]
                if existing.request_digest != request.canonical_digest:
                    raise IdempotencyConflict(
                        "delegation_request_id was reused with different canonical content"
                    )
                return CreateTaskResult(existing, TaskCreateDisposition.IDEMPOTENT_REUSE)

            if not request.force_new:
                duplicate_worker_id = self._active_fingerprints.get(fingerprint_key)
                if duplicate_worker_id is not None:
                    duplicate = self._records[duplicate_worker_id]
                    if not duplicate.phase.terminal:
                        self._request_index[request_key] = duplicate_worker_id
                        return CreateTaskResult(duplicate, TaskCreateDisposition.SEMANTIC_REUSE)
                    self._active_fingerprints.pop(fingerprint_key, None)

            worker_id = self._worker_id_factory()
            if not worker_id:
                raise ValueError("worker_id_factory returned an empty worker_id")
            if worker_id in self._records:
                raise ValueError(f"worker_id_factory returned duplicate id {worker_id!r}")
            now = utc_now()
            record = AgentTaskRecord(
                worker_id=worker_id,
                delegation_request_id=request.delegation_request_id,
                request_digest=request.canonical_digest,
                semantic_fingerprint=request.semantic_fingerprint,
                request=request,
                context=request.context.for_worker(worker_id),
                phase=AgentTaskPhase.ACCEPTED,
                revision=1,
                created_at=now,
                updated_at=now,
                dedupe_guard=not request.force_new,
            )
            self._records[worker_id] = record
            self._request_index[request_key] = worker_id
            if record.dedupe_guard:
                self._active_fingerprints[fingerprint_key] = worker_id
            return CreateTaskResult(record, TaskCreateDisposition.CREATED)

    @staticmethod
    def _request_key(request: DelegationRequest) -> tuple[str, str, str]:
        return (
            request.context.tenant_id,
            request.context.thread_id,
            request.delegation_request_id,
        )

    @staticmethod
    def _fingerprint_key(request: DelegationRequest) -> tuple[str, str, str]:
        return (
            request.context.tenant_id,
            request.context.thread_id,
            request.semantic_fingerprint,
        )

    async def get(self, worker_id: str) -> AgentTaskRecord | None:
        async with self._lock:
            return self._records.get(worker_id)

    async def list_records(self) -> tuple[AgentTaskRecord, ...]:
        async with self._lock:
            return tuple(self._records.values())

    async def select_candidate(
        self,
        worker_id: str,
        *,
        expected_revision: int,
        agent_name: str,
        candidate_index: int,
    ) -> AgentTaskRecord:
        async with self._lock:
            record = self._expect(worker_id, expected_revision)
            if record.phase is not AgentTaskPhase.ACCEPTED:
                raise InvalidTaskTransition("candidate can only be selected from ACCEPTED")
            candidate = record.request.selection_plan.candidates[candidate_index]
            if candidate.agent_name != agent_name:
                raise ValueError("candidate index and agent name do not match selection plan")
            return self._replace(
                record,
                phase=AgentTaskPhase.QUEUED,
                selected_agent=agent_name,
                selected_candidate_index=candidate_index,
            )

    async def commit_backend(
        self, worker_id: str, *, expected_revision: int, dispatch_token: str
    ) -> AgentTaskRecord:
        async with self._lock:
            record = self._expect(worker_id, expected_revision)
            if record.phase is not AgentTaskPhase.QUEUED or record.selected_agent is None:
                raise InvalidTaskTransition("backend can only commit a selected QUEUED task")
            if not dispatch_token:
                raise ValueError("dispatch_token must be non-empty")
            return self._replace(
                record,
                phase=AgentTaskPhase.STARTING,
                backend_committed=True,
                dispatch_token=dispatch_token,
            )

    async def attach_handle(
        self, worker_id: str, *, expected_revision: int, handle: AgentRunHandle
    ) -> AgentTaskRecord:
        async with self._lock:
            record = self._expect(worker_id, expected_revision)
            if record.phase is not AgentTaskPhase.STARTING:
                raise InvalidTaskTransition("run handle can only attach to STARTING")
            if handle.worker_id != worker_id or handle.dispatch_token != record.dispatch_token:
                raise ValueError("AgentRunHandle does not match committed task")
            return self._replace(record, phase=AgentTaskPhase.RUNNING, handle=handle)

    async def begin_dispatch(
        self, worker_id: str, *, expected_revision: int
    ) -> AgentTaskRecord:
        async with self._lock:
            record = self._expect(worker_id, expected_revision)
            if record.phase is not AgentTaskPhase.STARTING or not record.backend_committed:
                raise InvalidTaskTransition(
                    "dispatch attempt can only begin for a backend-committed STARTING task"
                )
            if record.handle is not None:
                raise InvalidTaskTransition("dispatch attempt cannot begin after handle attachment")
            return self._replace(
                record,
                dispatch_attempt_count=record.dispatch_attempt_count + 1,
            )

    async def transition(
        self,
        worker_id: str,
        *,
        expected_revision: int,
        phase: AgentTaskPhase,
        blocker: str | None = None,
        result: str | None = None,
        error: str | None = None,
    ) -> AgentTaskRecord:
        async with self._lock:
            record = self._expect(worker_id, expected_revision)
            if not is_task_transition_allowed(record.phase, phase):
                raise InvalidTaskTransition(
                    f"invalid Agent task transition {record.phase.value} -> {phase.value}"
                )
            if phase is AgentTaskPhase.SUCCEEDED and error is not None:
                raise ValueError("successful task cannot carry error")
            if phase is not AgentTaskPhase.SUCCEEDED and result is not None:
                raise ValueError("non-successful task cannot carry result")
            updated = self._replace(
                record,
                phase=phase,
                blocker=blocker,
                result=result,
                error=error,
            )
            if phase.terminal and record.dedupe_guard:
                fingerprint_key = (
                    record.context.tenant_id,
                    record.context.thread_id,
                    record.semantic_fingerprint,
                )
                if self._active_fingerprints.get(fingerprint_key) == worker_id:
                    self._active_fingerprints.pop(fingerprint_key, None)
            return updated

    def _expect(self, worker_id: str, expected_revision: int) -> AgentTaskRecord:
        record = self._records.get(worker_id)
        if record is None:
            raise KeyError(worker_id)
        if record.revision != expected_revision:
            raise RevisionConflict(
                f"worker {worker_id} expected revision {expected_revision}, found {record.revision}"
            )
        return record

    def _replace(self, record: AgentTaskRecord, **changes: object) -> AgentTaskRecord:
        updated = replace(
            record,
            revision=record.revision + 1,
            updated_at=utc_now(),
            **changes,
        )
        self._records[record.worker_id] = updated
        return updated
