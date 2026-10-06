"""Durable Agent delegation admission for Realtime Engine proposals."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from server.agent_session.supervisor import TaskSubmission
from server.agent_session.task_models import DelegationRequest
from server.core.interaction_context import InteractionContext
from server.realtime.protocol import (
    AgentDelegationRequested,
    AgentDelegationRequestProposed,
    ProjectCommittedItem,
    RealtimeCapabilityFailed,
    RealtimeCommand,
    RealtimeConversation,
    RealtimeEvent,
)
from server.realtime.protocol.engine import is_output_deliverable
from server.realtime.scope import conversation_scope

_CLOSED = object()


class AgentTaskSubmitter(Protocol):
    async def submit(self, request: DelegationRequest) -> TaskSubmission: ...


DelegationRequestFactory = Callable[
    [AgentDelegationRequestProposed], DelegationRequest
]


class RealtimeDelegationController:
    """Commit Agent work through the sole Supervisor authority before exposure."""

    def __init__(
        self,
        *,
        context: InteractionContext,
        conversation: RealtimeConversation,
        committed_projection: RealtimeConversation,
        supervisor: AgentTaskSubmitter,
        request_factory: DelegationRequestFactory,
    ) -> None:
        self._context = context
        self._conversation = conversation
        self._committed_projection = committed_projection
        self._supervisor = supervisor
        self._request_factory = request_factory
        self._events: asyncio.Queue[RealtimeEvent | object] = asyncio.Queue()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._seen_event_ids: set[str] = set()
        self._closed = False
        self._pump_task = asyncio.create_task(
            self._pump_events(),
            name=f"realtime-delegation-{context.voice_session_id}",
        )

    async def send(self, command: RealtimeCommand) -> None:
        if self._closed:
            raise RuntimeError("realtime delegation controller is closed")
        if conversation_scope(command.context) != conversation_scope(self._context):
            raise ValueError("command belongs to a different realtime conversation scope")
        await self._conversation.send(command)

    async def _pump_events(self) -> None:
        try:
            async for event in self._conversation.events():
                if not self.output_delivery_allowed(event):
                    continue
                if isinstance(event, AgentDelegationRequestProposed):
                    self._start_submission(event)
                    continue
                await self._events.put(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - decorator failure is public
            await self._emit_failure(self._context, error)
        finally:
            await self._events.put(_CLOSED)

    def _start_submission(self, event: AgentDelegationRequestProposed) -> None:
        if event.event_id in self._seen_event_ids:
            return
        self._seen_event_ids.add(event.event_id)
        task = asyncio.create_task(
            self._submit(event),
            name=f"realtime-delegation-submit-{event.delegation_request_id}",
        )
        self._tasks[event.event_id] = task

    async def _submit(self, event: AgentDelegationRequestProposed) -> None:
        try:
            if not self.output_delivery_allowed(event):
                return
            request = self._request_factory(event)
            if request.delegation_request_id != event.delegation_request_id:
                raise ValueError(
                    "delegation request factory changed the proposal identity"
                )
            if conversation_scope(request.context) != conversation_scope(event.context):
                raise ValueError("delegation request belongs to a different scope")
            submission = await self._supervisor.submit(request)
            if not submission.create_result.created:
                return
            for item in submission.committed_items:
                await self._committed_projection.send(
                    ProjectCommittedItem(
                        command_id=f"project-agent-item:{item.item_id}:{item.sequence}",
                        idempotency_key=f"project:{item.item_id}:{item.sequence}",
                        context=item.context,
                        item=item,
                    )
                )
            await self._events.put(
                AgentDelegationRequested(
                    event_id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"urn:openrealtime:delegation:{submission.record.worker_id}",
                        )
                    ),
                    context=submission.record.context,
                    conversation_sequence=event.conversation_sequence + 1,
                    occurred_at=submission.record.created_at,
                    response_id=event.response_id,
                    response_sequence=event.response_sequence + 1,
                    worker_id=submission.record.worker_id,
                    instruction=submission.record.request.instruction,
                    agent_name=submission.record.selected_agent,
                )
            )
        except Exception as error:  # noqa: BLE001 - admission failure is public
            await self._emit_failure(event.context, error)
        finally:
            self._tasks.pop(event.event_id, None)

    async def _emit_failure(
        self, context: InteractionContext, error: Exception
    ) -> None:
        await self._events.put(
            RealtimeCapabilityFailed(
                event_id=str(uuid.uuid4()),
                context=context,
                conversation_sequence=1,
                occurred_at=datetime.now(UTC),
                capability="realtime_delegation_controller",
                error=f"{type(error).__name__}: {error}",
            )
        )

    def events(self) -> AsyncIterator[RealtimeEvent]:
        return self._iterate_events()

    def output_delivery_allowed(self, event: RealtimeEvent) -> bool:
        return is_output_deliverable(self._conversation, event)

    async def _iterate_events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._events.get()
            if event is _CLOSED:
                return
            typed_event = cast(RealtimeEvent, event)
            if self.output_delivery_allowed(typed_event):
                yield typed_event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = tuple(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._conversation.close()
        await self._pump_task
