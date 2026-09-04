"""Deterministic persistence conformers for orchestration tests.

Production correctness comes from the PostgreSQL implementation.  This module
models the same repository surface and lease/fencing behavior without claiming
crash durability or PostgreSQL transaction isolation.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta

from server.agent_session.driver_protocol import utc_now
from server.agent_session.event_store import InMemoryAgentEventStore
from server.agent_session.task_store import InMemoryAgentTaskStore
from server.conversation_journal import InMemoryConversationJournal
from server.persistence.outbox import (
    OutboxConflict,
    OutboxLeaseLost,
    OutboxMessage,
    OutboxMessageDraft,
    OutboxStatus,
)
from server.persistence.unit_of_work import PersistenceUnitOfWork
from server.tools.policy_gateway import InMemoryToolAuthorizationStore


class InMemoryOutboxStore:
    def __init__(self, *, outbox_id_factory: Callable[[], str] | None = None) -> None:
        self._outbox_id_factory = outbox_id_factory or (lambda: str(uuid.uuid4()))
        self._messages: dict[str, OutboxMessage] = {}
        self._dedupe: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, draft: OutboxMessageDraft) -> OutboxMessage:
        key = (draft.tenant_id, draft.dedupe_key)
        async with self._lock:
            existing_id = self._dedupe.get(key)
            if existing_id is not None:
                existing = self._messages[existing_id]
                if (
                    existing.payload_digest != draft.payload_digest
                    or existing.message_type != draft.message_type
                    or existing.schema_version != draft.schema_version
                    or existing.aggregate_type != draft.aggregate_type
                    or existing.aggregate_id != draft.aggregate_id
                ):
                    raise OutboxConflict(
                        "outbox dedupe_key was reused with different content"
                    )
                return existing
            outbox_id = self._outbox_id_factory()
            if not outbox_id or outbox_id in self._messages:
                raise ValueError("outbox_id_factory returned an invalid or duplicate id")
            now = utc_now()
            message = OutboxMessage(
                outbox_id=outbox_id,
                tenant_id=draft.tenant_id,
                aggregate_type=draft.aggregate_type,
                aggregate_id=draft.aggregate_id,
                message_type=draft.message_type,
                dedupe_key=draft.dedupe_key,
                payload=dict(draft.payload),
                payload_digest=draft.payload_digest,
                schema_version=draft.schema_version,
                status=OutboxStatus.PENDING,
                available_at=draft.available_at,
                attempt_count=0,
                fencing_token=0,
                created_at=now,
                updated_at=now,
            )
            self._messages[outbox_id] = message
            self._dedupe[key] = outbox_id
            return message

    async def claim(
        self,
        *,
        owner: str,
        limit: int,
        lease_seconds: float,
        message_types: frozenset[str] | None = None,
    ) -> tuple[OutboxMessage, ...]:
        if not owner:
            raise ValueError("Outbox lease owner must be non-empty")
        if limit < 1 or lease_seconds <= 0:
            raise ValueError("Outbox claim limit and lease_seconds must be positive")
        if message_types is not None and not message_types:
            return ()
        async with self._lock:
            now = utc_now()
            candidates = sorted(
                (
                    message
                    for message in self._messages.values()
                    if (
                        message.status is OutboxStatus.PENDING
                        and message.available_at <= now
                    )
                    or (
                        message.status is OutboxStatus.LEASED
                        and message.lease_expires_at is not None
                        and message.lease_expires_at <= now
                    )
                ),
                key=lambda message: (
                    message.available_at,
                    message.created_at,
                    message.outbox_id,
                ),
            )
            claimed: list[OutboxMessage] = []
            for message in candidates:
                if message_types is not None and message.message_type not in message_types:
                    continue
                updated = replace(
                    message,
                    status=OutboxStatus.LEASED,
                    lease_owner=owner,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    attempt_count=message.attempt_count + 1,
                    fencing_token=message.fencing_token + 1,
                    updated_at=now,
                )
                self._messages[message.outbox_id] = updated
                claimed.append(updated)
                if len(claimed) == limit:
                    break
            return tuple(claimed)

    async def mark_delivered(
        self, outbox_id: str, *, owner: str, fencing_token: int
    ) -> OutboxMessage:
        async with self._lock:
            message = self._expect_lease(outbox_id, owner, fencing_token)
            now = utc_now()
            updated = replace(
                message,
                status=OutboxStatus.DELIVERED,
                lease_owner=None,
                lease_expires_at=None,
                delivered_at=now,
                updated_at=now,
            )
            self._messages[outbox_id] = updated
            return updated

    async def reschedule(
        self,
        outbox_id: str,
        *,
        owner: str,
        fencing_token: int,
        error: str,
        retry_delay_seconds: float,
        terminal: bool = False,
    ) -> OutboxMessage:
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        async with self._lock:
            message = self._expect_lease(outbox_id, owner, fencing_token)
            now = utc_now()
            updated = replace(
                message,
                status=OutboxStatus.DEAD if terminal else OutboxStatus.PENDING,
                available_at=(
                    message.available_at
                    if terminal
                    else now + timedelta(seconds=retry_delay_seconds)
                ),
                lease_owner=None,
                lease_expires_at=None,
                last_error=error,
                updated_at=now,
            )
            self._messages[outbox_id] = updated
            return updated

    def _expect_lease(
        self, outbox_id: str, owner: str, fencing_token: int
    ) -> OutboxMessage:
        message = self._messages.get(outbox_id)
        if (
            message is None
            or message.status is not OutboxStatus.LEASED
            or message.lease_owner != owner
            or message.fencing_token != fencing_token
        ):
            raise OutboxLeaseLost(outbox_id)
        return message


class InMemoryPersistence:
    def __init__(
        self,
        *,
        agent_tasks: InMemoryAgentTaskStore | None = None,
        outbox: InMemoryOutboxStore | None = None,
        journal: InMemoryConversationJournal | None = None,
        agent_events: InMemoryAgentEventStore | None = None,
        tool_authorizations: InMemoryToolAuthorizationStore | None = None,
    ) -> None:
        self.agent_tasks = agent_tasks or InMemoryAgentTaskStore()
        self.outbox = outbox or InMemoryOutboxStore()
        self.journal = journal or InMemoryConversationJournal()
        self.agent_events = agent_events or InMemoryAgentEventStore()
        self.tool_authorizations = (
            tool_authorizations or InMemoryToolAuthorizationStore()
        )
        self._transaction_lock = asyncio.Lock()

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[PersistenceUnitOfWork]:
        async with self._transaction_lock:
            yield PersistenceUnitOfWork(
                agent_tasks=self.agent_tasks,
                outbox=self.outbox,
                journal=self.journal,
                agent_events=self.agent_events,
                tool_authorizations=self.tool_authorizations,
            )
