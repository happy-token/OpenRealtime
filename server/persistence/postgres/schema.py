"""Explicit migration loading for PostgreSQL adapters.

Production startup must not run migrations implicitly. ``apply_migrations`` is
provided for controlled setup and integration tests.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_MIGRATIONS = Path(__file__).with_name("migrations")


def validate_schema_name(schema: str) -> str:
    if not _SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError(f"invalid PostgreSQL schema name: {schema!r}")
    return schema


def render_initial_migration(schema: str = "voiceagent") -> str:
    validated = validate_schema_name(schema)
    migration = _MIGRATIONS / "0001_agent_tasks_outbox.sql"
    return migration.read_text(encoding="utf-8").replace("__VOICEAGENT_SCHEMA__", validated)


def render_migrations(schema: str = "voiceagent") -> tuple[str, ...]:
    validated = validate_schema_name(schema)
    return tuple(
        migration.read_text(encoding="utf-8").replace("__VOICEAGENT_SCHEMA__", validated)
        for migration in sorted(_MIGRATIONS.glob("*.sql"))
    )


async def apply_migrations(connection: Any, *, schema: str = "voiceagent") -> None:
    for migration in render_migrations(schema):
        await connection.execute(migration)
    predicates = {
        "conversation_items_session_read_idx": "kind = ANY (ARRAY['user.input'::text, 'assistant.output'::text])",
        "conversation_items_recording_read_idx": "producer = 'voice-session-recording'::text",
    }
    for index_name, predicate in predicates.items():
        valid = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_class t ON t.oid = i.indrelid "
            "WHERE n.nspname = $1 AND c.relname = $2 "
            "AND t.relname = 'conversation_items' AND i.indisvalid AND i.indisready "
            "AND ARRAY(SELECT a.attname::text FROM unnest(i.indkey) WITH ORDINALITY k(num, ord) "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.num ORDER BY k.ord) "
            "= ARRAY['voice_session_id','tenant_id','user_id','thread_id','sequence'] "
            "AND pg_get_expr(i.indpred, i.indrelid, true) = $3)",
            validate_schema_name(schema),
            index_name,
            predicate,
        )
        if not valid:
            raise RuntimeError(
                f"session index is missing, invalid or incompatible ({index_name}); inspect and rebuild it before continuing"
            )
    from server.persistence.postgres.runtime_telemetry import validate_playback_lookup_index

    await validate_playback_lookup_index(connection, validate_schema_name(schema))
