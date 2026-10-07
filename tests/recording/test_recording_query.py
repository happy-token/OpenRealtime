from __future__ import annotations

from dataclasses import replace

import pytest

from server.artifacts import InMemoryArtifactStore
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    TextContent,
)
from server.realtime.recording import SessionAudioRecorder, recording_scope
from tests.realtime.test_realtime_websocket_bridge import context
from tests.recording.test_session_audio_recording import audio


async def recorded(journal, store=None):
    store = store or InMemoryArtifactStore()
    recorder = SessionAudioRecorder(
        context=context(), artifacts=store, journal=journal, on_failure=lambda _: None
    )
    recorder.capture("input", audio(), context=context(), epoch="input")
    assert await recorder.close()
    item = (await journal.read(recording_scope(context())))[0]
    return store, item


def draft(item, **changes):
    return ConversationItemDraft(
        item_id="copy",
        context=item.context,
        kind=item.kind,
        status=item.status,
        producer=item.producer,
        content=item.content,
        visibility=item.visibility,
        **changes,
    )


@pytest.mark.asyncio
async def test_recording_query_resolves_original_scope_and_artifact_without_telemetry():
    journal = InMemoryConversationJournal()
    _, item = await recorded(journal)
    page = await journal.read_recording_page(context().voice_session_id, limit=1)
    assert page.items == (item,) and page.next_sequence is None
    assert (
        await journal.find_recording_artifact(
            context().voice_session_id, item.content[0].value["artifact_id"]
        )
        == item
    )
    assert (
        await journal.find_recording_artifact(
            "another-session", item.content[0].value["artifact_id"]
        )
        is None
    )


@pytest.mark.asyncio
async def test_recording_pages_advance_original_sequences_and_purge_indexes():
    journal = InMemoryConversationJournal()
    _, item = await recorded(journal)
    for index in range(205):
        await journal.append(replace(draft(item), item_id=f"copy-{index}"))
    first = await journal.read_recording_page(context().voice_session_id, limit=200)
    second = await journal.read_recording_page(
        context().voice_session_id, after_sequence=first.next_sequence, limit=200
    )
    assert len(first.items) == 200 and len(second.items) == 6
    assert second.next_sequence is None and second.items[0].sequence == 201
    # Duplicate reference identity is ambiguous even inside one scope.
    with pytest.raises(ValueError, match="ambiguous"):
        await journal.find_recording_artifact(
            context().voice_session_id, item.content[0].value["artifact_id"]
        )
    await journal.delete_threads([recording_scope(context())])
    assert (await journal.read_recording_page(context().voice_session_id)).items == ()
    assert (
        await journal.find_recording_artifact(
            context().voice_session_id, item.content[0].value["artifact_id"]
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["recording", "dialogue", "bad-thread"])
async def test_session_recording_identity_fails_closed_on_conflicting_journal_evidence(foreign):
    journal = InMemoryConversationJournal()
    _, item = await recorded(journal)
    if foreign == "dialogue":
        await journal.append(
            ConversationItemDraft(
                item_id="foreign-dialogue",
                context=replace(context(), tenant_id="other"),
                kind=ConversationItemKind.USER_INPUT,
                status=ConversationItemStatus.COMMITTED,
                producer="core",
                content=(TextContent("foreign"),),
            )
        )
    else:
        ctx = (
            replace(item.context, tenant_id="other")
            if foreign == "recording"
            else replace(item.context, thread_id="wrong-thread")
        )
        await journal.append(replace(draft(item), context=ctx))
    with pytest.raises(ValueError):
        await journal.read_recording_page(context().voice_session_id)
    with pytest.raises(ValueError):
        await journal.find_recording_artifact(
            context().voice_session_id, item.content[0].value["artifact_id"]
        )


@pytest.mark.asyncio
async def test_shared_thread_other_session_and_input_evidence_do_not_supply_recording_identity():
    journal = InMemoryConversationJournal()
    _, item = await recorded(journal)
    await journal.append(
        ConversationItemDraft(
            item_id="dialogue",
            context=context(),
            kind=ConversationItemKind.USER_INPUT,
            status=ConversationItemStatus.COMMITTED,
            producer="core",
            content=(TextContent("text"),),
        )
    )
    await journal.append(
        replace(
            draft(item),
            item_id="input-evidence",
            producer="input-evidence",
            context=replace(item.context, thread_id="another-evidence-thread"),
        )
    )
    await journal.append(
        replace(
            draft(item),
            item_id="other-session",
            context=replace(
                item.context,
                voice_session_id="another-session",
                thread_id="other::recording:another-session",
            ),
        )
    )
    assert (await journal.read_recording_page(context().voice_session_id)).items == (item,)
    await journal.delete_session_owned_threads(
        [recording_scope(context())], [context().voice_session_id]
    )
    assert (await journal.read_recording_page(context().voice_session_id)).items == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"after_sequence": True},
        {"after_sequence": -1},
        {"after_sequence": 2**63},
        {"limit": False},
        {"limit": 0},
        {"limit": 1001},
    ],
)
async def test_recording_query_rejects_invalid_windows(kwargs):
    with pytest.raises(ValueError):
        await InMemoryConversationJournal().read_recording_page(
            context().voice_session_id, **kwargs
        )
