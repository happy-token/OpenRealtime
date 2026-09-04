"""PostgreSQL Agent Task Store with durable idempotency and CAS transitions."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from server.agent_session.driver_protocol import AgentRunHandle, utc_now
from server.agent_session.task_codec import (
    decode_context,
    decode_handle,
    decode_request,
    encode_context,
    encode_handle,
    encode_request,
)
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
from server.agent_session.task_store import AgentTaskStore, is_task_transition_allowed
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name


class PostgresAgentTaskStore(AgentTaskStore):
    def __init__(
        self,
        executor: Any,
        *,
        schema: str = "voiceagent",
        worker_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._executor = executor
        self._schema = validate_schema_name(schema)
        self._tasks = f'"{self._schema}".agent_tasks'
        self._request_keys = f'"{self._schema}".agent_task_request_keys'
        self._worker_id_factory = worker_id_factory or (lambda: str(uuid.uuid4()))

    async def find_or_alias_existing(
        self, request: DelegationRequest
    ) -> CreateTaskResult | None:
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                key = await connection.fetchrow(
                    f"""
                    SELECT worker_id, request_digest
                    FROM {self._request_keys}
                    WHERE tenant_id = $1 AND thread_id = $2
                      AND delegation_request_id = $3
                    """,
                    request.context.tenant_id,
                    request.context.thread_id,
                    request.delegation_request_id,
                )
                if key is not None:
                    if key["request_digest"] != request.canonical_digest:
                        raise IdempotencyConflict(
                            "delegation_request_id was reused with different canonical content"
                        )
                    record = await self._fetch_record(connection, key["worker_id"])
                    return CreateTaskResult(
                        record, TaskCreateDisposition.IDEMPOTENT_REUSE
                    )
                if request.force_new:
                    return None
                duplicate = await connection.fetchrow(
                    f"""
                    SELECT * FROM {self._tasks}
                    WHERE tenant_id = $1 AND thread_id = $2
                      AND semantic_fingerprint = $3 AND dedupe_guard
                      AND phase = ANY($4::text[])
                    """,
                    request.context.tenant_id,
                    request.context.thread_id,
                    request.semantic_fingerprint,
                    _ACTIVE_PHASE_VALUES,
                )
                if duplicate is None:
                    return None
                await connection.execute(
                    f"""
                    INSERT INTO {self._request_keys} (
                        tenant_id, thread_id, delegation_request_id,
                        request_digest, worker_id, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (tenant_id, thread_id, delegation_request_id)
                    DO NOTHING
                    """,
                    request.context.tenant_id,
                    request.context.thread_id,
                    request.delegation_request_id,
                    request.canonical_digest,
                    duplicate["worker_id"],
                    utc_now(),
                )
                key = await connection.fetchrow(
                    f"""
                    SELECT worker_id, request_digest
                    FROM {self._request_keys}
                    WHERE tenant_id = $1 AND thread_id = $2
                      AND delegation_request_id = $3
                    """,
                    request.context.tenant_id,
                    request.context.thread_id,
                    request.delegation_request_id,
                )
                if key is None:
                    raise RuntimeError("semantic alias disappeared during transaction")
                if key["request_digest"] != request.canonical_digest:
                    raise IdempotencyConflict(
                        "delegation_request_id was reused with different canonical content"
                    )
                record = await self._fetch_record(connection, key["worker_id"])
                return CreateTaskResult(record, TaskCreateDisposition.SEMANTIC_REUSE)

    async def create_or_get(self, request: DelegationRequest) -> CreateTaskResult:
        candidate_worker_id = self._worker_id_factory()
        if not candidate_worker_id:
            raise ValueError("worker_id_factory returned an empty worker_id")
        now = utc_now()
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                owns_request_key = await connection.fetchrow(
                    f"""
                    INSERT INTO {self._request_keys} (
                        tenant_id, thread_id, delegation_request_id,
                        request_digest, worker_id, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (tenant_id, thread_id, delegation_request_id)
                    DO NOTHING
                    RETURNING worker_id, request_digest
                    """,
                    request.context.tenant_id,
                    request.context.thread_id,
                    request.delegation_request_id,
                    request.canonical_digest,
                    candidate_worker_id,
                    now,
                )
                if owns_request_key is None:
                    key = await connection.fetchrow(
                        f"""
                        SELECT worker_id, request_digest
                        FROM {self._request_keys}
                        WHERE tenant_id = $1 AND thread_id = $2
                          AND delegation_request_id = $3
                        """,
                        request.context.tenant_id,
                        request.context.thread_id,
                        request.delegation_request_id,
                    )
                    if key is None:
                        raise RuntimeError("idempotency key disappeared during transaction")
                    if key["request_digest"] != request.canonical_digest:
                        raise IdempotencyConflict(
                            "delegation_request_id was reused with different canonical content"
                        )
                    record = await self._fetch_record(connection, key["worker_id"])
                    return CreateTaskResult(record, TaskCreateDisposition.IDEMPOTENT_REUSE)

                if not request.force_new:
                    duplicate = await connection.fetchrow(
                        f"""
                        SELECT * FROM {self._tasks}
                        WHERE tenant_id = $1 AND thread_id = $2
                          AND semantic_fingerprint = $3 AND dedupe_guard
                          AND phase = ANY($4::text[])
                        FOR UPDATE
                        """,
                        request.context.tenant_id,
                        request.context.thread_id,
                        request.semantic_fingerprint,
                        _ACTIVE_PHASE_VALUES,
                    )
                    if duplicate is not None:
                        await self._retarget_request_key(
                            connection, request, duplicate["worker_id"]
                        )
                        return CreateTaskResult(
                            self._record(duplicate),
                            TaskCreateDisposition.SEMANTIC_REUSE,
                        )

                context = request.context.for_worker(candidate_worker_id)
                inserted = await connection.fetchrow(
                    f"""
                    INSERT INTO {self._tasks} (
                        worker_id, tenant_id, user_id, voice_session_id,
                        thread_id, turn_id, generation, delegation_request_id,
                        request_digest, semantic_fingerprint, request_payload,
                        context_payload, phase, revision, dedupe_guard,
                        created_at, updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        $9, $10, $11::jsonb, $12::jsonb, $13, 1, $14, $15, $15
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING *
                    """,
                    candidate_worker_id,
                    context.tenant_id,
                    context.user_id,
                    context.voice_session_id,
                    context.thread_id,
                    context.turn_id,
                    context.generation,
                    request.delegation_request_id,
                    request.canonical_digest,
                    request.semantic_fingerprint,
                    encode_request(request),
                    encode_context(context),
                    AgentTaskPhase.ACCEPTED.value,
                    not request.force_new,
                    now,
                )
                if inserted is not None:
                    return CreateTaskResult(self._record(inserted), TaskCreateDisposition.CREATED)

                if request.force_new:
                    raise RuntimeError(f"generated worker_id collision for {candidate_worker_id!r}")
                duplicate = await connection.fetchrow(
                    f"""
                    SELECT * FROM {self._tasks}
                    WHERE tenant_id = $1 AND thread_id = $2
                      AND semantic_fingerprint = $3 AND dedupe_guard
                      AND phase = ANY($4::text[])
                    """,
                    request.context.tenant_id,
                    request.context.thread_id,
                    request.semantic_fingerprint,
                    _ACTIVE_PHASE_VALUES,
                )
                if duplicate is None:
                    raise RuntimeError("semantic conflict winner was not visible")
                await self._retarget_request_key(connection, request, duplicate["worker_id"])
                return CreateTaskResult(
                    self._record(duplicate), TaskCreateDisposition.SEMANTIC_REUSE
                )

    async def get(self, worker_id: str) -> AgentTaskRecord | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"SELECT * FROM {self._tasks} WHERE worker_id = $1", worker_id
            )
            return self._record(row) if row is not None else None

    async def list_records(self) -> tuple[AgentTaskRecord, ...]:
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"SELECT * FROM {self._tasks} ORDER BY created_at, worker_id"
            )
            return tuple(self._record(row) for row in rows)

    async def select_candidate(
        self,
        worker_id: str,
        *,
        expected_revision: int,
        agent_name: str,
        candidate_index: int,
    ) -> AgentTaskRecord:
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                current = await self._fetch_record(connection, worker_id)
                self._expect_revision(current, expected_revision)
                if current.phase is not AgentTaskPhase.ACCEPTED:
                    raise InvalidTaskTransition("candidate can only be selected from ACCEPTED")
                try:
                    candidate = current.request.selection_plan.candidates[candidate_index]
                except IndexError as error:
                    raise ValueError("candidate index is outside selection plan") from error
                if candidate.agent_name != agent_name:
                    raise ValueError("candidate index and agent name do not match selection plan")
                return await self._update(
                    connection,
                    current,
                    phase=AgentTaskPhase.QUEUED,
                    selected_agent=agent_name,
                    selected_candidate_index=candidate_index,
                )

    async def commit_backend(
        self, worker_id: str, *, expected_revision: int, dispatch_token: str
    ) -> AgentTaskRecord:
        if not dispatch_token:
            raise ValueError("dispatch_token must be non-empty")
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                current = await self._fetch_record(connection, worker_id)
                self._expect_revision(current, expected_revision)
                if current.phase is not AgentTaskPhase.QUEUED or current.selected_agent is None:
                    raise InvalidTaskTransition("backend can only commit a selected QUEUED task")
                return await self._update(
                    connection,
                    current,
                    phase=AgentTaskPhase.STARTING,
                    backend_committed=True,
                    dispatch_token=dispatch_token,
                )

    async def attach_handle(
        self, worker_id: str, *, expected_revision: int, handle: AgentRunHandle
    ) -> AgentTaskRecord:
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                current = await self._fetch_record(connection, worker_id)
                self._expect_revision(current, expected_revision)
                if current.phase is not AgentTaskPhase.STARTING:
                    raise InvalidTaskTransition("run handle can only attach to STARTING")
                if handle.worker_id != worker_id or handle.dispatch_token != current.dispatch_token:
                    raise ValueError("AgentRunHandle does not match committed task")
                return await self._update(
                    connection,
                    current,
                    phase=AgentTaskPhase.RUNNING,
                    handle=handle,
                )

    async def begin_dispatch(
        self, worker_id: str, *, expected_revision: int
    ) -> AgentTaskRecord:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                UPDATE {self._tasks}
                SET dispatch_attempt_count = dispatch_attempt_count + 1,
                    revision = revision + 1, updated_at = $3
                WHERE worker_id = $1 AND revision = $2
                  AND phase = 'starting' AND backend_committed
                  AND handle_payload IS NULL
                RETURNING *
                """,
                worker_id,
                expected_revision,
                utc_now(),
            )
            if row is None:
                current = await self._fetch_record(connection, worker_id)
                self._expect_revision(current, expected_revision)
                raise InvalidTaskTransition(
                    "dispatch attempt can only begin for a backend-committed "
                    "STARTING task without a handle"
                )
            return self._record(row)

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
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                current = await self._fetch_record(connection, worker_id)
                self._expect_revision(current, expected_revision)
                if not is_task_transition_allowed(current.phase, phase):
                    raise InvalidTaskTransition(
                        f"invalid Agent task transition {current.phase.value} -> {phase.value}"
                    )
                if phase is AgentTaskPhase.SUCCEEDED and error is not None:
                    raise ValueError("successful task cannot carry error")
                if phase is not AgentTaskPhase.SUCCEEDED and result is not None:
                    raise ValueError("non-successful task cannot carry result")
                return await self._update(
                    connection,
                    current,
                    phase=phase,
                    blocker=blocker,
                    result=result,
                    error=error,
                )

    async def _fetch_record(self, connection: Any, worker_id: str) -> AgentTaskRecord:
        row = await connection.fetchrow(
            f"SELECT * FROM {self._tasks} WHERE worker_id = $1", worker_id
        )
        if row is None:
            raise KeyError(worker_id)
        return self._record(row)

    async def _retarget_request_key(
        self, connection: Any, request: DelegationRequest, worker_id: str
    ) -> None:
        await connection.execute(
            f"""
            UPDATE {self._request_keys}
            SET worker_id = $4
            WHERE tenant_id = $1 AND thread_id = $2
              AND delegation_request_id = $3
            """,
            request.context.tenant_id,
            request.context.thread_id,
            request.delegation_request_id,
            worker_id,
        )

    async def _update(
        self,
        connection: Any,
        current: AgentTaskRecord,
        **changes: object,
    ) -> AgentTaskRecord:
        values = {
            "phase": current.phase,
            "selected_agent": current.selected_agent,
            "selected_candidate_index": current.selected_candidate_index,
            "backend_committed": current.backend_committed,
            "dispatch_token": current.dispatch_token,
            "handle": current.handle,
            "blocker": current.blocker,
            "result": current.result,
            "error": current.error,
            **changes,
        }
        row = await connection.fetchrow(
            f"""
            UPDATE {self._tasks}
            SET phase = $3, selected_agent = $4,
                selected_candidate_index = $5, backend_committed = $6,
                dispatch_token = $7, handle_payload = $8::jsonb,
                blocker = $9, result = $10, error = $11,
                revision = revision + 1, updated_at = $12
            WHERE worker_id = $1 AND revision = $2
            RETURNING *
            """,
            current.worker_id,
            current.revision,
            _phase_value(values["phase"]),
            values["selected_agent"],
            values["selected_candidate_index"],
            values["backend_committed"],
            values["dispatch_token"],
            encode_handle(_optional_handle(values["handle"])),
            values["blocker"],
            values["result"],
            values["error"],
            utc_now(),
        )
        if row is None:
            raise RevisionConflict(f"worker {current.worker_id} revision changed during update")
        return self._record(row)

    def _record(self, row: Mapping[str, Any]) -> AgentTaskRecord:
        return AgentTaskRecord(
            worker_id=row["worker_id"],
            delegation_request_id=row["delegation_request_id"],
            request_digest=row["request_digest"],
            semantic_fingerprint=row["semantic_fingerprint"],
            request=decode_request(row["request_payload"]),
            context=decode_context(row["context_payload"]),
            phase=AgentTaskPhase(row["phase"]),
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            dedupe_guard=row["dedupe_guard"],
            dispatch_attempt_count=row["dispatch_attempt_count"],
            selected_agent=row["selected_agent"],
            selected_candidate_index=row["selected_candidate_index"],
            backend_committed=row["backend_committed"],
            dispatch_token=row["dispatch_token"],
            handle=decode_handle(row["handle_payload"]),
            blocker=row["blocker"],
            result=row["result"],
            error=row["error"],
        )

    @staticmethod
    def _expect_revision(record: AgentTaskRecord, expected_revision: int) -> None:
        if record.revision != expected_revision:
            raise RevisionConflict(
                f"worker {record.worker_id} expected revision {expected_revision}, "
                f"found {record.revision}"
            )


_ACTIVE_PHASE_VALUES = [phase.value for phase in AgentTaskPhase if not phase.terminal]


def _phase_value(value: object) -> str:
    if not isinstance(value, AgentTaskPhase):
        raise TypeError("phase update must be an AgentTaskPhase")
    return value.value


def _optional_handle(value: object) -> AgentRunHandle | None:
    if value is None or isinstance(value, AgentRunHandle):
        return value
    raise TypeError("handle update must be an AgentRunHandle or None")
