"""Metadata-only Session preservation, shared by Artifact transactions and composition."""

from __future__ import annotations

import json
from typing import Any

from server.agent_session.driver_protocol import utc_now
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactCreateRequest,
    SessionRecordingPreservation,
    recording_preservation_applies,
    validate_recording_preservation,
)
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name


async def lock_session_recordings(
    connection: Any, schema: str, scope: ArtifactAccessScope, session_id: str
) -> None:
    """One source lock; include schema and unambiguous original identity in its key."""
    key = json.dumps([validate_schema_name(schema), scope.tenant_id, scope.owner_id, session_id])
    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", key)


class PostgresRecordingPreservation:
    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        self._schema = validate_schema_name(schema)
        self._policies = f'"{self._schema}".session_recording_preservation'
        self._artifacts = f'"{self._schema}".artifacts'
        self._intents = f'"{self._schema}".artifact_cleanup_intents'

    async def request_preserved(self, connection: Any, request: ArtifactCreateRequest) -> bool:
        if request.source_kind != "voice_session_recording":
            return False
        marked_at = await connection.fetchval(
            f"SELECT marked_at FROM {self._policies} WHERE tenant_id=$1 AND owner_id=$2 AND voice_session_id=$3",
            request.tenant_id,
            request.owner_id,
            request.source_id,
        )
        return marked_at is not None and recording_preservation_applies(request, marked_at)

    async def lock_request(self, connection: Any, request: ArtifactCreateRequest) -> None:
        if request.source_kind == "voice_session_recording":
            await lock_session_recordings(
                connection,
                self._schema,
                ArtifactAccessScope(request.tenant_id, request.owner_id),
                request.source_id,
            )

    async def _state(
        self, connection: Any, scope: ArtifactAccessScope, session_id: str
    ) -> SessionRecordingPreservation | None:
        row = await connection.fetchrow(
            f"""
            SELECT p.marked_at, p.actor_id,
                COUNT(a.artifact_id) AS total,
                COUNT(a.artifact_id) FILTER (WHERE a.phase='available' AND a.immutable) AS preserved,
                COUNT(a.artifact_id) FILTER (WHERE a.phase='staging' AND a.retention_until > p.marked_at) AS pending
            FROM {self._policies} p LEFT JOIN {self._artifacts} a
                ON a.tenant_id=p.tenant_id AND a.owner_id=p.owner_id
                AND a.source_kind='voice_session_recording' AND a.source_id=p.voice_session_id
            WHERE p.tenant_id=$1 AND p.owner_id=$2 AND p.voice_session_id=$3
            GROUP BY p.marked_at, p.actor_id
        """,
            scope.tenant_id,
            scope.owner_id,
            session_id,
        )
        if row is None:
            return None
        return SessionRecordingPreservation(
            session_id,
            row["marked_at"],
            row["actor_id"],
            row["preserved"],
            row["pending"],
            row["total"] - row["preserved"] - row["pending"],
        )

    async def get_session_preservation_for(
        self, scope: ArtifactAccessScope, session_id: str
    ) -> SessionRecordingPreservation | None:
        validate_recording_preservation(session_id)
        async with connection_scope(self._executor) as connection:
            return await self._state(connection, scope, session_id)

    async def preserve_session_for(
        self, scope: ArtifactAccessScope, session_id: str, *, actor_id: str
    ) -> SessionRecordingPreservation:
        if actor_id is None:
            raise ValueError("invalid recording preservation actor")
        validate_recording_preservation(session_id, actor_id)
        async with connection_scope(self._executor) as connection, connection.transaction():
            await lock_session_recordings(connection, self._schema, scope, session_id)
            await connection.execute(
                f"""
                INSERT INTO {self._policies} (tenant_id,owner_id,voice_session_id,marked_at,actor_id)
                VALUES ($1,$2,$3,$4,$5) ON CONFLICT (tenant_id,owner_id,voice_session_id) DO NOTHING
            """,
                scope.tenant_id,
                scope.owner_id,
                session_id,
                utc_now(),
                actor_id,
            )
            await connection.execute(
                f"""
                UPDATE {self._artifacts} a SET immutable=true, revision=revision+1, updated_at=$4
                FROM {self._policies} p
                WHERE p.tenant_id=$1 AND p.owner_id=$2 AND p.voice_session_id=$3
                  AND a.tenant_id=p.tenant_id AND a.owner_id=p.owner_id
                  AND a.source_kind='voice_session_recording' AND a.source_id=p.voice_session_id
                  AND a.phase='available' AND NOT a.immutable AND a.retention_until > p.marked_at
            """,
                scope.tenant_id,
                scope.owner_id,
                session_id,
                utc_now(),
            )
            # Protect eligible staging without changing upload CAS revisions.
            await connection.execute(
                f"""
                UPDATE {self._intents} c SET phase='cancelled', failure_reason=NULL, updated_at=$4
                FROM {self._artifacts} a, {self._policies} p
                WHERE p.tenant_id=$1 AND p.owner_id=$2 AND p.voice_session_id=$3
                  AND a.tenant_id=p.tenant_id AND a.owner_id=p.owner_id
                  AND a.source_kind='voice_session_recording' AND a.source_id=p.voice_session_id
                  AND a.phase IN ('staging','available')
                  AND (a.immutable OR a.retention_until > p.marked_at)
                  AND c.artifact_id=a.artifact_id AND c.phase='pending'
            """,
                scope.tenant_id,
                scope.owner_id,
                session_id,
                utc_now(),
            )
            state = await self._state(connection, scope, session_id)
            assert state is not None
            return state
