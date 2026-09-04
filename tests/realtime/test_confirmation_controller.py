from __future__ import annotations

from dataclasses import replace

from server.conversation_journal import InMemoryConversationJournal
from server.core.interaction_context import InteractionContext
from server.realtime import ActiveRealtimeConversations, AppendItem, DeliverItem
from server.realtime.confirmation_controller import RealtimeConfirmationController
from server.tools.canonical import (
    CanonicalTool,
    ConfirmationRequirement,
    IdempotencyClass,
    LatencyClass,
    RiskLevel,
    ToolEffect,
)
from server.tools.confirmation import BoundToolConfirmationHandler
from server.tools.fast_loop import FastToolLoop
from server.tools.policy_gateway import (
    ConfirmationChannel,
    DefaultToolPolicyGateway,
    RequireConfirmation,
    ToolExecutor,
    ToolOrigin,
    ToolPolicyContext,
    ToolRequest,
)
from server.tools.registry import ToolRegistry
from server.transport.frames import ConfirmationDecisionFrame


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


class RecordingConversation:
    def __init__(self) -> None:
        self.commands = []

    async def send(self, command) -> None:
        self.commands.append(command)

    async def events(self):
        if False:
            yield

    async def close(self) -> None:
        return None


async def test_confirmation_controller_projects_result_then_schedules_delivery() -> None:
    calls = []

    async def execute(arguments):
        calls.append(arguments)
        return "消息已发送"

    class Source:
        def list_tools(self):
            return [
                CanonicalTool(
                    name="send_message",
                    version="1",
                    description="向外部发送消息",
                    parameters={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    handler=execute,
                    effects=frozenset({ToolEffect.COMMUNICATE_EXTERNAL}),
                    risk=RiskLevel.HIGH,
                    idempotency=IdempotencyClass.IDEMPOTENT,
                    latency=LatencyClass.FAST,
                    confirmation=ConfirmationRequirement.ALWAYS,
                )
            ]

    tools = ToolRegistry([Source()])
    gateway = DefaultToolPolicyGateway(tools)
    journal = InMemoryConversationJournal()
    request_context = replace(
        context(),
        response_id="response-1",
        call_id="call-1",
    )
    request = ToolRequest(
        call_id="call-1",
        tool_name="send_message",
        tool_version="1",
        arguments={"text": "你好"},
        context=request_context,
        origin=ToolOrigin.PIPELINE_BRAIN,
    )
    pending = await FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=journal,
    ).handle(request, ToolPolicyContext())
    assert isinstance(pending, RequireConfirmation)

    active = ActiveRealtimeConversations()
    conversation = RecordingConversation()
    active.register(context=context(), conversation=conversation)
    controller = RealtimeConfirmationController(
        context=context(),
        conversations=active,
        handler=BoundToolConfirmationHandler(
            gateway=gateway,
            executor=ToolExecutor(tools, gateway),
            journal=journal,
        ),
        channel=ConfirmationChannel.VOICE,
    )

    resolution = await controller.handle(
        ConfirmationDecisionFrame(
            confirmation_id=pending.pending.confirmation_id,
            action_digest=request.arguments_digest,
            approved=True,
        )
    )

    assert resolution.success is True
    assert calls == [{"text": "你好"}]
    assert len(conversation.commands) == 3
    assert all(isinstance(command, AppendItem) for command in conversation.commands[:2])
    assert isinstance(conversation.commands[-1], DeliverItem)
    assert conversation.commands[-1].item_id == resolution.result_item.item_id
