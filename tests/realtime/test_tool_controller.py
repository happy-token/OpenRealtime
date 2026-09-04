from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    InMemoryConversationJournal,
    JournalScope,
    StructuredContent,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendItem,
    ConfirmationRequested,
    DisplayContentDelta,
    ProjectCommittedItem,
    ToolRequested,
)
from server.realtime.tool_controller import RealtimeToolController
from server.tools.canonical import LatencyClass
from server.tools.control import ToolControlResult
from server.tools.policy_gateway import ToolOrigin, ToolRequest


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
        response_id="response-1",
    )


class RecordingConversation:
    def __init__(self) -> None:
        self.commands = []
        self.event_queue = asyncio.Queue()

    async def send(self, command) -> None:
        self.commands.append(command)

    async def events(self):
        while True:
            event = await self.event_queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        await self.event_queue.put(None)


class RejectingSendConversation(RecordingConversation):
    async def send(self, command) -> None:
        del command
        raise RuntimeError("projection unavailable")


@dataclass(slots=True)
class GatedToolHandler:
    release: asyncio.Event
    calls: int = 0

    async def handle(self, action, cancellation) -> ToolControlResult:
        self.calls += 1
        await self.release.wait()
        assert cancellation.is_cancelled is False
        return ToolControlResult(
            call_id=action.call_id,
            success=True,
            model_output="12:30",
        )


class RecordingCanonicalToolHandler:
    def __init__(self) -> None:
        self.request: ToolRequest | None = None

    async def handle(self, request, cancellation) -> ToolControlResult:
        assert cancellation.is_cancelled is False
        self.request = request
        return ToolControlResult(
            call_id=request.call_id,
            success=True,
            model_output="12:30",
        )


async def test_tool_controller_uses_canonical_request_without_legacy_action() -> None:
    delegate = RecordingConversation()
    handler = RecordingCanonicalToolHandler()
    controller = RealtimeToolController(
        context=context(),
        conversation=delegate,
        tool_control_handler_factory=lambda: handler,
    )
    await delegate.event_queue.put(
        ToolRequested(
            event_id="tool-canonical",
            context=replace(context(), call_id="call-1"),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=2,
            call_id="call-1",
            tool_name="get_current_datetime",
            tool_version="1",
            arguments={"timezone": "Asia/Shanghai"},
            latency=LatencyClass.FAST,
            origin=ToolOrigin.PIPELINE_BRAIN,
        )
    )

    while not delegate.commands:
        await asyncio.sleep(0)
    assert isinstance(handler.request, ToolRequest)
    assert handler.request.origin is ToolOrigin.PIPELINE_BRAIN
    assert isinstance(delegate.commands[0], AppendItem)
    await controller.close()


async def test_tool_controller_forwards_stream_while_tool_runs_then_appends_result() -> None:
    delegate = RecordingConversation()
    release = asyncio.Event()
    controller = RealtimeToolController(
        context=context(),
        conversation=delegate,
        tool_control_handler_factory=lambda: GatedToolHandler(release),
    )
    events = controller.events()
    requested_context = replace(context(), call_id="call-1")
    await delegate.event_queue.put(
        ToolRequested(
            event_id="tool-1",
            context=requested_context,
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=2,
            call_id="call-1",
            tool_name="get_current_datetime",
            tool_version="1",
            arguments={"timezone": "Asia/Shanghai"},
            latency=LatencyClass.FAST,
        )
    )
    await delegate.event_queue.put(
        DisplayContentDelta(
            event_id="ack-1",
            context=context(),
            conversation_sequence=2,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=3,
            delta="我查一下。",
        )
    )

    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ToolRequested)
    streamed = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(streamed, DisplayContentDelta)
    assert delegate.commands == []

    release.set()
    while not delegate.commands:
        await asyncio.sleep(0)
    appended = delegate.commands[0]
    assert isinstance(appended, AppendItem)
    assert appended.context.call_id == "call-1"
    assert appended.context.response_id == "response-1"
    assert appended.draft.status is ConversationItemStatus.COMPLETED
    assert appended.draft.content[0].text == "12:30"
    assert appended.draft.visibility == frozenset(
        {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
    )
    assert appended.draft.provider_metadata == {
        "call_id": "call-1",
        "success": True,
        "tool_name": "get_current_datetime",
        "tool_version": "1",
    }
    await controller.close()


async def test_tool_controller_executes_duplicate_call_id_only_once() -> None:
    delegate = RecordingConversation()
    release = asyncio.Event()
    handler = GatedToolHandler(release)
    controller = RealtimeToolController(
        context=context(),
        conversation=delegate,
        tool_control_handler_factory=lambda: handler,
    )
    requested = ToolRequested(
        event_id="tool-1",
        context=replace(context(), call_id="call-1"),
        conversation_sequence=1,
        occurred_at=datetime.now(UTC),
        response_id="response-1",
        response_sequence=2,
        call_id="call-1",
        tool_name="get_current_datetime",
        tool_version="1",
        arguments={},
        latency=LatencyClass.FAST,
    )

    await delegate.event_queue.put(requested)
    release.set()
    while not delegate.commands:
        await asyncio.sleep(0)
    await delegate.event_queue.put(replace(requested, event_id="tool-duplicate"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert handler.calls == 1
    assert len(delegate.commands) == 1
    await controller.close()


async def test_tool_controller_reuses_one_budgeted_handler_per_response() -> None:
    delegate = RecordingConversation()
    release = asyncio.Event()
    factory_calls = 0

    def handler_factory():
        nonlocal factory_calls
        factory_calls += 1
        return GatedToolHandler(release)

    controller = RealtimeToolController(
        context=context(),
        conversation=delegate,
        tool_control_handler_factory=handler_factory,
    )
    for index in (1, 2):
        await delegate.event_queue.put(
            ToolRequested(
                event_id=f"tool-{index}",
                context=replace(context(), call_id=f"call-{index}"),
                conversation_sequence=index,
                occurred_at=datetime.now(UTC),
                response_id="response-1",
                response_sequence=index,
                call_id=f"call-{index}",
                tool_name="get_current_datetime",
                tool_version="1",
                arguments={},
                latency=LatencyClass.FAST,
            )
        )
    release.set()
    while len(delegate.commands) < 2:
        await asyncio.sleep(0)

    assert factory_calls == 1
    await controller.close()


class JournaledToolHandler:
    def __init__(self, journal: InMemoryConversationJournal) -> None:
        self._journal = journal
        self._committed = None
        self._projection = ()

    async def handle(self, action, cancellation) -> ToolControlResult:
        del cancellation
        request = await self._journal.append(
            ConversationItemDraft(
                item_id="tool-request-1",
                context=action.context,
                kind=ConversationItemKind.TOOL_REQUESTED,
                status=ConversationItemStatus.COMMITTED,
                producer="test-tool-loop",
                content=(StructuredContent({"tool_name": action.tool_name}),),
                visibility=frozenset(
                    {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
                ),
            )
        )
        result = await self._journal.append(
            ConversationItemDraft(
                item_id="tool-result-1",
                context=action.context,
                kind=ConversationItemKind.TOOL_RESULT,
                status=ConversationItemStatus.COMPLETED,
                producer="test-tool-loop",
                content=(TextContent("12:30"),),
                visibility=frozenset(
                    {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
                ),
            )
        )
        self._committed = result.item
        self._projection = (request.item, result.item)
        return ToolControlResult(
            call_id=action.call_id,
            success=True,
            model_output="12:30",
        )

    def committed_tool_result(self, call_id):
        assert call_id == "call-1"
        return self._committed

    def committed_tool_items(self, call_id):
        assert call_id == "call-1"
        return self._projection


class ConfirmationToolHandler:
    def __init__(self, journal: InMemoryConversationJournal) -> None:
        self._journal = journal
        self._projection = ()

    async def handle(self, request, cancellation) -> ToolControlResult:
        del cancellation
        confirmation_context = replace(
            request.context,
            confirmation_id="confirmation-1",
        )
        requested = await self._journal.append(
            ConversationItemDraft(
                item_id="tool-request-confirmation",
                context=request.context,
                kind=ConversationItemKind.TOOL_REQUESTED,
                status=ConversationItemStatus.COMMITTED,
                producer="test-tool-loop",
                content=(StructuredContent({"tool_name": request.tool_name}),),
            )
        )
        confirmation = await self._journal.append(
            ConversationItemDraft(
                item_id="confirmation-request-1",
                context=confirmation_context,
                kind=ConversationItemKind.CONFIRMATION_REQUESTED,
                status=ConversationItemStatus.COMMITTED,
                producer="tool-policy-gateway",
                content=(
                    StructuredContent(
                        {
                            "confirmation_id": "confirmation-1",
                            "action_digest": "a" * 64,
                            "action_summary": "向外部发送消息",
                            "required_channel": "voice",
                            "expires_at": datetime.now(UTC).isoformat(),
                        }
                    ),
                ),
            )
        )
        self._projection = (requested.item, confirmation.item)
        return ToolControlResult(
            call_id=request.call_id,
            success=False,
            model_output="需要确认：向外部发送消息",
            error_code="confirmation_required",
        )

    def committed_tool_items(self, call_id):
        assert call_id == "call-1"
        return self._projection


async def test_tool_controller_emits_confirmation_from_authoritative_committed_item() -> None:
    delegate = RecordingConversation()
    projection = RecordingConversation()
    handler = ConfirmationToolHandler(InMemoryConversationJournal())
    controller = RealtimeToolController(
        context=context(),
        conversation=delegate,
        committed_projection=projection,
        tool_control_handler_factory=lambda: handler,
    )
    events = controller.events()
    await delegate.event_queue.put(
        ToolRequested(
            event_id="tool-1",
            context=replace(context(), call_id="call-1"),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=2,
            call_id="call-1",
            tool_name="send_message",
            tool_version="1",
            arguments={"text": "hello"},
            latency=LatencyClass.FAST,
        )
    )

    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ToolRequested)
    confirmation = await asyncio.wait_for(anext(events), timeout=0.2)
    assert isinstance(confirmation, ConfirmationRequested)
    assert confirmation.confirmation_id == "confirmation-1"
    assert confirmation.summary == "向外部发送消息"
    assert confirmation.context.confirmation_id == "confirmation-1"
    await controller.close()


async def test_tool_controller_projects_complete_committed_tool_chain_in_order() -> None:
    delegate = RecordingConversation()
    projection = RecordingConversation()
    journal = InMemoryConversationJournal()
    handler = JournaledToolHandler(journal)
    controller = RealtimeToolController(
        context=context(),
        conversation=delegate,
        committed_projection=projection,
        tool_control_handler_factory=lambda: handler,
    )
    await delegate.event_queue.put(
        ToolRequested(
            event_id="tool-1",
            context=replace(context(), call_id="call-1"),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=2,
            call_id="call-1",
            tool_name="get_current_datetime",
            tool_version="1",
            arguments={},
            latency=LatencyClass.FAST,
        )
    )

    async with asyncio.timeout(0.2):
        while len(projection.commands) < 2:
            await asyncio.sleep(0)

    assert delegate.commands == []
    assert all(isinstance(command, ProjectCommittedItem) for command in projection.commands)
    assert [command.item.kind for command in projection.commands] == [
        ConversationItemKind.TOOL_REQUESTED,
        ConversationItemKind.TOOL_RESULT,
    ]
    assert [command.item.sequence for command in projection.commands] == [1, 2]
    assert len(await journal.read(JournalScope.from_context(context()))) == 2
    await controller.close()


async def test_tool_controller_surfaces_result_projection_failure() -> None:
    delegate = RejectingSendConversation()
    release = asyncio.Event()
    release.set()
    controller = RealtimeToolController(
        context=context(),
        conversation=delegate,
        tool_control_handler_factory=lambda: GatedToolHandler(release),
    )
    events = controller.events()
    await delegate.event_queue.put(
        ToolRequested(
            event_id="tool-1",
            context=replace(context(), call_id="call-1"),
            conversation_sequence=1,
            occurred_at=datetime.now(UTC),
            response_id="response-1",
            response_sequence=2,
            call_id="call-1",
            tool_name="get_current_datetime",
            tool_version="1",
            arguments={},
            latency=LatencyClass.FAST,
        )
    )

    assert isinstance(await asyncio.wait_for(anext(events), timeout=0.2), ToolRequested)
    failed = await asyncio.wait_for(anext(events), timeout=0.2)
    assert failed.capability == "realtime_tool_result_projection"
    assert "projection unavailable" in failed.error
    await controller.close()
