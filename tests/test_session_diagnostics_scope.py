"""Exercise the production reader with real Journal and telemetry authorities."""

from dataclasses import replace

import pytest

from demos import voice_web_server
from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.observability.telemetry import TelemetryIdentity


async def append(runtime, context, item_id, text):
    await runtime.journal.append(ConversationItemDraft(
        item_id=item_id, context=context, kind=ConversationItemKind.USER_INPUT,
        status=ConversationItemStatus.COMMITTED, producer="test", content=(TextContent(text),),
    ))


def record_identity(runtime, context):
    runtime.telemetry.bind(TelemetryIdentity(
        tenant_id=context.tenant_id, user_id=context.user_id, device_id=context.device_id,
        voice_session_id=context.voice_session_id, thread_id=context.thread_id,
    )).record("interaction.collection_ready")


@pytest.mark.parametrize("public_identity", [False, True])
async def test_real_reader_filters_shared_thread_by_original_voice_session(monkeypatch, public_identity):
    monkeypatch.setenv("VOICEAGENT_TENANT_ID", "local")
    monkeypatch.setenv("VOICEAGENT_USER_ID", "local-user")
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    context = InteractionContext(
        tenant_id="public-tenant" if public_identity else "local",
        user_id="public-user" if public_identity else "local-user", device_id="device",
        voice_session_id="session-A", thread_id="shared-thread" if public_identity else "session-A",
        turn_id="turn-A", generation=1,
    )
    continued = replace(context, voice_session_id="session-B", turn_id="turn-B")
    try:
        await append(runtime, context, "item-A", "only A")
        await append(runtime, continued, "item-B", "only B")
        record_identity(runtime, context)
        record_identity(runtime, continued)
        for target, expected in [("session-A", "only A"), ("session-B", "only B")]:
            result = await voice_web_server._read_session_conversation(target)
            assert [row["text"] for row in result] == [expected]
            assert all(row["voice_session_id"] == target for row in result)
    finally:
        await runtime.close()


async def test_missing_metadata_legacy_scope_still_never_returns_a_continued_session(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_TENANT_ID", "local")
    monkeypatch.setenv("VOICEAGENT_USER_ID", "local-user")
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    context = InteractionContext(tenant_id="local", user_id="local-user", device_id="device",
                                 voice_session_id="session-A", thread_id="session-A", turn_id="turn", generation=1)
    try:
        await append(runtime, context, "item-A", "only A")
        await append(runtime, replace(context, voice_session_id="session-B"), "item-B", "only B")
        assert [row["text"] for row in await voice_web_server._read_session_conversation("session-A")] == ["only A"]
    finally:
        await runtime.close()


async def test_ambiguous_recorded_scope_is_unavailable_instead_of_guessing(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    context = InteractionContext(tenant_id="tenant", user_id="user", device_id="device",
                                 voice_session_id="ambiguous", thread_id="thread-1", turn_id="turn", generation=1)
    try:
        record_identity(runtime, context)
        record_identity(runtime, replace(context, thread_id="thread-2"))
        with pytest.raises(ValueError, match="ambiguous"):
            await voice_web_server._read_session_conversation("ambiguous")
    finally:
        await runtime.close()


async def test_thread_beyond_bounded_replay_is_unavailable_not_claimed_complete(monkeypatch):
    monkeypatch.setenv("VOICEAGENT_TENANT_ID", "local")
    monkeypatch.setenv("VOICEAGENT_USER_ID", "local-user")
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    context = InteractionContext(tenant_id="local", user_id="local-user", device_id="device",
                                 voice_session_id="large", thread_id="large", turn_id="turn", generation=1)
    try:
        for i in range(1001):
            await append(runtime, context, f"item-{i}", "bounded")
        with pytest.raises(RuntimeError, match="replay limit"):
            await voice_web_server._read_session_conversation("large")
    finally:
        await runtime.close()


async def test_identity_on_a_later_telemetry_page_cannot_be_claimed_unambiguous(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    context = InteractionContext(tenant_id="tenant", user_id="user", device_id="device",
                                 voice_session_id="many-events", thread_id="thread-A", turn_id="turn", generation=1)
    try:
        await append(runtime, context, "item-A", "only A")
        other = replace(context, tenant_id="other-tenant", thread_id="thread-B")
        await append(runtime, other, "item-B", "only B")
        for i in range(5000):
            record_identity(runtime, context)
            if (i + 1) % 500 == 0:
                await runtime.telemetry.flush()
        record_identity(runtime, other)
        await runtime.telemetry.flush()
        detail = await runtime.diagnostics.session_detail("many-events")
        assert detail is not None and detail.next_cursor is not None
        with pytest.raises(ValueError, match="identity is incomplete"):
            await voice_web_server._read_session_conversation("many-events")
    finally:
        await runtime.close()
