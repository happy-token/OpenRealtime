"""Restore semantic identities, never an old session's output permission."""

from dataclasses import replace

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    TextContent,
)
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.realtime.capabilities.reply_revision_controller import ReplyRevisionController
from server.realtime.capabilities.turn_manager import (
    AsrCommitRequested,
    ObserveConversationItem,
    ObserveSystemResponseStarted,
    UserTurnCommitted,
)
from server.turn_policy.policy import TurnPolicy
from tests.realtime.test_coordinated_turn_manager import Endpoint, context, start, stop, take, text
from tests.realtime.test_reply_revision_coordination import final


async def history(journal, *, identity, ctx, value, kind=ConversationItemKind.USER_INPUT, **metadata):
    return (await journal.append(ConversationItemDraft(
        item_id=identity, context=ctx, kind=kind, status=ConversationItemStatus.COMPLETED,
        producer="test", content=(TextContent(value),), provider_metadata=metadata,
    ))).item


@pytest.mark.asyncio
async def test_restored_correction_keeps_root_and_versions_without_restarting_old_reply():
    journal = InMemoryConversationJournal()
    original = context()
    user = await history(journal, identity="old-input", ctx=original, value="查北京天气",
        input_id="logical-root", input_observation_id="observation-a", input_version=1,
        transcript_revision=1, admission_reason="semantic_complete")
    reply = await history(journal, identity="old-reply", ctx=replace(original, response_id="reply-a"),
        value="北京晴", kind=ConversationItemKind.ASSISTANT_OUTPUT, response_id="reply-a",
        input_id="logical-root", input_version=1, reply_version=1)
    current = replace(original, voice_session_id="voice-new", turn_id="new-turn", generation=1)
    session = await CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, eot_classifier=Endpoint()).open(context=current)
    stream = session.events()
    try:
        for item in (user, reply, user, reply):
            await session.send(ObserveConversationItem(item=item))
        assert not session.response_delivery_allowed("reply-a")
        assert session.snapshot().response_id is None
        await start(session, current)
        await text(session, "不是，上海", ctx=current)
        await stop(session, current)
        await take(stream, AsrCommitRequested)
        await final(session, current, "不是，上海")
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "查北京天气\n不是，上海"
        assert committed.input_id == "logical-root"
        assert committed.input_version == 2
        assert committed.continuation_of_turn_id == original.turn_id
        await session.send(ObserveSystemResponseStarted(response_id="reply-b", context=committed.context))
        revision = session.response_revision("reply-b")
        assert revision.reply_version == 2
        assert revision.supersedes_response_id == "reply-a"
        assert session.response_delivery_allowed("reply-b")
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_legacy_history_has_a_stable_root_for_corrections():
    journal = InMemoryConversationJournal()
    user = await history(journal, identity="legacy-input", ctx=context(), value="查北京天气")
    current = replace(context(), voice_session_id="voice-new", turn_id="new-turn")
    session = await CoordinatedTurnManagerCapabilityAdapter(TurnPolicy, eot_classifier=Endpoint()).open(context=current)
    stream = session.events()
    try:
        await session.send(ObserveConversationItem(item=user))
        await start(session, current)
        await text(session, "不是，上海", ctx=current)
        await stop(session, current)
        await take(stream, AsrCommitRequested)
        await final(session, current, "不是，上海")
        committed = await take(stream, UserTurnCommitted)
        assert committed.text == "查北京天气\n不是，上海"
        assert (committed.input_id, committed.input_version) == ("legacy-input", 2)
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [
    {"input_id": "root"}, {"input_version": 1}, {"input_version": True},
    {"input_id": "root", "input_version": 0}, {"input_id": "root", "input_version": "1"},
    {"input_id": "root", "input_version": 1, "input_observation_id": 0},
    {"input_id": "root", "input_version": 1, "input_observation_id": ""},
    {"input_id": "root", "input_version": 1, "admission_reason": False},
    {"input_id": "root", "input_version": 1, "transcript_revision": False},
])
async def test_corrupt_input_metadata_fails_restore_without_fabricating_a_version(metadata):
    journal, ledger = InMemoryConversationJournal(), ReplyRevisionController()
    item = await history(journal, identity="bad", ctx=context(), value="查北京天气", **metadata)
    with pytest.raises(ValueError):
        ledger.restore_item(item)
    assert ledger.input is None


@pytest.mark.asyncio
async def test_same_root_cannot_rewind_versions_or_reuse_observation_identity():
    journal, ledger = InMemoryConversationJournal(), ReplyRevisionController()
    first = await history(journal, identity="a", ctx=context(), value="原问题",
        input_id="root", input_version=1, input_observation_id="obs-a")
    ledger.restore_item(first)
    second_ctx = replace(context(), turn_id="second", generation=2)
    second = await history(journal, identity="b", ctx=second_ctx, value="原问题\n补充",
        input_id="root", input_version=2, input_observation_id="obs-b", continuation_of_turn_id=context().turn_id)
    ledger.restore_item(second)
    for index, metadata in enumerate((
        {"input_version": 1},
        {"input_version": 3, "input_observation_id": "obs-b", "continuation_of_turn_id": "second"},
    )):
        item = await history(journal, identity=f"bad-{index}", ctx=context(), value="错版本",
                             input_id="root", **metadata)
        with pytest.raises(ValueError):
            ledger.restore_item(item)
        assert ledger.input.input_version == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["future", "wrong_turn", "wrong_generation", "wrong_response", "boolean_version"])
async def test_corrupt_reply_cannot_be_attached_to_restored_input(change):
    journal, ledger = InMemoryConversationJournal(), ReplyRevisionController()
    user = await history(journal, identity="user", ctx=context(), value="原问题", input_id="root", input_version=1)
    ledger.restore_item(user)
    ctx = replace(context(), response_id="reply")
    metadata = {"response_id": "reply", "input_id": "root", "input_version": 1, "reply_version": 1}
    if change == "future":
        metadata["input_version"] = 2
    elif change == "wrong_turn":
        ctx = replace(ctx, turn_id="other")
    elif change == "wrong_generation":
        ctx = replace(ctx, generation=9)
    elif change == "wrong_response":
        ctx = replace(ctx, response_id="other")
    else:
        metadata["reply_version"] = True
    item = await history(journal, identity="bad-reply", ctx=ctx, value="回答",
                         kind=ConversationItemKind.ASSISTANT_OUTPUT, **metadata)
    with pytest.raises(ValueError):
        ledger.restore_item(item)
    assert ledger.reply is None


@pytest.mark.asyncio
async def test_live_commit_prevents_late_journal_items_from_resetting_state():
    journal, ledger = InMemoryConversationJournal(), ReplyRevisionController()
    old = await history(journal, identity="old", ctx=context(), value="旧问题", input_id="old-root", input_version=1)
    ledger.restore_item(old)
    current = replace(context(), turn_id="live", generation=2)
    revision = ledger.commit_input(input_id="live-root", context=current, text="新问题",
        transcript_revision=1, continuation_of_turn_id=None, admission_reason="semantic_complete")
    reply = ledger.bind_response("live-reply", current)
    late = await history(journal, identity="late", ctx=context(), value="迟到旧问题", input_id="late-root", input_version=1)
    assert not ledger.restore_item(late)
    assert ledger.input == revision and ledger.reply == reply
    assert ledger.delivery_allowed("live-reply")


@pytest.mark.asyncio
async def test_unlinked_manual_reply_stays_history_without_breaking_restore():
    journal, ledger = InMemoryConversationJournal(), ReplyRevisionController()
    user = await history(journal, identity="user", ctx=context(), value="原问题")
    ledger.restore_item(user)
    manual = await history(journal, identity="manual", ctx=replace(context(), response_id="manual"),
        value="外部回答", kind=ConversationItemKind.ASSISTANT_OUTPUT,
        input_id=None, input_version=None, reply_version=1, response_id="manual")
    assert not ledger.restore_item(manual)
    assert ledger.input.input_id == "user" and ledger.reply is None


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ["tenant_id", "user_id", "thread_id"])
async def test_actor_rejects_foreign_thread_history(axis):
    journal = InMemoryConversationJournal()
    foreign = await history(journal, identity="foreign", ctx=replace(context(), **{axis: "other"}), value="外部问题")
    session = await CoordinatedTurnManagerCapabilityAdapter(TurnPolicy).open(context=context())
    try:
        with pytest.raises(ValueError, match="another conversation"):
            await session.send(ObserveConversationItem(item=foreign))
        assert session._revisions.input is None
    finally:
        await session.close()


@pytest.mark.parametrize("lease", [
    {"input_turn_id": "other", "input_generation": 1},
    {"input_turn_id": "", "input_generation": 1},
    {"input_turn_id": context().turn_id, "input_generation": True},
    {"input_turn_id": context().turn_id, "input_generation": 4},
    {"input_turn_id": context().turn_id, "input_generation": -1},
])
async def test_recovered_history_rejects_corrupt_original_input_lease(lease):
    journal, ledger = InMemoryConversationJournal(), ReplyRevisionController()
    user = await history(journal, identity="user", ctx=context(), value="原问题", input_id="root", input_version=1)
    ledger.restore_item(user)
    item = await history(journal, identity="recovered", ctx=replace(context(), response_id="recovered", generation=3),
        value="续答", kind=ConversationItemKind.ASSISTANT_OUTPUT, response_id="recovered",
        input_id="root", input_version=1, reply_version=2, **lease)
    with pytest.raises(ValueError, match="original input lease"):
        ledger.restore_item(item)
    assert ledger.reply is None
