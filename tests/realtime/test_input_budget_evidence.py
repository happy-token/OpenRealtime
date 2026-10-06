from __future__ import annotations

import asyncio

import pytest

from server.conversation_journal import InMemoryConversationJournal
from server.conversation_journal.input_evidence import read_input_evidence
from server.realtime.capabilities.asr import AsrEndpointHint
from server.realtime.capabilities.turn_manager import (
    AsrDiscardRequested,
    ObserveAsrEvent,
    SemanticInputRejected,
)
from server.turn_policy.semantic_input import SemanticInputBudget
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_coordinated_turn_manager import Endpoint, opened, start, take, text


class DurableMemoryJournal(InMemoryConversationJournal):
    """Local test double for a journal acknowledging durable writes."""
    durable = True


@pytest.mark.asyncio
async def test_utf8_budget_rejects_full_input_without_classifying_a_truncated_prefix():
    journal, endpoint = DurableMemoryJournal(), Endpoint()
    session = await opened(input_evidence_journal=journal, input_budget=SemanticInputBudget(max_text_bytes=6),
                           semantic_chunks_enabled=True, eot_classifier=endpoint)
    stream = session.events()
    try:
        await start(session)
        await text(session, "北京")
        await text(session, "北京上海", revision=2)
        rejected = await take(stream, SemanticInputRejected)
        assert rejected.reason == "input_text_bytes" and rejected.evidence_saved
        assert (await take(stream, AsrDiscardRequested)).reason == "input_text_bytes"
        assert endpoint.requests == []
        records = (await read_input_evidence(journal, context()))["records"]
        assert records[-1]["detail"]["text"] == "北京上海"
        assert records[-1]["detail"]["accepted_revision"] == 1
        assert records[-1]["detail"]["rejected_revision"] == 2
        assert records[-1]["item_id"] == rejected.evidence_id
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_missing_storage_confirmation_keeps_the_only_input_and_reports_failure():
    session = await opened(input_budget=SemanticInputBudget(max_text_bytes=6), semantic_chunks_enabled=True)
    try:
        await start(session)
        await text(session, "北京")
        await text(session, "北京上海", revision=2)
        rejected = await take(session.events(), SemanticInputRejected)
        assert not rejected.evidence_saved
        assert session._input.text == "北京"
        assert session._input.rejected_text == "北京上海"
        assert session._input.blocked
        await text(session, "后面继续", revision=3)
        assert session._input.rejected_text == "北京上海"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_asr_rewrite_evidence_is_a_replayable_delta_chain():
    journal = InMemoryConversationJournal()
    session = await opened(input_evidence_journal=journal, semantic_chunks_enabled=True)
    try:
        await start(session)
        for revision, value in enumerate(["查北京天气，", "查上海天气，", "查上海明天天气，"], 1):
            await text(session, value, revision=revision)
        assert await session._evidence.close() == 0
        records = (await read_input_evidence(journal, context()))["records"]
        replay, previous = "", None
        snapshots = []
        for record in records:
            detail = record["detail"]
            if detail["event"] == "asr_revision":
                assert detail["previous_item_id"] == previous
                replay = replay[:detail["replace_from"]] + detail["suffix"]
                snapshots.append(replay)
                previous = record["item_id"]
        assert snapshots == ["查北京天气，", "查上海天气，", "查上海明天天气，"]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_absolute_input_duration_does_not_restart_on_asr_revisions():
    journal = DurableMemoryJournal()
    session = await opened(input_evidence_journal=journal, input_budget=SemanticInputBudget(max_duration_ms=30))
    try:
        await start(session)
        await text(session, "查北京")
        await asyncio.sleep(.02)
        await text(session, "查上海", revision=2)
        rejected = await take(session.events(), SemanticInputRejected)
        assert rejected.reason == "input_duration" and rejected.evidence_saved
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_chunk_history_overflow_stops_before_dispatch_and_preserves_entire_snapshot():
    journal, endpoint = DurableMemoryJournal(), Endpoint()
    session = await opened(input_evidence_journal=journal, input_budget=SemanticInputBudget(max_chunks=1),
                           semantic_chunks_enabled=True, eot_classifier=endpoint)
    try:
        await session.send(ObserveAsrEvent(event=AsrEndpointHint(context=context(), revision=1, text="第一句，第二句。")))
        rejected = await take(session.events(), SemanticInputRejected)
        assert rejected.reason == "input_chunks" and rejected.evidence_saved
        assert endpoint.requests == []
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_memory_ack_does_not_authorize_discard_as_durable():
    journal = InMemoryConversationJournal()
    session = await opened(input_evidence_journal=journal, input_budget=SemanticInputBudget(max_text_bytes=6))
    try:
        await text(session, "北京上海")
        rejected = await take(session.events(), SemanticInputRejected)
        assert not rejected.evidence_saved
        assert session._input.blocked
        assert session._input.rejected_text == "北京上海"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_same_revision_endpoint_boundary_is_recorded():
    journal = InMemoryConversationJournal()
    session = await opened(input_evidence_journal=journal)
    try:
        await start(session)
        await text(session, "查北京", revision=1)
        await session.send(ObserveAsrEvent(event=AsrEndpointHint(context=context(), revision=1, text="查北京")))
        await session._evidence.close()
        records = (await read_input_evidence(journal, context()))["records"]
        assert [record["detail"]["boundary"] for record in records
                if record["detail"]["event"] == "asr_revision"] == ["partial", "sentence_end"]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_late_write_failure_after_committed_input_still_reports_session_failure():
    from server.realtime.capabilities.asr import AsrTranscriptFinal
    from server.realtime.capabilities.turn_manager import AsrCommitRequested, UserTurnCommitted
    from tests.realtime.test_coordinated_turn_manager import stop

    release = asyncio.Event()

    class FailsLate(InMemoryConversationJournal):
        async def append(self, draft):
            await release.wait()
            raise RuntimeError("must not expose password")

    session = await opened(input_evidence_journal=FailsLate(), eot_classifier=Endpoint())
    stream = session.events()
    try:
        await start(session)
        await text(session)
        await stop(session)
        await take(stream, AsrCommitRequested)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=context(), revision=2, text="查北京天气", reason="final")))
        await take(stream, UserTurnCommitted)
        assert session._input is None
        release.set()
        failure = await take(stream, SemanticInputRejected)
        assert failure.reason == "input_evidence_unavailable"
        assert not failure.evidence_saved
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_final_ack_after_budget_rejection_cannot_commit():
    from server.realtime.capabilities.asr import AsrTranscriptFinal
    from server.realtime.capabilities.turn_manager import AsrCommitRequested
    from tests.realtime.test_coordinated_turn_manager import stop

    session = await opened(input_budget=SemanticInputBudget(max_text_bytes=12), eot_classifier=Endpoint())
    stream = session.events()
    try:
        await start(session)
        await text(session, "北京天气")
        await stop(session)
        await take(stream, AsrCommitRequested)
        await text(session, "北京上海明天天气", revision=2)
        await take(stream, SemanticInputRejected)
        await session.send(ObserveAsrEvent(event=AsrTranscriptFinal(
            context=context(), revision=3, text="北京天气", reason="final")))
        assert session._input.blocked
        assert session._last_committed is None
    finally:
        await session.close()


@pytest.mark.parametrize("budget,reason", [
    (SemanticInputBudget(max_revisions=1), "input_revisions"),
    (SemanticInputBudget(max_evidence_bytes=1), "input_evidence_bytes"),
])
@pytest.mark.asyncio
async def test_revision_and_evidence_budgets_have_explicit_failure(budget, reason):
    session = await opened(input_evidence_journal=DurableMemoryJournal(), input_budget=budget)
    try:
        await start(session)
        await text(session, "查北京")
        if reason == "input_revisions":
            await text(session, "查上海", revision=2)
        failure = await take(session.events(), SemanticInputRejected)
        assert failure.reason == reason
    finally:
        await session.close()


@pytest.mark.parametrize("field", ["max_text_bytes", "max_revisions", "max_chunks", "max_duration_ms", "max_evidence_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_budget_limits_require_positive_integer_values(field, value):
    with pytest.raises(ValueError, match="positive integers"):
        SemanticInputBudget(**{field: value})


def test_budget_thresholds_use_utf8_and_absolute_duration():
    budget = SemanticInputBudget(max_text_bytes=6, max_revisions=2, max_duration_ms=100)
    assert budget.violation("北京", revisions=2, elapsed_ms=99) is None
    assert budget.violation("北京啊", revisions=2, elapsed_ms=99) == "input_text_bytes"
    assert budget.violation("ok", revisions=3, elapsed_ms=99) == "input_revisions"
    assert budget.violation("ok", revisions=2, elapsed_ms=100) == "input_duration"


@pytest.mark.asyncio
async def test_oversized_uncaptured_payload_reports_missing_evidence_and_is_released_on_close():
    session = await opened(input_evidence_journal=DurableMemoryJournal())
    try:
        payload = "大" * 20000
        await text(session, payload)
        failure = await take(session.events(), SemanticInputRejected)
        assert not failure.evidence_saved
        assert session._input.rejected_text == payload
        records = (await read_input_evidence(session._provider.input_evidence_journal, context()))["records"]
        assert records[-1]["detail"]["capture_complete"] is False
        assert records[-1]["detail"]["text"] is None
    finally:
        await session.close()
    assert session._input is None


@pytest.mark.asyncio
async def test_late_storage_failure_after_rule_discard_still_reports_failure():
    from server.realtime.capabilities.turn_manager import ObserveSystemResponseStarted
    from tests.realtime.test_coordinated_turn_manager import stop

    release = asyncio.Event()

    class FailsLate(InMemoryConversationJournal):
        async def append(self, draft):
            await release.wait()
            raise RuntimeError("storage unavailable")

    session = await opened(input_evidence_journal=FailsLate(), eot_classifier=Endpoint())
    stream = session.events()
    try:
        await session.send(ObserveSystemResponseStarted(response_id="a", context=context()))
        await start(session)
        await text(session, "嗯嗯")
        await stop(session)
        await take(stream, AsrDiscardRequested)
        assert session._input is None
        release.set()
        rejected = await take(stream, SemanticInputRejected)
        assert rejected.reason == "input_evidence_unavailable" and not rejected.evidence_saved
    finally:
        await session.close()
