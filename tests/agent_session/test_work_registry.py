from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from server.agent_session.task_models import AgentTaskPhase
from server.agent_session.work_registry import AgentWorkRegistry
from server.core.interaction_context import InteractionContext
from server.voice_session import VoiceSessionIdentity


def identity() -> VoiceSessionIdentity:
    return VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
    )


def record(worker_id: str, phase: AgentTaskPhase, *, voice_session_id: str = "voice-1"):
    return SimpleNamespace(
        worker_id=worker_id,
        phase=phase,
        created_at=datetime.now(UTC),
        context=InteractionContext(
            tenant_id="tenant-1",
            user_id="user-1",
            device_id="device-1",
            voice_session_id=voice_session_id,
            thread_id="thread-1",
            turn_id="turn-1",
            generation=1,
            worker_id=worker_id,
        ),
    )


async def test_work_registry_rebuild_reads_authority_without_starting_work() -> None:
    class Records:
        def __init__(self) -> None:
            self.calls = 0

        async def list_records(self):
            self.calls += 1
            return (
                record("worker-running", AgentTaskPhase.RUNNING),
                record("worker-complete", AgentTaskPhase.SUCCEEDED),
                record(
                    "worker-other-session",
                    AgentTaskPhase.RUNNING,
                    voice_session_id="voice-2",
                ),
            )

    records = Records()
    registry = AgentWorkRegistry(records)

    snapshot = await registry.rebuild(identity())

    assert records.calls == 1
    assert snapshot.worker_ids == ("worker-running",)
    assert registry.snapshot(identity()) == snapshot
