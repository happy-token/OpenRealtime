"""PostgreSQL Conversation Journal conformer."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from server.conversation_journal import (
    AppendResult,
    ArtifactReferenceContent,
    ConversationItem,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationProjection,
    ConversationVisibility,
    DisplayContent,
    JournalConflict,
    JournalScope,
    SessionConversationPage,
    SpokenContent,
    StructuredContent,
    TextContent,
    ThreadVersionConflict,
)
from server.conversation_journal.journal import (
    validate_recording_query_scope,
    validate_session_window,
)
from server.conversation_journal.models import ConversationContent, utc_now
from server.core.interaction_context import InteractionContext
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name


class PostgresConversationJournal:
    durable = True

    def __init__(self, executor: Any, *, schema: str = "voiceagent") -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._threads = f'"{validated}".conversation_threads'
        self._items = f'"{validated}".conversation_items'

    async def append(
        self,
        draft: ConversationItemDraft,
        *,
        expected_thread_version: int | None = None,
    ) -> AppendResult:
        if expected_thread_version is not None and expected_thread_version < 0:
            raise ValueError("expected_thread_version must be non-negative")
        async with connection_scope(self._executor) as connection, connection.transaction():
            # Serialize identical item identities before allocating a thread
            # sequence. This makes concurrent retries gapless as well as idempotent.
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                draft.item_id,
            )
            existing = await connection.fetchrow(
                f"SELECT * FROM {self._items} WHERE item_id = $1",
                draft.item_id,
            )
            if existing is not None:
                if existing["item_digest"] != draft.item_digest:
                    raise JournalConflict(
                        f"conversation item {draft.item_id!r} was reused with different content"
                    )
                return AppendResult(item=self._item(existing), created=False)

            now = utc_now()
            scope = draft.scope
            await connection.execute(
                f"""
                    INSERT INTO {self._threads} (
                        tenant_id, user_id, thread_id, version, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, 0, $4, $4)
                    ON CONFLICT (tenant_id, user_id, thread_id) DO NOTHING
                    """,
                scope.tenant_id,
                scope.user_id,
                scope.thread_id,
                now,
            )
            version = await connection.fetchval(
                f"""
                    UPDATE {self._threads}
                    SET version = version + 1, updated_at = $4
                    WHERE tenant_id = $1 AND user_id = $2 AND thread_id = $3
                      AND ($5::bigint IS NULL OR version = $5)
                    RETURNING version
                    """,
                scope.tenant_id,
                scope.user_id,
                scope.thread_id,
                now,
                expected_thread_version,
            )
            if version is None:
                actual = await connection.fetchval(
                    f"""
                        SELECT version FROM {self._threads}
                        WHERE tenant_id = $1 AND user_id = $2 AND thread_id = $3
                        """,
                    scope.tenant_id,
                    scope.user_id,
                    scope.thread_id,
                )
                raise ThreadVersionConflict(
                    expected=expected_thread_version or 0,
                    actual=int(actual or 0),
                )

            context = draft.context
            row = await connection.fetchrow(
                f"""
                    INSERT INTO {self._items} (
                        item_id, tenant_id, user_id, device_id, voice_session_id,
                        thread_id, turn_id, generation, response_id, call_id,
                        worker_id, confirmation_id, handoff_id, sequence,
                        schema_version, kind, status, producer, content,
                        display_content, spoken_content, visibility, parent_item_id,
                        provider_metadata, item_digest, occurred_at, recorded_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9, $10,
                        $11, $12, $13, $14,
                        $15, $16, $17, $18, $19::jsonb,
                        $20::jsonb, $21::jsonb, $22::text[], $23,
                        $24::jsonb, $25, $26, $27
                    )
                    RETURNING *
                    """,
                draft.item_id,
                context.tenant_id,
                context.user_id,
                context.device_id,
                context.voice_session_id,
                context.thread_id,
                context.turn_id,
                context.generation,
                context.response_id,
                context.call_id,
                context.worker_id,
                context.confirmation_id,
                context.handoff_id,
                version,
                draft.schema_version,
                draft.kind.value,
                draft.status.value,
                draft.producer,
                _json([part.to_payload() for part in draft.content]),
                _json(draft.display.to_payload()) if draft.display is not None else None,
                _json(draft.spoken.to_payload()) if draft.spoken is not None else None,
                sorted(value.value for value in draft.visibility),
                draft.parent_item_id,
                _json(draft.provider_metadata),
                draft.item_digest,
                draft.occurred_at,
                now,
            )
            if row is None:  # pragma: no cover - INSERT RETURNING contract
                raise RuntimeError("conversation item insert returned no row")
            return AppendResult(item=self._item(row), created=True)

    async def read(
        self,
        scope: JournalScope,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[ConversationItem, ...]:
        _validate_window(after_sequence, limit)
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"""
                SELECT * FROM {self._items}
                WHERE tenant_id = $1 AND user_id = $2 AND thread_id = $3
                  AND sequence > $4
                ORDER BY sequence
                LIMIT $5
                """,
                scope.tenant_id,
                scope.user_id,
                scope.thread_id,
                after_sequence,
                limit,
            )
            return tuple(self._item(row) for row in rows)

    async def thread_version(self, scope: JournalScope) -> int:
        async with connection_scope(self._executor) as connection:
            version = await connection.fetchval(
                f"""
                SELECT version FROM {self._threads}
                WHERE tenant_id = $1 AND user_id = $2 AND thread_id = $3
                """,
                scope.tenant_id,
                scope.user_id,
                scope.thread_id,
            )
            return int(version or 0)

    async def read_session_page(
        self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200,
    ) -> SessionConversationPage:
        validate_session_window(voice_session_id, after_sequence, limit)
        async with asyncio.timeout(4), connection_scope(self._executor) as connection, connection.transaction():
            previous_timeout = await connection.fetchval("SHOW statement_timeout")
            await connection.execute("SELECT set_config('statement_timeout', $1, true)", _session_statement_timeout(previous_timeout))
            rows = await connection.fetch(
                f"""WITH scopes AS MATERIALIZED (
                        SELECT DISTINCT tenant_id, user_id, thread_id FROM {self._items}
                        WHERE voice_session_id = $1 AND kind IN ('user.input', 'assistant.output')
                        ORDER BY tenant_id, user_id, thread_id LIMIT 2
                    ), identity AS (SELECT count(*) AS scope_count FROM scopes)
                    SELECT identity.scope_count, page.* FROM identity
                    LEFT JOIN LATERAL (
                        SELECT item.* FROM {self._items} item
                        JOIN scopes s ON item.tenant_id = s.tenant_id AND item.user_id = s.user_id AND item.thread_id = s.thread_id
                        WHERE identity.scope_count = 1 AND item.voice_session_id = $1
                          AND item.kind IN ('user.input', 'assistant.output') AND item.sequence > $2
                        ORDER BY item.sequence LIMIT $3
                    ) page ON true ORDER BY page.sequence""",
                voice_session_id, after_sequence, limit + 1,
            )
            # A nested SAVEPOINT retains successful SET LOCAL changes in
            # its caller's transaction unless explicitly restored.
            await connection.execute("SELECT set_config('statement_timeout', $1, true)", previous_timeout)
            if rows[0]["scope_count"] > 1:
                raise ValueError("session conversation identity is ambiguous")
            if rows[0]["item_id"] is None:
                return SessionConversationPage((), None)
            page = tuple(self._item(row) for row in rows[:limit])
            return SessionConversationPage(page, page[-1].sequence if len(rows) > limit else None)

    async def _recording_items(
        self, session_id: str, after_sequence: int, limit: int, artifact_id: str | None = None,
    ) -> tuple[ConversationItem, ...]:
        async with asyncio.timeout(4), connection_scope(self._executor) as connection, connection.transaction():
            previous = await connection.fetchval("SHOW statement_timeout")
            await connection.execute("SELECT set_config('statement_timeout', $1, true)", _session_statement_timeout(previous))
            rows = await connection.fetch(f"""
                WITH recording_scopes AS MATERIALIZED (
                    SELECT DISTINCT tenant_id, user_id, thread_id FROM {self._items}
                    WHERE voice_session_id=$1 AND producer='voice-session-recording'
                    ORDER BY tenant_id,user_id,thread_id LIMIT 2
                ), dialogue_scopes AS MATERIALIZED (
                    SELECT DISTINCT tenant_id, user_id, thread_id FROM {self._items}
                    WHERE voice_session_id=$1 AND kind IN ('user.input','assistant.output')
                    ORDER BY tenant_id,user_id,thread_id LIMIT 2
                ), identity AS (
                    SELECT (SELECT count(*) FROM recording_scopes) AS recording_count,
                           (SELECT count(*) FROM dialogue_scopes) AS dialogue_count
                ) SELECT identity.*, r.tenant_id AS rt, r.user_id AS ru, r.thread_id AS rh,
                         d.tenant_id AS dt, d.user_id AS du, d.thread_id AS dh, page.*
                FROM identity LEFT JOIN recording_scopes r ON true LEFT JOIN dialogue_scopes d ON true
                LEFT JOIN LATERAL (
                    SELECT item.* FROM {self._items} item
                    WHERE identity.recording_count=1 AND identity.dialogue_count<=1
                        AND item.tenant_id=r.tenant_id AND item.user_id=r.user_id AND item.thread_id=r.thread_id
                        AND item.voice_session_id=$1 AND item.producer='voice-session-recording'
                        AND item.sequence>$2 AND ($4::jsonb IS NULL OR item.content @> $4::jsonb)
                    ORDER BY item.sequence LIMIT $3
                ) page ON true ORDER BY page.sequence
                """, session_id, after_sequence, limit,
                _json([{"type": "artifact_reference", "artifact_id": artifact_id}]) if artifact_id is not None else None)
            await connection.execute("SELECT set_config('statement_timeout', $1, true)", previous)
            if rows[0]["recording_count"] > 1 or rows[0]["dialogue_count"] > 1:
                raise ValueError("session recording identity is ambiguous")
            row = rows[0]
            validate_recording_query_scope(session_id, [JournalScope(row["rt"],row["ru"],row["rh"])] if row["rt"] is not None else [],
                                            [JournalScope(row["dt"],row["du"],row["dh"])] if row["dt"] is not None else [])
            return tuple(self._item(row) for row in rows if row["item_id"] is not None)

    async def read_recording_page(self, voice_session_id: str, *, after_sequence: int = 0, limit: int = 200) -> SessionConversationPage:
        validate_session_window(voice_session_id, after_sequence, limit)
        rows = await self._recording_items(voice_session_id, after_sequence, limit + 1)
        page = rows[:limit]
        return SessionConversationPage(page, page[-1].sequence if len(rows)>limit else None)

    async def find_recording_artifact(self, voice_session_id: str, artifact_id: str) -> ConversationItem | None:
        validate_session_window(voice_session_id, 0, 1)
        if not artifact_id or len(artifact_id) > 128:
            raise ValueError("invalid recording artifact identity")
        rows = await self._recording_items(voice_session_id, 0, 2, artifact_id)
        if len(rows)>1:
            raise ValueError("recording artifact reference is ambiguous")
        return rows[0] if rows else None

    async def delete_threads(self, scopes: Sequence[JournalScope]) -> int:
        return await self._delete_threads(scopes)

    async def delete_session_owned_threads(self, scopes: Sequence[JournalScope], voice_session_ids: Sequence[str]) -> int:
        return await self._delete_threads(scopes, allowed_sessions=voice_session_ids)

    async def _delete_threads(self, scopes: Sequence[JournalScope], *, allowed_sessions: Sequence[str] | None = None) -> int:
        selected = tuple(dict.fromkeys(scopes))
        if not selected:
            return 0
        tenant_ids = [scope.tenant_id for scope in selected]
        user_ids = [scope.user_id for scope in selected]
        thread_ids = [scope.thread_id for scope in selected]
        async with (
            connection_scope(self._executor) as connection,
            connection.transaction(),
        ):
            if allowed_sessions is not None:
                owned = []
                for scope in sorted(selected, key=lambda value: (value.tenant_id, value.user_id, value.thread_id)):
                    # Append increments this same row before inserting an item. Hold its lock
                    # through both the ownership check and deletion to exclude concurrent writes.
                    version = await connection.fetchval(
                        f"SELECT version FROM {self._threads} WHERE tenant_id=$1 AND user_id=$2 AND thread_id=$3 FOR UPDATE",
                        scope.tenant_id, scope.user_id, scope.thread_id,
                    )
                    if version is None:
                        continue
                    shared = await connection.fetchval(
                        f"SELECT EXISTS (SELECT 1 FROM {self._items} WHERE tenant_id=$1 AND user_id=$2 AND thread_id=$3 AND NOT (voice_session_id = ANY($4::text[])))",
                        scope.tenant_id, scope.user_id, scope.thread_id, list(allowed_sessions),
                    )
                    if not shared:
                        owned.append(scope)
                if not owned:
                    return 0
                tenant_ids = [scope.tenant_id for scope in owned]
                user_ids = [scope.user_id for scope in owned]
                thread_ids = [scope.thread_id for scope in owned]
            await connection.execute(
                f"""
                DELETE FROM {self._items}
                WHERE (tenant_id, user_id, thread_id) IN (
                    SELECT * FROM unnest($1::text[], $2::text[], $3::text[])
                )
                """,
                tenant_ids,
                user_ids,
                thread_ids,
            )
            rows = await connection.fetch(
                f"""
                DELETE FROM {self._threads}
                WHERE (tenant_id, user_id, thread_id) IN (
                    SELECT * FROM unnest($1::text[], $2::text[], $3::text[])
                )
                RETURNING thread_id
                """,
                tenant_ids,
                user_ids,
                thread_ids,
            )
        return len(rows)

    async def project_for_model(
        self,
        scope: JournalScope,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> ConversationProjection:
        items = await self.read(
            scope,
            after_sequence=after_sequence,
            limit=limit,
        )
        return ConversationProjection(
            scope=scope,
            items=tuple(
                item for item in items if ConversationVisibility.MODEL in item.visibility
            ),
            thread_version=await self.thread_version(scope),
        )

    def _item(self, row: Mapping[str, Any]) -> ConversationItem:
        content = _decode_content(_decoded_json(row["content"]))
        provider_metadata = _decoded_json(row["provider_metadata"])
        if not isinstance(provider_metadata, dict):
            raise ValueError("provider_metadata must decode to an object")
        context = InteractionContext(
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            device_id=row["device_id"],
            voice_session_id=row["voice_session_id"],
            thread_id=row["thread_id"],
            turn_id=row["turn_id"],
            generation=row["generation"],
            response_id=row["response_id"],
            call_id=row["call_id"],
            worker_id=row["worker_id"],
            confirmation_id=row["confirmation_id"],
            handoff_id=row["handoff_id"],
        )
        return ConversationItem(
            item_id=row["item_id"],
            context=context,
            kind=ConversationItemKind(row["kind"]),
            status=ConversationItemStatus(row["status"]),
            producer=row["producer"],
            content=content,
            display=_decode_display_content(row["display_content"]),
            spoken=_decode_spoken_content(row["spoken_content"]),
            visibility=frozenset(
                ConversationVisibility(value) for value in row["visibility"]
            ),
            parent_item_id=row["parent_item_id"],
            provider_metadata=provider_metadata,
            schema_version=row["schema_version"],
            occurred_at=row["occurred_at"],
            recorded_at=row["recorded_at"],
            sequence=row["sequence"],
            thread_version=row["sequence"],
            item_digest=row["item_digest"],
        )


def _decode_content(value: Any) -> tuple[ConversationContent, ...]:
    if not isinstance(value, list):
        raise ValueError("conversation content must decode to an array")
    parts: list[ConversationContent] = []
    for payload in value:
        if not isinstance(payload, dict):
            raise ValueError("conversation content part must be an object")
        part_type = payload.get("type")
        if part_type == "text":
            parts.append(TextContent(payload["text"], language=payload.get("language")))
        elif part_type == "structured":
            parts.append(StructuredContent(payload["value"]))
        elif part_type == "artifact_reference":
            parts.append(
                ArtifactReferenceContent(
                    artifact_id=payload["artifact_id"],
                    media_type=payload["media_type"],
                    size_bytes=payload["size_bytes"],
                    sha256=payload["sha256"],
                )
            )
        else:
            raise ValueError(f"unsupported conversation content type: {part_type!r}")
    return tuple(parts)


def _decode_display_content(value: Any) -> DisplayContent | None:
    if value is None:
        return None
    payload = _decoded_json(value)
    if not isinstance(payload, dict) or not isinstance(payload.get("markdown"), str):
        raise ValueError("display_content must decode to an object with markdown")
    return DisplayContent(markdown=payload["markdown"])


def _decode_spoken_content(value: Any) -> SpokenContent | None:
    if value is None:
        return None
    payload = _decoded_json(value)
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise ValueError("spoken_content must decode to an object with text")
    language = payload.get("language")
    if language is not None and not isinstance(language, str):
        raise ValueError("spoken_content language must be a string when provided")
    return SpokenContent(text=payload["text"], language=language)


def _decoded_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _session_statement_timeout(previous: str) -> str:
    match = re.fullmatch(r"([0-9]+)(ms|s|min|h|d)?", previous)
    if match is None:
        raise ValueError("unsupported statement timeout format")
    milliseconds = int(match[1]) * {None: 1, "ms": 1, "s": 1000, "min": 60_000, "h": 3_600_000, "d": 86_400_000}[match[2]]
    return str(min(milliseconds, 3000) if milliseconds else 3000)


def _validate_window(after_sequence: int, limit: int) -> None:
    if after_sequence < 0:
        raise ValueError("after_sequence must be non-negative")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
