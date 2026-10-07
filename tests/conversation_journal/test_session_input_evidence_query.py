"""Original Session evidence must not depend on a telemetry first page."""
from dataclasses import replace

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.conversation_journal.input_evidence import InputEvidenceRecorder, input_evidence_scope
from tests.realtime.test_cascaded_capabilities import context


async def record(journal, ctx, suffix):
    recorder = InputEvidenceRecorder(journal, context=ctx, on_failure=lambda reason: None)
    try:
        receipt = recorder.offer("logical-input", "asr_revision", {"suffix": suffix, "replace_from": 0})
        return await receipt.committed
    finally:
        assert await recorder.close() == 0


async def test_original_session_evidence_pages_survive_continuation_and_delete():
    journal = InMemoryConversationJournal()
    ctx = context()
    one = await record(journal, ctx, "original")
    await record(journal, replace(ctx, voice_session_id="continued"), "foreign")
    two = await record(journal, ctx, "revision")
    first = await journal.read_input_evidence_page(ctx.voice_session_id, limit=1)
    assert first.items == (one,) and first.next_sequence == one.sequence
    tail = await journal.read_input_evidence_page(ctx.voice_session_id, after_sequence=first.next_sequence, limit=1)
    assert tail.items == (two,) and tail.next_sequence is None
    assert (await journal.read_input_evidence_page("missing")).items == ()
    await journal.delete_threads([input_evidence_scope(ctx)])
    assert (await journal.read_input_evidence_page(ctx.voice_session_id)).items == ()
    assert len((await journal.read_input_evidence_page("continued")).items) == 1


@pytest.mark.parametrize("field", ["tenant_id", "user_id", "thread_id"])
async def test_ambiguous_session_input_identity_is_unavailable(field):
    journal = InMemoryConversationJournal()
    ctx = context()
    await record(journal, ctx, "mine")
    await record(journal, replace(ctx, **{field: "other"}), "foreign")
    with pytest.raises(ValueError, match="ambiguous"):
        await journal.read_input_evidence_page(ctx.voice_session_id)


async def test_input_evidence_projection_uses_exact_cursor_and_original_context():
    from server.conversation_journal.input_evidence import read_session_input_evidence

    journal = InMemoryConversationJournal()
    ctx = context()
    await record(journal, ctx, "one")
    await record(journal, ctx, "two")
    page = await read_session_input_evidence(journal, ctx.voice_session_id, limit=1)
    assert page["voice_session_id"] == ctx.voice_session_id
    assert page["next_cursor"] == "1" and page["records"][0]["sequence"] == "1"
    assert page["records"][0]["detail"]["source_thread_id"] == ctx.thread_id
    assert not page["durable"] and page["status"] == "available"
    final = await read_session_input_evidence(journal, ctx.voice_session_id, after_sequence=1, limit=1)
    assert final["next_cursor"] is None and final["records"][0]["sequence"] == "2"
    empty = await read_session_input_evidence(journal, "missing")
    assert empty["status"] == "not_collected" and empty["records"] == []


async def test_input_evidence_projection_rejects_mismatched_recorded_payload():
    from server.conversation_journal import ConversationItemDraft, StructuredContent
    from server.conversation_journal.input_evidence import (
        InputEvidenceUnavailable,
        read_session_input_evidence,
    )

    journal = InMemoryConversationJournal()
    ctx = context()
    valid = await record(journal, ctx, "one")
    draft = ConversationItemDraft(item_id="corrupt", context=valid.context, kind=valid.kind,
        status=valid.status, producer=valid.producer,
        content=(StructuredContent({**valid.content[0].value, "source_thread_id": "foreign"}),))
    await journal.append(draft)
    with pytest.raises(InputEvidenceUnavailable, match="invalid committed"):
        await read_session_input_evidence(journal, ctx.voice_session_id)


async def test_cursor_is_not_evidence_that_a_missing_session_was_collected():
    from server.conversation_journal.input_evidence import read_session_input_evidence

    journal = InMemoryConversationJournal()
    assert (await read_session_input_evidence(journal, "missing", after_sequence=100))["status"] == "not_collected"
    await record(journal, context(), "actual")
    tail = await read_session_input_evidence(journal, context().voice_session_id, after_sequence=100)
    assert tail["status"] == "available" and tail["records"] == [] and tail["next_cursor"] is None
