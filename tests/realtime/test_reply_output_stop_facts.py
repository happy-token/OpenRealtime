"""Stop operation evidence never restores reply delivery permission."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
from server.realtime.protocol.commands import RecordOutputStop
from server.realtime.protocol.playback import ReplyPlayback
from tests.realtime.test_automatic_context_repair import automatic_reply
from tests.realtime.test_output_stop_storage import confirmed, requested
from tests.realtime.test_realtime_websocket_bridge import context


def ledger():
    revisions = ReplyRevisionController()
    ctx = replace(context(), response_id="a")
    revisions.commit_input(input_id="input", context=ctx, text="说两句", transcript_revision=1,
        continuation_of_turn_id=None, admission_reason="semantic_complete")
    revisions.bind_response("a", ctx)
    revisions.observe_playback_fact("a", ctx, ReplyPlayback(output_epoch="epoch", speech_id="response:a",
        played_audio_end_us=500000, confirmed_text_end=0, observed_at_ns=1, position_precision="sample",
        played_position_samples=500, sample_rate_hz=1000))
    revisions.revoke("a", reason="barge_in_floor_claim")
    fact = replace(requested(), context=ctx, operation_sequence=1)
    return revisions, fact


def test_requested_confirmed_and_duplicate_stop_facts_do_not_restore_permission():
    revisions, fact = ledger()
    assert revisions.observe_output_stop(fact)
    assert revisions.output_stop == fact
    done = confirmed(fact)
    assert revisions.observe_output_stop(done)
    assert not revisions.observe_output_stop(fact)
    assert not revisions.observe_output_stop(done)
    assert revisions.output_stop == done
    assert not revisions.reply.delivery_permitted
    assert revisions.reply.playback.played_position_samples == 500
    assert revisions.reply.context_repair_permit is None


def test_unknown_stop_cannot_be_rewritten_as_confirmation():
    revisions, fact = ledger()
    unknown = replace(fact, state="STOP_UNKNOWN", failure_reason="receipt_deadline")
    revisions.observe_output_stop(unknown)
    with pytest.raises(ValueError, match="terminal stop evidence"):
        revisions.observe_output_stop(confirmed(fact))
    assert revisions.output_stop == unknown and not revisions.reply.delivery_permitted


@pytest.mark.parametrize("field", ["tenant_id", "user_id", "device_id", "voice_session_id", "thread_id", "turn_id", "response_id", "generation"])
def test_stop_fact_from_another_reply_lease_is_ignored(field):
    revisions, fact = ledger()
    wrong = replace(fact, context=replace(fact.context, **{field: 2 if field == "generation" else "other"}))
    assert not revisions.observe_output_stop(wrong)
    assert revisions.output_stop is None and not revisions.reply.delivery_permitted


@pytest.mark.parametrize("field", ["speech_id", "output_epoch"])
def test_stop_fact_from_another_renderer_target_is_ignored(field):
    revisions, fact = ledger()
    assert not revisions.observe_output_stop(replace(fact, **{field: "other"}))
    assert revisions.output_stop is None


def test_server_operation_sequence_orders_stops_without_wall_clock_assumptions():
    revisions, first = ledger()
    revisions.observe_output_stop(first)
    second = replace(first, stop_command_id="stop-2", operation_sequence=2,
        requested_at=first.requested_at - timedelta(seconds=1), observed_at=first.observed_at - timedelta(seconds=1))
    assert revisions.observe_output_stop(second)
    assert revisions.observe_output_stop(confirmed(second))
    assert not revisions.observe_output_stop(confirmed(first))
    assert revisions.output_stop.stop_command_id == "stop-2"
    assert not revisions.reply.delivery_permitted


def test_missing_or_reused_operation_order_cannot_replace_the_current_stop():
    revisions, first = ledger()
    revisions.observe_output_stop(first)
    assert not revisions.observe_output_stop(replace(first, stop_command_id="other", operation_sequence=None))
    assert not revisions.observe_output_stop(replace(first, stop_command_id="other"))
    with pytest.raises(ValueError, match="stop operation identity"):
        revisions.observe_output_stop(replace(first, operation_sequence=2))
    assert revisions.output_stop == first


def test_new_reply_and_close_do_not_inherit_old_stop_authority():
    revisions, fact = ledger()
    revisions.observe_output_stop(confirmed(fact))
    ctx = replace(fact.context, turn_id="next", generation=2, response_id="b")
    revisions.commit_input(input_id="next-input", context=ctx, text="新的问题", transcript_revision=1,
        continuation_of_turn_id=None, admission_reason="semantic_complete")
    revisions.bind_response("b", ctx)
    assert revisions.output_stop is None
    assert not revisions.observe_output_stop(confirmed(fact))
    revisions.close()
    assert not revisions.observe_output_stop(replace(fact, context=ctx, speech_id="response:b"))
    assert revisions.output_stop is None


@pytest.mark.parametrize("wrappers", ["none", "tools", "tools_and_agents"])
async def test_actual_core_observes_only_canonical_saved_stop_and_preserves_failure(monkeypatch, wrappers):
    async with automatic_reply(monkeypatch,
        tool_handler_factory=(lambda: object()) if wrappers != "none" else None,
        supervisor=object() if wrappers == "tools_and_agents" else None) as (core, conversation, _bridge, _brain, _journal, previous, _first, _):
        revisions = core._input_pipeline._turn_manager._revisions
        owner = core._published_brain_output.command.context
        fact = replace(requested(), context=owner, speech_id=f"response:{previous.response_id}", operation_sequence=1)
        entered, release = asyncio.Event(), asyncio.Event()
        record = core._speech_deliveries.record_output_stop

        async def gated(candidate):
            entered.set()
            await release.wait()
            return await record(candidate)

        monkeypatch.setattr(core._speech_deliveries, "record_output_stop", gated)
        task = asyncio.create_task(conversation.send(RecordOutputStop(command_id="request", idempotency_key="request",
            context=owner, fact=fact)))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert revisions.output_stop is None
            release.set()
            await task
            assert revisions.output_stop == fact
            done = confirmed(fact)
            await conversation.send(RecordOutputStop(command_id="confirmed", idempotency_key="confirmed", context=owner, fact=done))
            await conversation.send(RecordOutputStop(command_id="request-replay", idempotency_key="request-replay", context=owner, fact=fact))
            assert revisions.output_stop == done
            assert revisions.reply.delivery_permitted == previous.delivery_permitted

            async def failed(candidate):
                raise RuntimeError("controlled stop storage failure")

            monkeypatch.setattr(core._speech_deliveries, "record_output_stop", failed)
            with pytest.raises(RuntimeError, match="controlled stop storage failure"):
                await conversation.send(RecordOutputStop(command_id="failed", idempotency_key="failed", context=owner,
                    fact=replace(fact, stop_command_id="stop-2", operation_sequence=2)))
            assert revisions.output_stop == done
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
