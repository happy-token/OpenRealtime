"""Exercise the production reader with real Journal and telemetry authorities."""

import asyncio
import json
import urllib.request
from dataclasses import replace

import pytest

from demos import voice_web_server
from server.application.runtime import ApplicationRuntimeConfig, build_application_runtime
from server.control_plane import http as control_plane_http
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.endpoint_session.registry import EndpointSessionRegistry
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


async def test_paged_production_reader_reads_large_continued_thread_without_telemetry(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    context = InteractionContext(tenant_id="public-tenant", user_id="public-user", device_id="device",
                                 voice_session_id="earlier", thread_id="shared", turn_id="turn", generation=1)
    continued = replace(context, voice_session_id="continued")
    try:
        for i in range(1005):
            await append(runtime, context, f"earlier-{i}", "other Session")
        for i in range(3):
            await append(runtime, continued, f"continued-{i}", f"mine {i}")
        page = await voice_web_server._read_session_conversation_page("continued", 0, 2)
        assert [row["text"] for row in page["items"]] == ["mine 0", "mine 1"]
        assert page["next_cursor"] == "1007"
        final = await voice_web_server._read_session_conversation_page("continued", int(page["next_cursor"]), 2)
        assert [row["text"] for row in final["items"]] == ["mine 2"]
        assert final["next_cursor"] is None
        assert all(row["voice_session_id"] == "continued" for row in page["items"] + final["items"])
    finally:
        await runtime.close()


async def test_real_http_pagination_runs_production_reader_and_conversation_query(monkeypatch):
    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    context = InteractionContext(tenant_id="tenant", user_id="user", device_id="device",
                                 voice_session_id="A", thread_id="shared", turn_id="turn", generation=1)
    server = control_plane_http.start(EndpointSessionRegistry(),
        session_conversation_page_reader=voice_web_server._read_session_conversation_page, port=0)
    base = f"http://127.0.0.1:{server.server_address[1]}/observability/sessions/A/conversation-page?limit=1"
    def get(url):
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status, json.loads(response.read())
    try:
        await append(runtime, context, "A-1", "first")
        await append(runtime, replace(context, voice_session_id="B"), "B-1", "not A")
        await append(runtime, context, "A-2", "second")
        status, first = await asyncio.to_thread(get, base)
        assert status == 200 and first["next_cursor"] == "1"
        status, second = await asyncio.to_thread(get, base + "&after_sequence=" + first["next_cursor"])
        assert status == 200 and second["next_cursor"] is None
        assert [first["items"][0]["text"], second["items"][0]["text"]] == ["first", "second"]
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await runtime.close()


async def test_real_http_input_evidence_uses_journal_without_telemetry(monkeypatch):
    from server.conversation_journal.input_evidence import InputEvidenceRecorder

    runtime = await build_application_runtime(ApplicationRuntimeConfig())
    monkeypatch.setattr(voice_web_server, "_application_runtime", runtime)
    ctx = InteractionContext(tenant_id="real-tenant", user_id="real-user", device_id="device",
        voice_session_id="original", thread_id="shared", turn_id="turn", generation=1)
    recorder = InputEvidenceRecorder(runtime.journal, context=ctx, on_failure=lambda _: None)
    server = control_plane_http.start(EndpointSessionRegistry(),
        session_input_evidence_reader=voice_web_server._read_session_input_evidence, port=0)
    def get(query):
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/observability/sessions/original/input-evidence?{query}", timeout=3) as response:
            return json.loads(response.read())
    try:
        await recorder.offer("input", "asr_revision", {"suffix": "原文"}).committed
        await recorder.offer("input", "asr_revision", {"suffix": "纠正"}).committed
        first = await asyncio.to_thread(get, "limit=1")
        second = await asyncio.to_thread(get, "limit=1&after_sequence=" + first["next_cursor"])
        assert first["records"][0]["detail"]["suffix"] == "原文"
        assert second["records"][0]["detail"]["suffix"] == "纠正" and second["next_cursor"] is None
        assert first["voice_session_id"] == "original" and not first["durable"]
    finally:
        await recorder.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await runtime.close()
