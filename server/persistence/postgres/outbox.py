"""PostgreSQL Transactional Outbox conformer."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from server.agent_session.driver_protocol import utc_now
from server.persistence.outbox import (
    OutboxConflict,
    OutboxLeaseLost,
    OutboxMessage,
    OutboxMessageDraft,
    OutboxStatus,
    OutboxStore,
)
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name


class PostgresOutboxStore(OutboxStore):
    def __init__(
        self,
        executor: Any,
        *,
        schema: str = "voiceagent",
        outbox_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._table = f'"{validated}".outbox_messages'
        self._outbox_id_factory = outbox_id_factory or (lambda: str(uuid.uuid4()))

    async def enqueue(self, draft: OutboxMessageDraft) -> OutboxMessage:
        outbox_id = self._outbox_id_factory()
        if not outbox_id:
            raise ValueError("outbox_id_factory returned an empty outbox_id")
        now = utc_now()
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    f"""
                    INSERT INTO {self._table} (
                        outbox_id, tenant_id, aggregate_type, aggregate_id,
                        message_type, schema_version, dedupe_key, payload,
                        payload_digest, status, available_at, attempt_count,
                        fencing_token, created_at, updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8::jsonb,
                        $9, 'pending', $10, 0, 0, $11, $11
                    )
                    ON CONFLICT (tenant_id, dedupe_key) DO NOTHING
                    RETURNING *
                    """,
                    outbox_id,
                    draft.tenant_id,
                    draft.aggregate_type,
                    draft.aggregate_id,
                    draft.message_type,
                    draft.schema_version,
                    draft.dedupe_key,
                    draft.payload_json,
                    draft.payload_digest,
                    draft.available_at,
                    now,
                )
                if row is None:
                    row = await connection.fetchrow(
                        f"""
                        SELECT * FROM {self._table}
                        WHERE tenant_id = $1 AND dedupe_key = $2
                        """,
                        draft.tenant_id,
                        draft.dedupe_key,
                    )
                    if row is None:
                        raise RuntimeError("Outbox dedupe row disappeared")
                    if (
                        row["payload_digest"] != draft.payload_digest
                        or row["message_type"] != draft.message_type
                        or row["schema_version"] != draft.schema_version
                        or row["aggregate_type"] != draft.aggregate_type
                        or row["aggregate_id"] != draft.aggregate_id
                    ):
                        raise OutboxConflict("outbox dedupe_key was reused with different content")
                return self._message(row)

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
        async with connection_scope(self._executor) as connection:
            async with connection.transaction():
                rows = await connection.fetch(
                    f"""
                    WITH claimable AS (
                        SELECT outbox_id
                        FROM {self._table}
                        WHERE (
                            (
                                status = 'pending'
                                AND available_at <= clock_timestamp()
                            ) OR (
                                status = 'leased'
                                AND lease_expires_at <= clock_timestamp()
                            )
                        )
                        AND ($4::text[] IS NULL OR message_type = ANY($4::text[]))
                        ORDER BY available_at, created_at, outbox_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT $1
                    )
                    UPDATE {self._table} AS messages
                    SET status = 'leased', lease_owner = $2,
                        lease_expires_at = clock_timestamp()
                            + make_interval(secs => $3),
                        attempt_count = messages.attempt_count + 1,
                        fencing_token = messages.fencing_token + 1,
                        updated_at = clock_timestamp()
                    FROM claimable
                    WHERE messages.outbox_id = claimable.outbox_id
                    RETURNING messages.*
                    """,
                    limit,
                    owner,
                    lease_seconds,
                    sorted(message_types) if message_types is not None else None,
                )
                return tuple(self._message(row) for row in rows)

    async def mark_delivered(
        self, outbox_id: str, *, owner: str, fencing_token: int
    ) -> OutboxMessage:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                UPDATE {self._table}
                SET status = 'delivered', delivered_at = clock_timestamp(),
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = clock_timestamp()
                WHERE outbox_id = $1 AND status = 'leased'
                  AND lease_owner = $2 AND fencing_token = $3
                RETURNING *
                """,
                outbox_id,
                owner,
                fencing_token,
            )
            if row is None:
                raise OutboxLeaseLost(outbox_id)
            return self._message(row)

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
        status = OutboxStatus.DEAD if terminal else OutboxStatus.PENDING
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                UPDATE {self._table}
                SET status = $4,
                    available_at = CASE
                        WHEN $4 = 'pending' THEN clock_timestamp()
                            + make_interval(secs => $5)
                        ELSE available_at
                    END,
                    lease_owner = NULL, lease_expires_at = NULL,
                    last_error = $6, updated_at = clock_timestamp()
                WHERE outbox_id = $1 AND status = 'leased'
                  AND lease_owner = $2 AND fencing_token = $3
                RETURNING *
                """,
                outbox_id,
                owner,
                fencing_token,
                status.value,
                retry_delay_seconds,
                error,
            )
            if row is None:
                raise OutboxLeaseLost(outbox_id)
            return self._message(row)

    def _message(self, row: Mapping[str, Any]) -> OutboxMessage:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError("Outbox payload must decode to an object")
        return OutboxMessage(
            outbox_id=row["outbox_id"],
            tenant_id=row["tenant_id"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            message_type=row["message_type"],
            dedupe_key=row["dedupe_key"],
            payload=payload,
            payload_digest=row["payload_digest"],
            schema_version=row["schema_version"],
            status=OutboxStatus(row["status"]),
            available_at=row["available_at"],
            attempt_count=row["attempt_count"],
            fencing_token=row["fencing_token"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            last_error=row["last_error"],
            delivered_at=row["delivered_at"],
        )
