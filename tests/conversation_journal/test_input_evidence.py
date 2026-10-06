from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationVisibility,
    InMemoryConversationJournal,
    JournalScope,
)
from server.conversation_journal.input_evidence import (
    InputEvidenceRecorder,
    InputEvidenceUnavailable,
    input_evidence_scope,
    read_input_evidence,
)
from tests.realtime.test_cascaded_capabilities import context


@pytest.mark.asyncio
async def test_confirmed_ordered_evidence_is_immutable_internal_and_paginated():
    journal = InMemoryConversationJournal()
    faults = []
    recorder = InputEvidenceRecorder(journal, context=context(), on_failure=faults.append)
    value = {"suffix": "查北京天气", "replace_from": 0}
    first = recorder.offer("input-1", "asr_revision", value)
    value["suffix"] = "mutated"
    second = recorder.offer("input-1", "asr_revision", {"suffix": "上海", "replace_from": 1})
    try:
        committed = await first.committed
        await second.committed
        assert committed.visibility == frozenset({ConversationVisibility.INTERNAL})
        assert await journal.read(JournalScope.from_context(context())) == ()
        page = await read_input_evidence(journal, context(), limit=1)
        assert page["records"][0]["detail"]["suffix"] == "查北京天气"
        assert page["has_more"] and not page["durable"]
        tail = await read_input_evidence(journal, context(), after_sequence=page["next_sequence"], limit=1)
        assert tail["records"][0]["item_id"] == second.item_id
        assert not tail["has_more"] and not faults
        assert (await read_input_evidence(journal, replace(context(), voice_session_id="other")))["records"] == []
    finally:
        assert await recorder.close() == 0


@pytest.mark.asyncio
async def test_failed_write_freezes_recorder_and_keeps_every_unsaved_draft():
    class Failing(InMemoryConversationJournal):
        async def append(self, *args, **kwargs):
            raise RuntimeError("credential=secret provider details")

    faults = []
    recorder = InputEvidenceRecorder(Failing(), context=context(), on_failure=faults.append)
    first = recorder.offer("input-1", "asr_revision", {"text": "原始输入"})
    second = recorder.offer("input-1", "asr_revision", {"text": "重要补充"})
    for receipt in (first, second):
        with pytest.raises(InputEvidenceUnavailable, match="RuntimeError"):
            await receipt.committed
    with pytest.raises(InputEvidenceUnavailable):
        recorder.offer("input-2", "asr_revision", {})
    assert len(faults) == 1 and "secret" not in faults[0]
    assert len(recorder._retained) == 2
    assert await recorder.close() == 2


@pytest.mark.asyncio
async def test_noncooperative_storage_times_out_and_late_commit_is_not_promoted():
    started, release = asyncio.Event(), asyncio.Event()

    class Slow(InMemoryConversationJournal):
        async def append(self, draft, **kwargs):
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass
            return await super().append(draft, **kwargs)

    journal = Slow()
    recorder = InputEvidenceRecorder(journal, context=context(), on_failure=lambda reason: None, write_timeout_s=.01)
    receipt = recorder.offer("input-1", "asr_revision", {"text": "不能丢失"})
    await started.wait()
    with pytest.raises(InputEvidenceUnavailable, match="timed out"):
        async with asyncio.timeout(.2):
            await receipt.committed
    async with asyncio.timeout(.3):
        assert await recorder.close() == 1
    release.set()
    await asyncio.sleep(.01)
    assert receipt.committed.exception() is not None
    assert len(await journal.read(input_evidence_scope(context()))) == 1


@pytest.mark.asyncio
async def test_queue_limit_counts_active_write_and_shutdown_resolves_waiters():
    release = asyncio.Event()

    class Slow(InMemoryConversationJournal):
        async def append(self, draft, **kwargs):
            await release.wait()
            return await super().append(draft, **kwargs)

    recorder = InputEvidenceRecorder(Slow(), context=context(), on_failure=lambda reason: None, max_pending=1)
    first = recorder.offer("input-1", "asr_revision", {"text": "保留"})
    await asyncio.sleep(0)
    with pytest.raises(InputEvidenceUnavailable, match="queue is full"):
        recorder.offer("input-1", "asr_revision", {})
    assert await recorder.close(timeout_s=.01) == 1
    with pytest.raises(InputEvidenceUnavailable):
        await first.committed


@pytest.mark.asyncio
async def test_wrong_commit_acknowledgement_cannot_count_as_saved():
    class Wrong(InMemoryConversationJournal):
        async def append(self, draft, **kwargs):
            return await super().append(replace(draft, item_id="wrong-id"), **kwargs)

    recorder = InputEvidenceRecorder(Wrong(), context=context(), on_failure=lambda reason: None)
    receipt = recorder.offer("input-1", "asr_revision", {"text": "完整证据"})
    with pytest.raises(InputEvidenceUnavailable, match="does not match"):
        await receipt.committed
    assert await recorder.close() == 1


@pytest.mark.asyncio
async def test_record_and_queue_byte_limits_are_enforced_before_accepting_a_receipt():
    recorder = InputEvidenceRecorder(InMemoryConversationJournal(), context=context(),
                                    on_failure=lambda reason: None, max_record_bytes=10)
    with pytest.raises(InputEvidenceUnavailable, match="record exceeds"):
        recorder.offer("input-1", "asr_revision", {"text": "北京"})
    assert await recorder.close() == 0


@pytest.mark.asyncio
async def test_cancelled_storage_notifies_failure_and_cannot_strand_other_receipts():
    class CancelledStorage(InMemoryConversationJournal):
        async def append(self, draft):
            raise asyncio.CancelledError

    faults = []
    recorder = InputEvidenceRecorder(CancelledStorage(), context=context(), on_failure=faults.append)
    first = recorder.offer("input", "asr_revision", {})
    second = recorder.offer("input", "asr_revision", {})
    try:
        for receipt in (first, second):
            with pytest.raises(InputEvidenceUnavailable):
                async with asyncio.timeout(.2):
                    await receipt.committed
        assert faults == ["input evidence write was cancelled"]
    finally:
        assert await recorder.close() == 2


@pytest.mark.asyncio
async def test_callers_cannot_override_evidence_identity_metadata():
    recorder = InputEvidenceRecorder(InMemoryConversationJournal(), context=context(), on_failure=lambda _: None)
    try:
        item = await recorder.offer("input", "asr_revision", {"input_id": "wrong", "schema": "wrong", "durable": True}).committed
        detail = item.content[0].value
        assert detail["input_id"] == "input" and detail["schema"] == "semantic-input-evidence.v1"
        assert detail["durable"] is False
    finally:
        await recorder.close()


@pytest.mark.asyncio
async def test_later_turn_context_is_preserved_without_changing_storage_scope():
    recorder = InputEvidenceRecorder(InMemoryConversationJournal(), context=context(), on_failure=lambda _: None)
    later = replace(context(), generation=4, turn_id="later-turn")
    try:
        item = await recorder.offer("input-later", "asr_revision", {}, context=later).committed
        assert item.context.generation == 4 and item.context.turn_id == "later-turn"
        assert item.content[0].value["generation"] == 4
        assert item.content[0].value["turn_id"] == "later-turn"
        assert JournalScope.from_context(item.context) == input_evidence_scope(context())
        with pytest.raises(InputEvidenceUnavailable, match="outside"):
            recorder.offer("other", "asr_revision", {}, context=replace(later, user_id="other-user"))
    finally:
        await recorder.close()
