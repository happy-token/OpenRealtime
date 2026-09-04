"""Shared PostgreSQL transaction for modular persistence adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from server.persistence.postgres.agent_task_store import PostgresAgentTaskStore
from server.persistence.postgres.agent_event_store import PostgresAgentEventStore
from server.persistence.postgres.conversation_journal import PostgresConversationJournal
from server.persistence.postgres.outbox import PostgresOutboxStore
from server.persistence.postgres.schema import validate_schema_name
from server.persistence.postgres.tool_authorization import PostgresToolAuthorizationStore
from server.persistence.unit_of_work import PersistenceUnitOfWork


class PostgresPersistence:
    def __init__(self, pool: Any, *, schema: str = "voiceagent") -> None:
        self._pool = pool
        self._schema = validate_schema_name(schema)

    @property
    def agent_tasks(self) -> PostgresAgentTaskStore:
        return PostgresAgentTaskStore(self._pool, schema=self._schema)

    @property
    def outbox(self) -> PostgresOutboxStore:
        return PostgresOutboxStore(self._pool, schema=self._schema)

    @property
    def journal(self) -> PostgresConversationJournal:
        return PostgresConversationJournal(self._pool, schema=self._schema)

    @property
    def agent_events(self) -> PostgresAgentEventStore:
        return PostgresAgentEventStore(self._pool, schema=self._schema)

    @property
    def tool_authorizations(self) -> PostgresToolAuthorizationStore:
        return PostgresToolAuthorizationStore(self._pool, schema=self._schema)

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[PersistenceUnitOfWork]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                yield PersistenceUnitOfWork(
                    agent_tasks=PostgresAgentTaskStore(connection, schema=self._schema),
                    outbox=PostgresOutboxStore(connection, schema=self._schema),
                    journal=PostgresConversationJournal(connection, schema=self._schema),
                    agent_events=PostgresAgentEventStore(connection, schema=self._schema),
                    tool_authorizations=PostgresToolAuthorizationStore(
                        connection,
                        schema=self._schema,
                    ),
                )
