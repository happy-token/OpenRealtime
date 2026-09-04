"""Storage-agnostic transaction boundary used by orchestration services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncContextManager, Protocol

from server.agent_session.task_store import AgentTaskStore
from server.agent_session.event_store import AgentEventStore
from server.conversation_journal import ConversationJournal
from server.persistence.outbox import OutboxStore
from server.tools.policy_gateway import ToolAuthorizationStore


@dataclass(frozen=True, slots=True)
class PersistenceUnitOfWork:
    agent_tasks: AgentTaskStore
    outbox: OutboxStore
    journal: ConversationJournal
    agent_events: AgentEventStore
    tool_authorizations: ToolAuthorizationStore


class AgentPersistence(Protocol):
    @property
    def agent_tasks(self) -> AgentTaskStore: ...

    @property
    def outbox(self) -> OutboxStore: ...

    @property
    def journal(self) -> ConversationJournal: ...

    @property
    def agent_events(self) -> AgentEventStore: ...

    @property
    def tool_authorizations(self) -> ToolAuthorizationStore: ...

    def unit_of_work(self) -> AsyncContextManager[PersistenceUnitOfWork]: ...
