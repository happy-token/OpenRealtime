from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from server.agent_session.result_delivery import AgentResultDeliveryWorker
from server.application.runtime import (
    ApplicationRuntimeConfig,
    build_application_runtime,
)
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    JournalScope,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.observability.telemetry import DiagnosticsWindow, TelemetryIdentity
from server.persistence.postgres import PostgresPersistence
from server.voice_session import VoiceSessionAdmissionRejected, VoiceSessionIdentity


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


async def test_runtime_defaults_to_in_memory_persistence_for_local_development() -> None:
    runtime = await build_application_runtime(ApplicationRuntimeConfig())

    assert isinstance(runtime.journal, InMemoryConversationJournal)

    await runtime.close()


async def test_runtime_owns_one_shared_configured_voice_session_admission() -> None:
    runtime = await build_application_runtime(
        ApplicationRuntimeConfig(voice_max_active_sessions=1)
    )
    identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="browser",
        voice_session_id="voice-1",
        thread_id="voice-1",
    )

    lease = await runtime.voice_session_admission.acquire(identity)
    rejected_identity = VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="browser-2",
        voice_session_id="voice-2",
        thread_id="voice-2",
    )
    with pytest.raises(VoiceSessionAdmissionRejected):
        await runtime.voice_session_admission.acquire(rejected_identity)

    await lease.release()
    await runtime.telemetry.flush()
    accepted = await runtime.diagnostics.session_detail(identity.voice_session_id)
    rejected = await runtime.diagnostics.session_detail(
        rejected_identity.voice_session_id
    )
    assert accepted is not None
    assert [event.attributes["decision"] for event in accepted.events] == [
        "accepted",
        "released",
    ]
    assert rejected is not None
    assert rejected.events[0].outcome == "degraded"
    assert rejected.events[0].attributes["reasons"] == ["active_sessions"]
    await runtime.close()


def test_runtime_reads_voice_capacity_profile_from_environment() -> None:
    config = ApplicationRuntimeConfig.from_env(
        {
            "VOICEAGENT_MAX_ACTIVE_VOICE_SESSIONS": "3",
            "VOICEAGENT_MAX_ASR_SESSIONS": "4",
            "VOICEAGENT_MAX_TTS_SESSIONS": "5",
            "VOICEAGENT_MAX_EVENT_LOOP_LAG_MS": "125",
            "VOICEAGENT_MAX_PROCESS_MEMORY_BYTES": "2000000000",
            "VOICEAGENT_MAX_AUDIO_QUEUE_BYTES": "8000000",
            "VOICEAGENT_AUDIO_QUEUE_RESERVATION_BYTES": "1000000",
            "VOICEAGENT_CAPACITY_RETRY_AFTER_MS": "900",
        }
    )

    assert config.voice_max_active_sessions == 3
    assert config.voice_max_asr_sessions == 4
    assert config.voice_max_tts_sessions == 5
    assert config.voice_max_event_loop_lag_ms == 125
    assert config.voice_max_process_memory_bytes == 2_000_000_000
    assert config.voice_max_audio_queue_bytes == 8_000_000
    assert config.voice_audio_queue_reservation_bytes == 1_000_000
    assert config.voice_capacity_retry_after_ms == 900


async def test_runtime_close_cancels_a_stalled_result_delivery_poll(monkeypatch) -> None:
    poll_started = asyncio.Event()

    async def stalled_poll(self, *, owner: str):
        del self, owner
        poll_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(AgentResultDeliveryWorker, "deliver_once", stalled_poll)
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    await asyncio.wait_for(poll_started.wait(), timeout=0.2)

    await asyncio.wait_for(runtime.close(), timeout=0.2)


async def test_runtime_owns_live_diagnostics_for_the_configured_state_backend() -> None:
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    session = runtime.telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-runtime",
            thread_id="voice-runtime",
        )
    )
    session.record("asr.final_tail", generation=1, duration_ms=120)
    await runtime.telemetry.flush()

    overview = await runtime.diagnostics.overview(
        DiagnosticsWindow.last(timedelta(minutes=5))
    )

    assert overview.session_count == 1
    assert overview.metrics[0].name == "asr.final_tail"

    await runtime.close()


async def test_runtime_deletes_session_telemetry_and_conversation_history() -> None:
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    context = InteractionContext(
        tenant_id="local",
        user_id="user",
        device_id="browser",
        voice_session_id="voice-delete",
        thread_id="voice-delete",
        turn_id="turn-1",
        generation=1,
    )
    await runtime.journal.append(
        ConversationItemDraft(
            item_id="item-delete",
            context=context,
            kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMMITTED,
            producer="test",
            content=(TextContent("delete me"),),
        )
    )
    telemetry = runtime.telemetry.bind(
        TelemetryIdentity(
            tenant_id="local",
            user_id="user",
            device_id="browser",
            voice_session_id="voice-delete",
            thread_id="voice-delete",
        )
    )
    telemetry.record("turn.total", duration_ms=100)

    result = await runtime.delete_session_history(
        ["voice-delete"], tenant_id="local", user_id="user"
    )

    assert result == {"requested": 1, "deleted_sessions": 1, "deleted_threads": 1}
    assert await runtime.diagnostics.session_detail("voice-delete") is None
    assert await runtime.journal.read(
        JournalScope(tenant_id="local", user_id="user", thread_id="voice-delete")
    ) == ()
    await runtime.close()


async def test_postgres_runtime_requires_an_explicit_dsn() -> None:
    with pytest.raises(ValueError, match="POSTGRES_DSN"):
        await build_application_runtime(
            ApplicationRuntimeConfig(state_backend="postgres")
        )


def test_runtime_rejects_invalid_postgres_schema_before_opening_a_pool() -> None:
    with pytest.raises(ValueError, match="invalid PostgreSQL schema"):
        ApplicationRuntimeConfig(postgres_schema="voiceagent; drop schema")


async def test_postgres_runtime_owns_pool_without_running_migrations() -> None:
    pool = FakePool()
    calls: list[dict[str, object]] = []

    async def create_pool(**kwargs):
        calls.append(kwargs)
        return pool

    runtime = await build_application_runtime(
        ApplicationRuntimeConfig(
            state_backend="postgres",
            postgres_dsn="postgresql://voiceagent",
            postgres_schema="voiceagent_test",
        ),
        postgres_pool_factory=create_pool,
    )

    assert isinstance(runtime.persistence, PostgresPersistence)
    assert calls == [
        {
            "dsn": "postgresql://voiceagent",
            "min_size": 1,
            "max_size": 12,
        }
    ]

    await runtime.close()
    await runtime.close()

    assert pool.closed is True
