"""Version leases are revoked synchronously, independently of async cleanup."""

from dataclasses import FrozenInstanceError, replace

import pytest

from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
from tests.realtime.test_cascaded_capabilities import context


def commit(ledger, *, identity="input-a", ctx=None, text="查北京天气", parent=None):
    return ledger.commit_input(
        input_id=identity, context=ctx or context(), text=text,
        transcript_revision=1, continuation_of_turn_id=parent,
        admission_reason="semantic_complete",
    )


def test_continuation_keeps_logical_identity_and_supersedes_reply():
    ledger = ReplyRevisionController()
    first = commit(ledger)
    reply = ledger.bind_response("reply-a", context())
    assert reply.input_id == first.input_id
    assert reply.input_version == reply.reply_version == 1
    assert ledger.delivery_allowed("reply-a")
    ledger.revoke("reply-a", reason="barge_in_floor_claim")
    assert not ledger.delivery_allowed("reply-a")
    updated = replace(context(), turn_id="turn-b", generation=2)
    second = commit(ledger, identity="input-b", ctx=updated,
                    text="查北京天气\n不是，上海", parent=context().turn_id)
    assert second.input_id == first.input_id
    assert second.input_version == 2
    assert second.supersedes_turn_id == context().turn_id
    newer = ledger.bind_response("reply-b", updated)
    assert newer.reply_version == 2
    assert newer.input_version == 2
    assert newer.supersedes_response_id == "reply-a"
    assert not ledger.delivery_allowed("reply-a")
    assert ledger.delivery_allowed("reply-b")
    ledger.finish("reply-a")  # Late completion cannot settle the new reply.
    assert ledger.delivery_allowed("reply-b")


def test_duplicate_binding_and_commit_are_idempotent_but_not_reusable():
    ledger = ReplyRevisionController()
    first = commit(ledger)
    assert commit(ledger) == first
    with pytest.raises(ValueError):
        commit(ledger, text="查上海天气")
    reply = ledger.bind_response("a", context())
    ledger.revoke("a", reason="cancelled")
    assert not ledger.bind_response("a", context()).delivery_permitted
    with pytest.raises(ValueError):
        ledger.bind_response("a", replace(context(), turn_id="other"))
    with pytest.raises(FrozenInstanceError):
        reply.reply_version = 99


def test_new_topic_does_not_inherit_cumulative_input_version():
    ledger = ReplyRevisionController()
    commit(ledger)
    ledger.bind_response("a", context())
    updated = replace(context(), turn_id="other", generation=2)
    newest = commit(ledger, identity="other-input", ctx=updated, text="查日期")
    assert newest.input_id == "other-input"
    assert newest.input_version == 1
    assert newest.supersedes_turn_id is None
    assert not ledger.delivery_allowed("a")
    assert ledger.bind_response("b", updated).reply_version == 1


def test_playback_fact_and_natural_completion_do_not_restore_revoked_output():
    ledger = ReplyRevisionController()
    commit(ledger)
    ledger.bind_response("a", context())
    ledger.observe_playback("a")
    assert ledger.reply.playback_started
    ledger.finish("a")
    assert ledger.reply.completed
    assert ledger.delivery_allowed("a")  # Queued final text can still be drained.
    ledger.revoke("a", reason="replacement")
    ledger.observe_playback("a")
    ledger.finish("a")
    assert not ledger.delivery_allowed("a")
    assert not ledger.delivery_allowed("unknown")
    ledger.close()
    assert not ledger.delivery_allowed("a")


def test_ledger_retains_only_current_records_without_full_transcript_history():
    ledger = ReplyRevisionController()
    for index in range(1000):
        ctx = replace(context(), turn_id=str(index), generation=index + 1)
        commit(ledger, identity=str(index), ctx=ctx)
        ledger.bind_response(str(index), ctx)
    assert ledger.input.observation_id == "999"
    assert ledger.reply.response_id == "999"
    assert not hasattr(ledger.input, "text")
    assert not ledger.delivery_allowed("0")
