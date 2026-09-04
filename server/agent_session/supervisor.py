"""Agent Task Supervisor: the sole authority allowed to start v2 Drivers."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentDriver,
    AgentEvent,
    AgentMessageDelta,
    AgentPlanUpdated,
    AgentProgressUpdated,
    AgentRunHandle,
    AgentRunPhase,
    AgentRunSnapshot,
    AgentRunStarted,
    AgentRunTerminal,
    AgentRunWaiting,
    AgentStartRequest,
    WorkspaceLease,
    utc_now,
)
from server.agent_session.task_models import (
    AgentCandidate,
    AgentTaskPhase,
    AgentTaskRecord,
    ConfirmationRule,
    CreateTaskResult,
    DelegationRequest,
    InvalidTaskTransition,
    RevisionConflict,
)
from server.conversation_journal import (
    ConversationItem,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    StructuredContent,
    TextContent,
)
from server.persistence.outbox import OutboxMessage, OutboxMessageDraft
from server.persistence.unit_of_work import AgentPersistence

logger = logging.getLogger(__name__)

AGENT_DISPATCH_MESSAGE_TYPE = "agent.dispatch.requested.v1"
AGENT_RESULT_MESSAGE_TYPE = "agent.result.committed.v1"


class AgentSelectionError(RuntimeError):
    pass


class FallbackConfirmationRequired(AgentSelectionError):
    def __init__(self, worker_id: str, candidate: AgentCandidate) -> None:
        self.worker_id = worker_id
        self.candidate = candidate
        super().__init__(f"fallback to {candidate.agent_name!r} requires confirmation")


class _FallbackSelectionRequired(AgentSelectionError):
    def __init__(self, candidate: AgentCandidate) -> None:
        self.candidate = candidate
        super().__init__(candidate.agent_name)


@dataclass(frozen=True, slots=True)
class TaskSubmission:
    record: AgentTaskRecord
    create_result: CreateTaskResult
    dispatch_message: OutboxMessage | None = None
    committed_items: tuple[ConversationItem, ...] = ()

    @property
    def started_new_execution(self) -> bool:
        return self.create_result.created and self.record.handle is not None

    @property
    def queued_new_execution(self) -> bool:
        return self.create_result.created and self.dispatch_message is not None


@dataclass(frozen=True, slots=True)
class DispatchResult:
    message: OutboxMessage
    record: AgentTaskRecord | None
    started: bool = False


class AgentTaskSupervisor:
    def __init__(
        self,
        *,
        persistence: AgentPersistence,
        drivers: Mapping[str, AgentDriver],
    ) -> None:
        self._persistence = persistence
        self._store = persistence.agent_tasks
        self._outbox = persistence.outbox
        self._events = persistence.agent_events
        self._drivers = dict(drivers)
        self._event_tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    async def submit(self, request: DelegationRequest) -> TaskSubmission:
        if self._closed:
            raise RuntimeError("AgentTaskSupervisor is closed")
        existing = await self._store.find_or_alias_existing(request)
        if existing is not None:
            return TaskSubmission(record=existing.record, create_result=existing)
        try:
            candidate_index, candidate, _ = await self._select_candidate(request)
        except _FallbackSelectionRequired as error:
            failure = await self._persist_selection_failure(
                request,
                error=f"fallback_confirmation_required:{error.candidate.agent_name}",
            )
            if not failure.create_result.created:
                return failure
            raise FallbackConfirmationRequired(
                failure.record.worker_id, error.candidate
            ) from error
        except AgentSelectionError as error:
            failure = await self._persist_selection_failure(request, error=str(error))
            if not failure.create_result.created:
                return failure
            raise

        dispatch_token = str(uuid.uuid4())
        lease_id = str(uuid.uuid4())
        lease_expires_at = utc_now() + timedelta(seconds=request.budget.max_wall_time_s)
        async with self._persistence.unit_of_work() as unit:
            created = await unit.agent_tasks.create_or_get(request)
            if not created.created:
                return TaskSubmission(record=created.record, create_result=created)
            record = await unit.agent_tasks.select_candidate(
                created.record.worker_id,
                expected_revision=created.record.revision,
                agent_name=candidate.agent_name,
                candidate_index=candidate_index,
            )
            record = await unit.agent_tasks.commit_backend(
                record.worker_id,
                expected_revision=record.revision,
                dispatch_token=dispatch_token,
            )
            requested_item = await unit.journal.append(
                _delegation_requested_item(record)
            )
            message = await unit.outbox.enqueue(
                _dispatch_draft(
                    record,
                    lease_id=lease_id,
                    lease_expires_at=lease_expires_at,
                )
            )
        return TaskSubmission(
            record=record,
            create_result=created,
            dispatch_message=message,
            committed_items=(requested_item.item,),
        )

    async def dispatch_once(
        self,
        *,
        owner: str,
        limit: int = 10,
        lease_seconds: float = 30,
        retry_delay_seconds: float = 1,
    ) -> tuple[DispatchResult, ...]:
        if self._closed:
            raise RuntimeError("AgentTaskSupervisor is closed")
        messages = await self._outbox.claim(
            owner=owner,
            limit=limit,
            lease_seconds=lease_seconds,
            message_types=frozenset({AGENT_DISPATCH_MESSAGE_TYPE}),
        )
        results: list[DispatchResult] = []
        for message in messages:
            results.append(
                await self._dispatch_message(
                    message,
                    owner=owner,
                    retry_delay_seconds=retry_delay_seconds,
                )
            )
        return tuple(results)

    async def get(self, worker_id: str) -> AgentTaskRecord | None:
        return await self._store.get(worker_id)

    async def cancel(self, worker_id: str, reason: str) -> AgentTaskRecord:
        record = await self._require(worker_id)
        if record.phase.terminal:
            return record
        if record.handle is None:
            if record.backend_committed and record.dispatch_attempt_count > 0:
                # The external start may already have happened. Without an exact
                # handle/locator, claiming cancellation would release the dedupe
                # guard while an unobserved backend run could still be active.
                return record
            return await self._store.transition(
                worker_id,
                expected_revision=record.revision,
                phase=AgentTaskPhase.CANCELLED,
                error=reason,
            )
        if record.phase is not AgentTaskPhase.CANCELLING:
            record = await self._store.transition(
                worker_id,
                expected_revision=record.revision,
                phase=AgentTaskPhase.CANCELLING,
                blocker=reason,
            )
        driver = self._drivers[record.selected_agent or ""]
        result = await driver.cancel(record.handle, reason)
        if result.stopped:
            current = await self._require(worker_id)
            if not current.phase.terminal:
                return await self._store.transition(
                    worker_id,
                    expected_revision=current.revision,
                    phase=AgentTaskPhase.CANCELLED,
                    error=reason,
                )
        return await self._require(worker_id)

    async def recover_active(self) -> tuple[str, ...]:
        if self._closed:
            raise RuntimeError("AgentTaskSupervisor is closed")
        recovered: list[str] = []
        for record in await self._store.list_records():
            if record.phase.terminal or record.handle is None or not record.selected_agent:
                continue
            driver = self._drivers.get(record.selected_agent)
            if driver is None:
                continue
            try:
                descriptor = await driver.capabilities()
            except Exception:
                logger.warning(
                    "agent recovery capability lookup failed: worker_id=%s agent=%s",
                    record.worker_id,
                    record.selected_agent,
                    exc_info=True,
                )
                continue
            required_recovery = {
                AgentCapability.RESUME,
                AgentCapability.STATUS_LOOKUP,
            }
            if not required_recovery.issubset(descriptor.capabilities):
                await self._mark_dispatch_unknown(
                    record,
                    "driver cannot safely resume/status an existing backend run",
                )
                continue
            cursor = await self._events.last_sequence(record.worker_id)
            try:
                handle = await driver.resume(
                    record.handle.locator,
                    worker_id=record.worker_id,
                    dispatch_token=record.handle.dispatch_token,
                    after_sequence=cursor,
                )
            except Exception:
                logger.warning(
                    "agent recovery resume failed: worker_id=%s agent=%s",
                    record.worker_id,
                    record.selected_agent,
                    exc_info=True,
                )
                continue
            if handle.dispatch_token != record.dispatch_token:
                continue
            try:
                snapshot = await driver.status(handle)
            except Exception:
                logger.warning(
                    "agent recovery status lookup failed: worker_id=%s agent=%s",
                    record.worker_id,
                    record.selected_agent,
                    exc_info=True,
                )
                continue
            if (
                snapshot.worker_id != record.worker_id
                or snapshot.locator != handle.locator
                or (
                    AgentCapability.EVENT_REPLAY in descriptor.capabilities
                    and snapshot.last_event_sequence < cursor
                )
            ):
                continue
            if (
                snapshot.phase.terminal
                and AgentCapability.EVENT_REPLAY not in descriptor.capabilities
            ):
                await self._ingest_event(
                    AgentRunTerminal(
                        worker_id=record.worker_id,
                        event_id=_reconciliation_event_id(record, snapshot),
                        sequence=cursor + 1,
                        occurred_at=utc_now(),
                        locator=snapshot.locator,
                        phase=snapshot.phase,
                        result=snapshot.result,
                        error=snapshot.error,
                    )
                )
            else:
                self._start_event_consumer(driver, handle, after=cursor)
            recovered.append(record.worker_id)
        return tuple(recovered)

    async def shutdown(self) -> None:
        self._closed = True
        tasks = tuple(self._event_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for worker_id in tuple(self._event_tasks):
            record = await self._store.get(worker_id)
            if record and record.handle and record.selected_agent:
                await self._drivers[record.selected_agent].close(record.handle)
        self._event_tasks.clear()

    async def _select_candidate(
        self, request: DelegationRequest
    ) -> tuple[int, AgentCandidate, AgentDriver]:
        plan = request.selection_plan
        required_by_plan = plan.required_capabilities
        reasons: list[str] = []
        primary_failure_reason: str | None = None
        for index, candidate in enumerate(plan.candidates):
            if index > 0 and primary_failure_reason not in plan.fallback_reason_allowlist:
                break
            driver = self._drivers.get(candidate.agent_name)
            if driver is None:
                reason = "backend_unavailable"
                reasons.append(f"{candidate.agent_name}: {reason}")
                if index == 0:
                    primary_failure_reason = reason
                continue
            try:
                descriptor = await driver.capabilities()
            except Exception as error:
                reason = "backend_unavailable"
                reasons.append(f"{candidate.agent_name}: {reason} ({type(error).__name__})")
                if index == 0:
                    primary_failure_reason = reason
                continue
            required = required_by_plan | candidate.required_capabilities
            if not descriptor.supports(required):
                reason = "capability_mismatch"
                reasons.append(f"{candidate.agent_name}: {reason}")
                if index == 0:
                    primary_failure_reason = reason
                continue
            if index > 0 and plan.confirmation_on_fallback in {
                ConfirmationRule.REQUIRE,
                ConfirmationRule.STRONG,
            }:
                raise _FallbackSelectionRequired(candidate)
            return index, candidate, driver
        detail = "; ".join(reasons) if reasons else "selection plan has no candidate"
        raise AgentSelectionError(detail)

    async def _persist_selection_failure(
        self, request: DelegationRequest, *, error: str
    ) -> TaskSubmission:
        async with self._persistence.unit_of_work() as unit:
            created = await unit.agent_tasks.create_or_get(request)
            if not created.created:
                return TaskSubmission(record=created.record, create_result=created)
            failed = await unit.agent_tasks.transition(
                created.record.worker_id,
                expected_revision=created.record.revision,
                phase=AgentTaskPhase.FAILED,
                error=error,
            )
            requested_item = await unit.journal.append(
                _delegation_requested_item(failed)
            )
            failed_item = await unit.journal.append(
                _delegation_failed_item(failed, error=error)
            )
            return TaskSubmission(
                record=failed,
                create_result=created,
                committed_items=(requested_item.item, failed_item.item),
            )

    async def _dispatch_message(
        self,
        message: OutboxMessage,
        *,
        owner: str,
        retry_delay_seconds: float,
    ) -> DispatchResult:
        try:
            (
                worker_id,
                dispatch_token,
                selected_agent,
                lease_id,
                lease_expires_at,
            ) = _decode_dispatch_message(message)
        except ValueError as error:
            dead = await self._outbox.reschedule(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
                error=f"invalid dispatch message: {error}",
                retry_delay_seconds=0,
                terminal=True,
            )
            return DispatchResult(message=dead, record=None)

        record = await self._store.get(worker_id)
        if record is None:
            dead = await self._outbox.reschedule(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
                error=f"agent task {worker_id!r} does not exist",
                retry_delay_seconds=0,
                terminal=True,
            )
            return DispatchResult(message=dead, record=None)
        if (
            message.tenant_id != record.context.tenant_id
            or dispatch_token != record.dispatch_token
            or selected_agent != record.selected_agent
        ):
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=record,
                error="dispatch message does not match committed task identity",
            )
        if record.phase.terminal:
            delivered = await self._outbox.mark_delivered(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
            )
            return DispatchResult(message=delivered, record=record)
        if record.handle is not None:
            driver = self._drivers.get(record.selected_agent or "")
            if driver is not None:
                cursor = await self._events.last_sequence(record.worker_id)
                self._start_event_consumer(driver, record.handle, after=cursor)
            delivered = await self._outbox.mark_delivered(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
            )
            return DispatchResult(message=delivered, record=record)
        if (
            record.phase is not AgentTaskPhase.STARTING
            or not record.backend_committed
            or record.dispatch_token is None
            or record.selected_agent is None
        ):
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=record,
                error="task is not a committed STARTING dispatch",
            )
        if lease_expires_at <= utc_now():
            timed_out = await self._store.transition(
                record.worker_id,
                expected_revision=record.revision,
                phase=AgentTaskPhase.TIMED_OUT,
                error="workspace lease expired before Agent dispatch",
            )
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=timed_out,
                error="workspace lease expired before Agent dispatch",
            )

        driver = self._drivers.get(record.selected_agent)
        if driver is None:
            pending = await self._outbox.reschedule(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
                error=f"selected Agent driver {record.selected_agent!r} is unavailable",
                retry_delay_seconds=retry_delay_seconds,
            )
            return DispatchResult(message=pending, record=record)
        try:
            descriptor = await driver.capabilities()
        except Exception as error:
            pending = await self._outbox.reschedule(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
                error=f"driver capability lookup failed: {type(error).__name__}: {error}",
                retry_delay_seconds=retry_delay_seconds,
            )
            return DispatchResult(message=pending, record=record)

        try:
            selected_candidate = _selected_candidate(record)
        except ValueError as error:
            failed = await self._store.transition(
                record.worker_id,
                expected_revision=record.revision,
                phase=AgentTaskPhase.FAILED,
                error=f"invalid committed Agent selection: {error}",
            )
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=failed,
                error=failed.error or "invalid committed Agent selection",
            )
        required = (
            record.request.selection_plan.required_capabilities
            | selected_candidate.required_capabilities
        )
        if not descriptor.supports(required):
            pending = await self._outbox.reschedule(
                message.outbox_id,
                owner=owner,
                fencing_token=message.fencing_token,
                error="selected Agent no longer satisfies required capabilities",
                retry_delay_seconds=retry_delay_seconds,
            )
            return DispatchResult(message=pending, record=record)

        idempotent_start = AgentCapability.IDEMPOTENT_START in descriptor.capabilities
        if record.dispatch_attempt_count > 0 and not idempotent_start:
            unknown = await self._mark_dispatch_unknown(
                record,
                "an earlier non-idempotent start attempt may have reached the backend; "
                "automatic respawn is forbidden",
            )
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=unknown,
                error=unknown.error or "non-idempotent dispatch outcome is unknown",
            )

        try:
            attempting = await self._store.begin_dispatch(
                record.worker_id,
                expected_revision=record.revision,
            )
        except (InvalidTaskTransition, RevisionConflict) as error:
            latest = await self._store.get(record.worker_id)
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=latest,
                error=f"could not fence Agent dispatch attempt: {error}",
            )

        try:
            start_request = _start_request(
                attempting,
                lease_id=lease_id,
                lease_expires_at=lease_expires_at,
            )
        except ValueError as error:
            failed = await self._store.transition(
                attempting.worker_id,
                expected_revision=attempting.revision,
                phase=AgentTaskPhase.FAILED,
                error=f"invalid committed Agent dispatch: {error}",
            )
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=failed,
                error=failed.error or "invalid committed Agent dispatch",
            )
        try:
            handle = await driver.start(start_request)
        except Exception as error:
            detail = f"backend start failed: {type(error).__name__}: {error}"
            if idempotent_start:
                pending = await self._outbox.reschedule(
                    message.outbox_id,
                    owner=owner,
                    fencing_token=message.fencing_token,
                    error=detail,
                    retry_delay_seconds=retry_delay_seconds,
                )
                return DispatchResult(message=pending, record=attempting)
            unknown = await self._mark_dispatch_unknown(attempting, detail)
            return await self._dead_dispatch(
                message,
                owner=owner,
                record=unknown,
                error=detail,
            )

        try:
            running = await self._store.attach_handle(
                attempting.worker_id,
                expected_revision=attempting.revision,
                handle=handle,
            )
        except (InvalidTaskTransition, RevisionConflict, ValueError) as error:
            latest = await self._store.get(attempting.worker_id)
            if latest is not None and latest.handle == handle:
                running = latest
            else:
                unknown = (
                    await self._mark_dispatch_unknown(
                        latest,
                        f"backend started but handle attachment failed: {error}",
                    )
                    if latest is not None
                    else None
                )
                return await self._dead_dispatch(
                    message,
                    owner=owner,
                    record=unknown,
                    error=f"backend started but handle attachment failed: {error}",
                )

        cursor = await self._events.last_sequence(running.worker_id)
        self._start_event_consumer(driver, handle, after=cursor)
        delivered = await self._outbox.mark_delivered(
            message.outbox_id,
            owner=owner,
            fencing_token=message.fencing_token,
        )
        return DispatchResult(message=delivered, record=running, started=True)

    async def _dead_dispatch(
        self,
        message: OutboxMessage,
        *,
        owner: str,
        record: AgentTaskRecord | None,
        error: str,
    ) -> DispatchResult:
        dead = await self._outbox.reschedule(
            message.outbox_id,
            owner=owner,
            fencing_token=message.fencing_token,
            error=error,
            retry_delay_seconds=0,
            terminal=True,
        )
        return DispatchResult(message=dead, record=record)

    async def _mark_dispatch_unknown(
        self, record: AgentTaskRecord, error: str
    ) -> AgentTaskRecord:
        if record.phase is AgentTaskPhase.UNKNOWN or record.phase.terminal:
            return record
        try:
            return await self._store.transition(
                record.worker_id,
                expected_revision=record.revision,
                phase=AgentTaskPhase.UNKNOWN,
                error=f"{error}; reconciliation required",
            )
        except (InvalidTaskTransition, RevisionConflict):
            return await self._require(record.worker_id)

    def _start_event_consumer(
        self,
        driver: AgentDriver,
        handle: AgentRunHandle,
        *,
        after: int,
    ) -> None:
        existing = self._event_tasks.get(handle.worker_id)
        if existing is not None and not existing.done():
            return
        self._event_tasks[handle.worker_id] = asyncio.create_task(
            self._consume_events(driver, handle, after=after),
            name=f"agent-events-{handle.worker_id}",
        )

    async def _consume_events(
        self,
        driver: AgentDriver,
        handle: AgentRunHandle,
        *,
        after: int,
    ) -> None:
        try:
            async for event in driver.events(handle, after=after):
                if event.worker_id != handle.worker_id or event.locator != handle.locator:
                    raise ValueError("Agent event does not match its supervised run handle")
                await self._ingest_event(event)
                if isinstance(event, AgentRunTerminal):
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            current = await self._store.get(handle.worker_id)
            if current is not None and not current.phase.terminal:
                try:
                    await self._store.transition(
                        current.worker_id,
                        expected_revision=current.revision,
                        phase=AgentTaskPhase.UNKNOWN,
                        error=f"event stream failed: {type(error).__name__}: {error}",
                    )
                except (InvalidTaskTransition, RevisionConflict):
                    pass

    async def _ingest_event(self, event: AgentEvent) -> AgentTaskRecord:
        for _ in range(3):
            try:
                async with self._persistence.unit_of_work() as unit:
                    current = await unit.agent_tasks.get(event.worker_id)
                    if current is None:
                        raise KeyError(event.worker_id)
                    appended = await unit.agent_events.append(event)
                    if not appended.created:
                        return current
                    updated = current
                    if isinstance(event, AgentRunWaiting):
                        if current.phase is AgentTaskPhase.RUNNING:
                            updated = await unit.agent_tasks.transition(
                                current.worker_id,
                                expected_revision=current.revision,
                                phase=AgentTaskPhase.WAITING,
                                blocker=event.reason,
                            )
                            await unit.journal.append(
                                _delegation_waiting_item(updated, event)
                            )
                    elif isinstance(event, AgentRunTerminal):
                        if not current.phase.terminal:
                            updated = await unit.agent_tasks.transition(
                                current.worker_id,
                                expected_revision=current.revision,
                                phase=_terminal_task_phase(event.phase),
                                result=event.result,
                                error=event.error,
                            )
                        terminal_item = await unit.journal.append(
                            _delegation_terminal_item(updated)
                        )
                        await unit.outbox.enqueue(
                            _result_delivery_draft(
                                updated,
                                journal_item=terminal_item.item,
                            )
                        )
                    elif current.phase is AgentTaskPhase.WAITING and isinstance(
                        event,
                        (
                            AgentRunStarted,
                            AgentProgressUpdated,
                            AgentMessageDelta,
                            AgentPlanUpdated,
                        ),
                    ):
                        updated = await unit.agent_tasks.transition(
                            current.worker_id,
                            expected_revision=current.revision,
                            phase=AgentTaskPhase.RUNNING,
                        )
                    return updated
            except RevisionConflict:
                continue
        raise RevisionConflict(
            f"worker {event.worker_id} changed repeatedly during Agent event ingestion"
        )

    async def _require(self, worker_id: str) -> AgentTaskRecord:
        record = await self._store.get(worker_id)
        if record is None:
            raise KeyError(worker_id)
        return record


def _terminal_task_phase(phase: AgentRunPhase) -> AgentTaskPhase:
    return {
        AgentRunPhase.SUCCEEDED: AgentTaskPhase.SUCCEEDED,
        AgentRunPhase.FAILED: AgentTaskPhase.FAILED,
        AgentRunPhase.CANCELLED: AgentTaskPhase.CANCELLED,
        AgentRunPhase.TIMED_OUT: AgentTaskPhase.TIMED_OUT,
    }[phase]


def _dispatch_draft(
    record: AgentTaskRecord,
    *,
    lease_id: str,
    lease_expires_at: datetime,
) -> OutboxMessageDraft:
    if record.dispatch_token is None or record.selected_agent is None:
        raise ValueError("Agent dispatch draft requires a backend-committed task")
    return OutboxMessageDraft(
        tenant_id=record.context.tenant_id,
        aggregate_type="agent_task",
        aggregate_id=record.worker_id,
        message_type=AGENT_DISPATCH_MESSAGE_TYPE,
        dedupe_key=f"agent-dispatch:{record.worker_id}:{record.dispatch_token}",
        payload={
            "worker_id": record.worker_id,
            "dispatch_token": record.dispatch_token,
            "selected_agent": record.selected_agent,
            "workspace_lease_id": lease_id,
            "workspace_fencing_token": 1,
            "workspace_lease_expires_at": lease_expires_at.isoformat(),
        },
    )


def _delegation_requested_item(record: AgentTaskRecord) -> ConversationItemDraft:
    request = record.request
    return ConversationItemDraft(
        item_id=_delegation_item_id(record, "requested"),
        context=record.context,
        kind=ConversationItemKind.DELEGATION_REQUESTED,
        status=ConversationItemStatus.COMMITTED,
        producer="agent-task-supervisor",
        visibility=frozenset(
            {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
        ),
        content=(
            TextContent(request.instruction),
            StructuredContent(
                {
                    "delegation_request_id": request.delegation_request_id,
                    "selection_plan": {
                        "plan_id": request.selection_plan.plan_id,
                        "version": request.selection_plan.version,
                        "candidates": [
                            candidate.agent_name
                            for candidate in request.selection_plan.candidates
                        ],
                    },
                    "selected_agent": record.selected_agent,
                    "workspace_mode": request.workspace_mode.value,
                    "input_refs": list(request.input_refs),
                    "budget": {
                        "max_wall_time_s": request.budget.max_wall_time_s,
                        "max_tokens": request.budget.max_tokens,
                        "max_cost_usd": request.budget.max_cost_usd,
                    },
                }
            ),
        ),
    )


def _delegation_failed_item(
    record: AgentTaskRecord,
    *,
    error: str,
) -> ConversationItemDraft:
    return ConversationItemDraft(
        item_id=_delegation_item_id(record, "selection-failed"),
        context=record.context,
        kind=ConversationItemKind.DELEGATION_RESULT,
        status=ConversationItemStatus.FAILED,
        producer="agent-task-supervisor",
        visibility=frozenset(
            {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
        ),
        content=(StructuredContent({"error": error}),),
        parent_item_id=_delegation_item_id(record, "requested"),
    )


def _delegation_waiting_item(
    record: AgentTaskRecord,
    event: AgentRunWaiting,
) -> ConversationItemDraft:
    return ConversationItemDraft(
        item_id=str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"urn:voiceagent:agent-event:{record.worker_id}:{event.event_id}",
            )
        ),
        context=record.context,
        kind=ConversationItemKind.DELEGATION_PROGRESS,
        status=ConversationItemStatus.IN_PROGRESS,
        producer="agent-task-supervisor",
        visibility=frozenset(
            {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
        ),
        content=(StructuredContent({"phase": "waiting", "reason": event.reason}),),
        parent_item_id=_delegation_item_id(record, "requested"),
        occurred_at=event.occurred_at,
    )


def _delegation_terminal_item(record: AgentTaskRecord) -> ConversationItemDraft:
    if not record.phase.terminal:
        raise ValueError("terminal Conversation Item requires a terminal Agent task")
    status = {
        AgentTaskPhase.SUCCEEDED: ConversationItemStatus.COMPLETED,
        AgentTaskPhase.FAILED: ConversationItemStatus.FAILED,
        AgentTaskPhase.CANCELLED: ConversationItemStatus.CANCELLED,
        AgentTaskPhase.TIMED_OUT: ConversationItemStatus.FAILED,
    }[record.phase]
    summary = record.result if record.phase is AgentTaskPhase.SUCCEEDED else record.error
    content = (
        *((TextContent(summary),) if summary else ()),
        StructuredContent(
            {
                "phase": record.phase.value,
                "result": record.result,
                "error": record.error,
            }
        ),
    )
    return ConversationItemDraft(
        item_id=_delegation_item_id(record, "terminal"),
        context=record.context,
        kind=ConversationItemKind.DELEGATION_RESULT,
        status=status,
        producer="agent-task-supervisor",
        visibility=frozenset(
            {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
        ),
        content=content,
        parent_item_id=_delegation_item_id(record, "requested"),
    )


def _result_delivery_draft(
    record: AgentTaskRecord,
    *,
    journal_item: ConversationItem,
) -> OutboxMessageDraft:
    if not record.phase.terminal:
        raise ValueError("result delivery requires a terminal Agent task")
    return OutboxMessageDraft(
        tenant_id=record.context.tenant_id,
        aggregate_type="agent_task",
        aggregate_id=record.worker_id,
        message_type=AGENT_RESULT_MESSAGE_TYPE,
        dedupe_key=f"agent-result:{record.worker_id}",
        payload={
            "worker_id": record.worker_id,
            "phase": record.phase.value,
            "conversation_item_id": journal_item.item_id,
            "thread_sequence": journal_item.sequence,
        },
    )


def _reconciliation_event_id(
    record: AgentTaskRecord,
    snapshot: AgentRunSnapshot,
) -> str:
    identity = ":".join(
        (
            "urn:voiceagent:agent-reconciliation",
            record.worker_id,
            snapshot.locator.driver_kind,
            snapshot.locator.backend_session_id,
            snapshot.locator.backend_run_id or "",
            str(snapshot.last_event_sequence),
            snapshot.phase.value,
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


def _delegation_item_id(record: AgentTaskRecord, boundary: str) -> str:
    context = record.context
    identity = ":".join(
        (
            "urn:voiceagent:delegation",
            context.tenant_id,
            context.user_id,
            context.thread_id,
            record.delegation_request_id,
            boundary,
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


def _decode_dispatch_message(
    message: OutboxMessage,
) -> tuple[str, str, str, str, datetime]:
    if (
        message.message_type != AGENT_DISPATCH_MESSAGE_TYPE
        or message.schema_version != 1
        or message.aggregate_type != "agent_task"
    ):
        raise ValueError("unsupported message envelope")
    payload = message.payload
    worker_id = payload.get("worker_id")
    dispatch_token = payload.get("dispatch_token")
    selected_agent = payload.get("selected_agent")
    lease_id = payload.get("workspace_lease_id")
    fencing_token = payload.get("workspace_fencing_token")
    expires_at_value = payload.get("workspace_lease_expires_at")
    if any(
        not isinstance(value, str) or not value
        for value in (
            worker_id,
            dispatch_token,
            selected_agent,
            lease_id,
            expires_at_value,
        )
    ):
        raise ValueError("dispatch identity fields must be non-empty strings")
    if worker_id != message.aggregate_id:
        raise ValueError("payload worker_id does not match aggregate_id")
    if type(fencing_token) is not int or fencing_token != 1:
        raise ValueError("unsupported workspace fencing token")
    try:
        expires_at = datetime.fromisoformat(expires_at_value)
    except ValueError as error:
        raise ValueError("workspace lease expiry is not ISO-8601") from error
    if expires_at.tzinfo is None:
        raise ValueError("workspace lease expiry must be timezone-aware")
    return worker_id, dispatch_token, selected_agent, lease_id, expires_at


def _start_request(
    record: AgentTaskRecord,
    *,
    lease_id: str,
    lease_expires_at: datetime,
) -> AgentStartRequest:
    if record.dispatch_token is None:
        raise ValueError("Agent start requires committed selection metadata")
    candidate = _selected_candidate(record)
    request = record.request
    return AgentStartRequest(
        worker_id=record.worker_id,
        dispatch_token=record.dispatch_token,
        instruction=request.instruction,
        context=record.context,
        workspace=WorkspaceLease(
            lease_id=lease_id,
            worker_id=record.worker_id,
            root=request.workspace_root,
            mode=request.workspace_mode,
            fencing_token=1,
            expires_at=lease_expires_at,
            allowed_roots=(request.workspace_root,),
        ),
        model=candidate.model,
        budget={
            "max_wall_time_s": request.budget.max_wall_time_s,
            **(
                {"max_tokens": request.budget.max_tokens}
                if request.budget.max_tokens is not None
                else {}
            ),
            **(
                {"max_cost_usd": request.budget.max_cost_usd}
                if request.budget.max_cost_usd is not None
                else {}
            ),
        },
    )


def _selected_candidate(record: AgentTaskRecord) -> AgentCandidate:
    if record.selected_agent is None or record.selected_candidate_index is None:
        raise ValueError("selection metadata is incomplete")
    try:
        candidate = record.request.selection_plan.candidates[
            record.selected_candidate_index
        ]
    except IndexError as error:
        raise ValueError("selected candidate index is outside the immutable plan") from error
    if candidate.agent_name != record.selected_agent:
        raise ValueError("selected Agent no longer matches immutable plan")
    return candidate
