"""Rebuildable live projection of durable Agent Task authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.agent_session.task_models import AgentTaskRecord
from server.core.interaction_context import InteractionContext
from server.voice_session.models import VoiceSessionIdentity


class AgentTaskRecordSource(Protocol):
    async def list_records(self) -> tuple[AgentTaskRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class AgentWorkRegistrySnapshot:
    identity: VoiceSessionIdentity
    records: tuple[AgentTaskRecord, ...]

    @property
    def worker_ids(self) -> tuple[str, ...]:
        return tuple(record.worker_id for record in self.records)


class AgentWorkRegistry:
    """Cache active work; Agent Task Store remains the only authority."""

    def __init__(self, records: AgentTaskRecordSource) -> None:
        self._records = records
        self._snapshots: dict[
            tuple[str, str, str, str, str], AgentWorkRegistrySnapshot
        ] = {}

    async def rebuild(
        self,
        identity: VoiceSessionIdentity,
    ) -> AgentWorkRegistrySnapshot:
        active = tuple(
            sorted(
                (
                    record
                    for record in await self._records.list_records()
                    if not record.phase.terminal
                    and _same_voice_session(record.context, identity)
                ),
                key=lambda record: (record.created_at, record.worker_id),
            )
        )
        snapshot = AgentWorkRegistrySnapshot(identity=identity, records=active)
        self._snapshots[_identity_key(identity)] = snapshot
        return snapshot

    def snapshot(
        self,
        identity: VoiceSessionIdentity,
    ) -> AgentWorkRegistrySnapshot:
        return self._snapshots.get(
            _identity_key(identity),
            AgentWorkRegistrySnapshot(identity=identity, records=()),
        )


def _identity_key(
    identity: VoiceSessionIdentity,
) -> tuple[str, str, str, str, str]:
    return (
        identity.tenant_id,
        identity.user_id,
        identity.device_id,
        identity.voice_session_id,
        identity.thread_id,
    )


def _same_voice_session(
    context: InteractionContext,
    identity: VoiceSessionIdentity,
) -> bool:
    return (
        context.tenant_id,
        context.user_id,
        context.device_id,
        context.voice_session_id,
        context.thread_id,
    ) == _identity_key(identity)
