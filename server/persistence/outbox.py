"""Transactional Outbox domain contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from server.agent_session.driver_protocol import utc_now


class OutboxStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    DELIVERED = "delivered"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class OutboxMessageDraft:
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    message_type: str
    dedupe_key: str
    payload: dict[str, Any]
    schema_version: int = 1
    available_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.tenant_id,
                self.aggregate_type,
                self.aggregate_id,
                self.message_type,
                self.dedupe_key,
            )
        ):
            raise ValueError("Outbox identity fields must be non-empty")
        if self.schema_version < 1:
            raise ValueError("Outbox schema_version must be positive")
        if self.available_at.tzinfo is None:
            raise ValueError("Outbox available_at must be timezone-aware")

    @property
    def payload_json(self) -> str:
        return json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def payload_digest(self) -> str:
        return hashlib.sha256(self.payload_json.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    outbox_id: str
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    message_type: str
    dedupe_key: str
    payload: dict[str, Any]
    payload_digest: str
    schema_version: int
    status: OutboxStatus
    available_at: datetime
    attempt_count: int
    fencing_token: int
    created_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    delivered_at: datetime | None = None


class OutboxConflict(RuntimeError):
    pass


class OutboxLeaseLost(RuntimeError):
    pass


class OutboxStore(Protocol):
    async def enqueue(self, draft: OutboxMessageDraft) -> OutboxMessage: ...

    async def claim(
        self,
        *,
        owner: str,
        limit: int,
        lease_seconds: float,
        message_types: frozenset[str] | None = None,
    ) -> tuple[OutboxMessage, ...]: ...

    async def mark_delivered(
        self, outbox_id: str, *, owner: str, fencing_token: int
    ) -> OutboxMessage: ...

    async def reschedule(
        self,
        outbox_id: str,
        *,
        owner: str,
        fencing_token: int,
        error: str,
        retry_delay_seconds: float,
        terminal: bool = False,
    ) -> OutboxMessage: ...
