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
from server.conversation_journal.input_evidence import InputEvidenceRecorder, input_evidence_scope
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

    evidence = InputEvidenceRecorder(runtime.journal, context=context, on_failure=lambda _: None)
    await evidence.offer("input-1", "asr_revision", {"suffix": "delete me"}).committed
    await evidence.close()

    runtime.debug_log.bind("voice-delete").log("turn", "decision", "delete me")
    runtime.debug_log.bind("voice-keep").log("turn", "decision", "keep me")

    await runtime.debug_log.flush()
    result = await runtime.delete_session_history(
        ["voice-delete"], tenant_id="local", user_id="user"
    )

    assert result == {"requested": 1, "deleted_sessions": 1, "deleted_threads": 1, "deleted_evidence_threads": 1, "deleted_recording_threads": 0, "deleted_output_stop_facts": 0}
    assert await runtime.journal.read(input_evidence_scope(context)) == ()
    assert not await runtime.debug_log_query.session_timeline("voice-delete")
    assert len(await runtime.debug_log_query.session_timeline("voice-keep")) == 1
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


async def test_delete_origin_session_preserves_resumed_session_history_and_diagnostics():
    from dataclasses import replace

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    origin = InteractionContext(tenant_id="tenant", user_id="user", device_id="device", voice_session_id="origin",
                                thread_id="origin", turn_id="turn", generation=1)
    resumed = replace(origin, voice_session_id="resumed", generation=2)
    try:
        for ctx in (origin, resumed):
            await runtime.journal.append(ConversationItemDraft(
                item_id=ctx.voice_session_id, context=ctx, kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMMITTED, producer="test", content=(TextContent(ctx.voice_session_id),)))
            runtime.telemetry.bind(TelemetryIdentity(ctx.tenant_id, ctx.user_id, ctx.device_id,
                                  ctx.voice_session_id, ctx.thread_id)).record("interaction.collection_ready")
        result = await runtime.delete_session_history(["origin"], tenant_id="local", user_id="local-user")
        assert result["deleted_threads"] == 0
        assert len(await runtime.journal.read(JournalScope.from_context(origin))) == 2
        assert await runtime.diagnostics.session_detail("origin") is None
        assert await runtime.diagnostics.session_detail("resumed") is not None
    finally:
        await runtime.close()


async def test_delete_origin_retains_thread_referenced_by_active_session_without_items():
    from dataclasses import replace

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    origin = InteractionContext(tenant_id="tenant", user_id="user", device_id="device", voice_session_id="origin",
                                thread_id="origin", turn_id="turn", generation=1)
    resumed = replace(origin, voice_session_id="resumed")
    class Conversation:
        async def close(self):
            pass
    conversation = Conversation()
    runtime.active_realtime_conversations.register(context=resumed, conversation=conversation)
    try:
        await runtime.journal.append(ConversationItemDraft(item_id="origin", context=origin,
            kind=ConversationItemKind.USER_INPUT, status=ConversationItemStatus.COMMITTED,
            producer="test", content=(TextContent("retain original context"),)))
        runtime.telemetry.bind(TelemetryIdentity(origin.tenant_id, origin.user_id, origin.device_id,
                              origin.voice_session_id, origin.thread_id)).record("interaction.collection_ready")
        result = await runtime.delete_session_history(["origin"], tenant_id="local", user_id="local-user")
        assert result["deleted_threads"] == 0
        assert await runtime.journal.read(JournalScope.from_context(origin))
    finally:
        runtime.active_realtime_conversations.unregister(context=resumed, conversation=conversation)
        await runtime.close()


@pytest.mark.parametrize("fail", [False, True])
async def test_thread_deletion_excludes_interleaved_registration_and_releases_guard(monkeypatch, fail):
    from dataclasses import replace

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    ctx = InteractionContext(tenant_id="tenant", user_id="user", device_id="device", voice_session_id="origin",
                             thread_id="origin", turn_id="turn", generation=1)
    resumed = replace(ctx, voice_session_id="resumed")
    entered, release = asyncio.Event(), asyncio.Event()
    original_delete = runtime.debug_log.delete_sessions

    async def paused_delete(session_ids):
        entered.set()
        await release.wait()
        if fail:
            raise RuntimeError("injected delete failure")
        return await original_delete(session_ids)

    monkeypatch.setattr(runtime.debug_log, "delete_sessions", paused_delete)
    runtime.telemetry.bind(TelemetryIdentity(ctx.tenant_id, ctx.user_id, ctx.device_id,
                          ctx.voice_session_id, ctx.thread_id)).record("interaction.collection_ready")
    await runtime.journal.append(ConversationItemDraft(item_id="origin", context=ctx,
        kind=ConversationItemKind.USER_INPUT, status=ConversationItemStatus.COMMITTED,
        producer="test", content=(TextContent("original"),)))
    deleting = asyncio.create_task(runtime.delete_session_history(["origin"], tenant_id="tenant", user_id="user"))
    class Conversation:
        async def close(self):
            pass
    conversation = Conversation()
    try:
        async with asyncio.timeout(1):
            await entered.wait()
        with pytest.raises(RuntimeError, match="being deleted"):
            runtime.active_realtime_conversations.register(context=resumed, conversation=conversation)
        release.set()
        if fail:
            with pytest.raises(RuntimeError, match="injected"):
                await deleting
            assert await runtime.journal.read(JournalScope.from_context(ctx))
        else:
            assert (await deleting)["deleted_threads"] == 1
        runtime.active_realtime_conversations.register(context=resumed, conversation=conversation)
        assert runtime.active_realtime_conversations.resolve(resumed) is not None
    finally:
        release.set()
        await asyncio.gather(deleting, return_exceptions=True)
        runtime.active_realtime_conversations.unregister(context=resumed, conversation=conversation)
        await runtime.close()


async def test_delete_session_removes_only_its_stop_facts_for_resolved_identity():
    from dataclasses import replace

    from tests.realtime.test_output_stop_storage import requested
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    fact = requested()
    resumed = replace(fact, context=replace(fact.context, voice_session_id="resumed"))
    try:
        for item in (fact, resumed):
            await runtime.speech_deliveries.record_output_stop(item)
            ctx = item.context
            runtime.telemetry.bind(TelemetryIdentity(ctx.tenant_id, ctx.user_id, ctx.device_id,
                                  ctx.voice_session_id, ctx.thread_id)).record("test")
        result = await runtime.delete_session_history([fact.context.voice_session_id],
                                                      tenant_id="admin-tenant", user_id="admin-user")
        assert result["deleted_output_stop_facts"] == 1
        assert await runtime.speech_deliveries.get_output_stop(fact.context, fact.stop_command_id) is None
        assert await runtime.speech_deliveries.get_output_stop(resumed.context, resumed.stop_command_id) == resumed
    finally:
        await runtime.close()


@pytest.mark.parametrize("suspended", [False, True])
async def test_active_session_cannot_be_purged_while_it_may_still_write_stop_facts(suspended):
    from tests.realtime.test_output_stop_storage import requested
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    fact = requested()
    class Conversation:
        pass
    owner = Conversation()
    runtime.active_realtime_conversations.register(context=fact.context, conversation=owner)
    if suspended:
        runtime.active_realtime_conversations.suspend(context=fact.context, conversation=owner)
    try:
        await runtime.speech_deliveries.record_output_stop(fact)
        ctx = fact.context
        runtime.telemetry.bind(TelemetryIdentity(ctx.tenant_id, ctx.user_id, ctx.device_id,
                              ctx.voice_session_id, ctx.thread_id)).record("test")
        with pytest.raises(ValueError, match="active realtime session"):
            await runtime.delete_session_history([ctx.voice_session_id], tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        assert await runtime.speech_deliveries.get_output_stop(ctx, fact.stop_command_id) == fact
        assert await runtime.diagnostics.session_detail(ctx.voice_session_id) is not None
    finally:
        runtime.active_realtime_conversations.unregister(context=fact.context, conversation=owner)
        await runtime.close()


@pytest.mark.parametrize("fail", [False, True])
async def test_shared_thread_session_purge_blocks_registration_only_for_selected_session(monkeypatch, fail):
    from dataclasses import replace

    from tests.realtime.test_output_stop_storage import requested
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    fact = requested()  # Thread and session differ, so the thread guard cannot mask this test.
    ctx = fact.context
    entered, release = asyncio.Event(), asyncio.Event()
    original_delete = runtime.debug_log.delete_sessions
    async def paused_delete(ids):
        entered.set()
        await release.wait()
        if fail:
            raise RuntimeError("injected failure")
        return await original_delete(ids)
    monkeypatch.setattr(runtime.debug_log, "delete_sessions", paused_delete)
    runtime.telemetry.bind(TelemetryIdentity(ctx.tenant_id, ctx.user_id, ctx.device_id,
                          ctx.voice_session_id, ctx.thread_id)).record("test")
    deleting = asyncio.create_task(runtime.delete_session_history([ctx.voice_session_id],
                                  tenant_id=ctx.tenant_id, user_id=ctx.user_id))
    class Conversation:
        pass
    owner = Conversation()
    other = replace(ctx, voice_session_id="resumed")
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(RuntimeError, match="being deleted"):
            runtime.active_realtime_conversations.register(context=replace(ctx, device_id="other"), conversation=owner)
        runtime.active_realtime_conversations.register(context=other, conversation=owner)
        release.set()
        if fail:
            with pytest.raises(RuntimeError, match="injected"):
                await deleting
        else:
            await deleting
        runtime.active_realtime_conversations.register(context=ctx, conversation=owner)
    finally:
        release.set()
        await asyncio.gather(deleting, return_exceptions=True)
        for target in (ctx, other):
            runtime.active_realtime_conversations.unregister(context=target, conversation=owner)
        await runtime.close()
