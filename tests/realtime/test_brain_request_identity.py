"""Attempt identity, cancellation and actual Core event admission."""

import asyncio

import pytest

from server.core.turn_content import TurnContent
from server.realtime import (
    DisplayContentDelta,
    RequestResponse,
    ResponseCompleted,
    ResponseFailed,
    ToolRequested,
)
from server.realtime.capabilities.brain import (
    BrainDelegationRequested,
    BrainResponseCompleted,
    BrainResponseFailed,
    BrainResponseStarted,
    BrainTextDelta,
    BrainToolRequested,
    CancelBrainResponse,
    LegacyBrainCapabilityAdapter,
    RequestBrainResponse,
    SubmitBrainToolResult,
)
from server.realtime.capabilities.brain_streaming import BrainDelegationCall, BrainToolCall
from server.realtime.journaled import JournaledRealtimeConversation
from server.tools.canonical import LatencyClass
from tests.realtime.test_cascaded_capabilities import context
from tests.realtime.test_input_association_production import wait_for
from tests.realtime.test_reply_revision_production_delivery import append_user, open_core


class TextBrain:
    def __init__(self):
        self.calls = 0

    async def stream(self, turn):
        self.calls += 1
        yield turn.text


@pytest.mark.parametrize("command", [
    RequestBrainResponse(response_id="same", turn=TurnContent(text="输入", generation=1)),
    CancelBrainResponse(response_id="same", reason="cancel"),
    SubmitBrainToolResult(response_id="same", call_id="call", success=True, model_output="结果"),
])
@pytest.mark.parametrize("token", [" ", b"token", 123, True, object()])
async def test_supplied_attempt_token_has_a_strict_nonempty_string_boundary(command, token):
    from dataclasses import replace

    with pytest.raises(ValueError, match="request token"):
        replace(command, request_token=token)


@pytest.mark.parametrize("token", [None, "attempt-1"])
@pytest.mark.parametrize("when", ["before_run", "started_blocked"])
async def test_cancel_before_provider_or_started_enqueue_releases_request_identity(token, when):
    brain = TextBrain()
    session = await LegacyBrainCapabilityAdapter(brain).open(context=context())
    session._events = asyncio.Queue(maxsize=1)
    session._events.put_nowait(BrainResponseStarted(context=context(), response_id="other"))
    command = RequestBrainResponse(response_id="same", turn=TurnContent(text="有效回复", generation=1),
                                   request_token=token)
    try:
        await session.send(command)
        if when == "started_blocked":
            await asyncio.sleep(0)
            assert session._events._putters
        assert brain.calls == 0
        await asyncio.wait_for(session.send(CancelBrainResponse(
            response_id="same", reason="rebuild", request_token=token)), .5)
        assert not session._requests
        assert brain.calls == 0
        assert session._events.get_nowait().response_id == "other"
        await session.send(command)
        stream = session.events()
        async with asyncio.timeout(.5):
            received = [await anext(stream) for _ in range(3)]
        assert [type(event) for event in received] == [BrainResponseStarted, BrainTextDelta, BrainResponseCompleted]
        assert all(event.request_token == token for event in received)
        assert brain.calls == 1
        await stream.aclose()
    finally:
        while not session._events.empty():
            session._events.get_nowait()
        await session.close()


class ToolBrain:
    def __init__(self):
        self.feedback = []

    async def stream_with_tools(self, turn, *, tool_results):
        yield BrainToolCall(call_id="call", tool_name="test", tool_version="1", arguments={},
                            latency=LatencyClass.FAST)
        self.feedback.append(await tool_results.wait("call"))
        yield self.feedback[-1].model_output


@pytest.mark.parametrize("stale_token", [None, "old"])
async def test_old_cancel_or_tool_feedback_cannot_affect_new_attempt(stale_token):
    brain = ToolBrain()
    session = await LegacyBrainCapabilityAdapter(brain).open(context=context())
    stream = session.events()
    try:
        await session.send(RequestBrainResponse(response_id="same", request_token="current",
                                                turn=TurnContent(text="查一下", generation=1)))
        assert isinstance(await anext(stream), BrainResponseStarted)
        tool = await anext(stream)
        assert isinstance(tool, BrainToolRequested) and tool.request_token == "current"
        await session.send(CancelBrainResponse(response_id="same", reason="late", request_token=stale_token))
        assert "same" in session._requests
        with pytest.raises(ValueError, match="attempt"):
            await session.send(SubmitBrainToolResult(response_id="same", request_token=stale_token,
                call_id="call", success=True, model_output="旧结果"))
        assert brain.feedback == []
        await session.send(SubmitBrainToolResult(response_id="same", request_token="current",
            call_id="call", success=True, model_output="正确结果"))
        text, completed = await anext(stream), await anext(stream)
        assert text.delta == "正确结果"
        assert isinstance(completed, BrainResponseCompleted)
        assert text.request_token == completed.request_token == "current"
    finally:
        await stream.aclose()
        await session.close()


@pytest.mark.parametrize("failed", [False, True])
async def test_attempt_token_survives_all_brain_event_types(failed):
    class Brain:
        async def stream(self, turn):
            yield BrainToolCall(call_id="call", tool_name="test", tool_version="1", arguments={},
                                latency=LatencyClass.FAST)
            yield BrainDelegationCall(delegation_request_id="work", instruction="inspect")
            yield "结果"
            if failed:
                raise RuntimeError("provider failed")

    session = await LegacyBrainCapabilityAdapter(Brain()).open(context=context())
    try:
        await session.send(RequestBrainResponse(response_id="same", request_token="attempt",
                                                turn=TurnContent(text="查一下", generation=1)))
        received = []
        async with asyncio.timeout(.5):
            async for event in session.events():
                received.append(event)
                if isinstance(event, (BrainResponseCompleted, BrainResponseFailed)):
                    break
        assert {type(event) for event in received} == {
            BrainResponseStarted, BrainToolRequested, BrainDelegationRequested, BrainTextDelta,
            BrainResponseFailed if failed else BrainResponseCompleted,
        }
        assert all(event.request_token == "attempt" for event in received)
    finally:
        await session.close()


async def test_actual_core_ignores_every_queued_old_attempt_event_including_terminals():
    from server.conversation_journal import InMemoryConversationJournal

    class Brain:
        def __init__(self):
            self.calls = 0

        async def stream(self, turn):
            self.calls += 1
            if self.calls == 1:
                yield BrainToolCall(call_id="old-tool", tool_name="test", tool_version="1", arguments={},
                                    latency=LatencyClass.FAST)
                yield BrainDelegationCall(delegation_request_id="old-work", instruction="old")
                yield "过期内容"
            else:
                yield "当前内容"

    brain = Brain()
    core = await open_core(brain=brain)
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(),
                                                 engine_conversation=core)
    try:
        await core._brain.send(RequestBrainResponse(response_id="same", request_token="old",
                                                    turn=TurnContent(text="旧输入", generation=1)))
        await wait_for(lambda: "same" not in core._brain._requests)
        core._brain._events.put_nowait(BrainResponseFailed(context=context(), response_id="same",
            response_sequence=6, error="old failure", request_token="old"))
        await append_user(conversation)
        await conversation.send(RequestResponse(command_id="current", idempotency_key="current",
            context=context(), response_id="same", minimum_thread_sequence=1))
        received = []
        async with asyncio.timeout(1):
            async for event in conversation.events():
                received.append(event)
                if isinstance(event, ResponseCompleted):
                    break
        assert [event.delta for event in received if isinstance(event, DisplayContentDelta)] == ["当前内容"]
        assert not any(isinstance(event, ToolRequested) for event in received)
        assert not any(getattr(event, "delegation_request_id", None) == "old-work" for event in received)
        assert brain.calls == 2
    finally:
        await conversation.close()


@pytest.mark.parametrize("behavior", ["finite", "blocked", "flood"])
async def test_non_echoing_brain_session_fails_explicitly_and_releases_all_owners(monkeypatch, behavior):
    from dataclasses import replace

    from server.conversation_journal import InMemoryConversationJournal

    class Brain(TextBrain):
        async def stream(self, turn):
            self.calls += 1
            if behavior == "blocked":
                await asyncio.Event().wait()
            while True:
                yield turn.text
                if behavior == "finite":
                    return

    brain = Brain()
    core = await open_core(brain=brain)
    conversation = JournaledRealtimeConversation(context=context(), journal=InMemoryConversationJournal(),
                                                 engine_conversation=core)
    send = core._brain.send

    async def broken_conformer(command):
        if isinstance(command, RequestBrainResponse):
            command = replace(command, request_token=None)
        await send(command)

    monkeypatch.setattr(core._brain, "send", broken_conformer)
    try:
        await append_user(conversation)
        await conversation.send(RequestResponse(command_id="request", idempotency_key="request",
            context=context(), response_id="same", minimum_thread_sequence=1))
        received = []
        async with asyncio.timeout(.2):
            async for event in conversation.events():
                received.append(event)
                if isinstance(event, ResponseFailed):
                    break
        assert "did not echo the request token" in received[-1].error
        assert not any(isinstance(event, DisplayContentDelta) for event in received)
        await wait_for(lambda: not core._brain._requests and core._response_task is None)
        assert core._brain._closed and core._brain_protocol_failed
        assert not core._detached_response_tasks
        calls = brain.calls
        await conversation.send(RequestResponse(command_id="retry", idempotency_key="retry",
            context=context(), response_id="other", minimum_thread_sequence=1))
        async with asyncio.timeout(.2):
            async for event in conversation.events():
                if isinstance(event, ResponseFailed):
                    assert "requires a new capability session" in event.error
                    break
        assert brain.calls == calls
    finally:
        await conversation.close()


async def test_previous_owner_done_callback_cannot_remove_new_same_id_request():
    release = asyncio.Event()

    class Brain(TextBrain):
        async def stream(self, turn):
            self.calls += 1
            if self.calls == 2:
                await release.wait()
            yield turn.text

    session = await LegacyBrainCapabilityAdapter(Brain()).open(context=context())
    stream = session.events()
    try:
        await session.send(RequestBrainResponse(response_id="same", request_token="old",
                                                turn=TurnContent(text="旧候选", generation=1)))
        # Queue reads complete without yielding. The old run released ownership,
        # but its scheduled done callback has not yet had a chance to execute.
        for _ in range(3):
            await anext(stream)
        await session.send(RequestBrainResponse(response_id="same", request_token="new",
                                                turn=TurnContent(text="新候选", generation=1)))
        current = session._requests["same"]
        await asyncio.sleep(0)
        assert session._requests["same"] is current
        assert current.request_token == "new"
        await session.send(CancelBrainResponse(response_id="same", request_token="old", reason="late"))
        assert session._requests["same"] is current
        release.set()
        received = []
        async with asyncio.timeout(.5):
            async for event in stream:
                received.append(event)
                if isinstance(event, BrainResponseCompleted):
                    break
        assert all(event.request_token == "new" for event in received)
        assert [event.delta for event in received if isinstance(event, BrainTextDelta)] == ["新候选"]
    finally:
        release.set()
        await stream.aclose()
        await session.close()
