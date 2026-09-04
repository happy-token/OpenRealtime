from __future__ import annotations

from dataclasses import replace

from server.conversation_journal import (
    ConversationItemKind,
    InMemoryConversationJournal,
    JournalScope,
)
from server.core.interaction_context import InteractionContext
from server.tools.canonical import (
    CanonicalTool,
    ConfirmationRequirement,
    IdempotencyClass,
    LatencyClass,
    RiskLevel,
    ToolEffect,
)
from server.tools.confirmation import (
    BoundToolConfirmationHandler,
    ToolConfirmationDecision,
)
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
        call_id="call-1",
    )


def registry(calls: list[dict[str, object]]) -> ToolRegistry:
    async def send_message(arguments: dict[str, object]) -> str:
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
                    handler=send_message,
                    effects=frozenset({ToolEffect.COMMUNICATE_EXTERNAL}),
                    risk=RiskLevel.HIGH,
                    idempotency=IdempotencyClass.IDEMPOTENT,
                    latency=LatencyClass.FAST,
                    confirmation=ConfirmationRequirement.ALWAYS,
                )
            ]

    return ToolRegistry([Source()])


async def pending_request(
    *, calls: list[dict[str, object]], journal: InMemoryConversationJournal
):
    tools = registry(calls)
    gateway = DefaultToolPolicyGateway(tools)
    loop = FastToolLoop(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=journal,
    )
    request = ToolRequest(
        call_id="call-1",
        tool_name="send_message",
        tool_version="1",
        arguments={"text": "你好"},
        context=context(),
        origin=ToolOrigin.PIPELINE_BRAIN,
    )
    outcome = await loop.handle(request, ToolPolicyContext())
    assert isinstance(outcome, RequireConfirmation)
    return tools, gateway, request, outcome


async def test_bound_confirmation_executes_once_and_journals_exact_decision() -> None:
    calls: list[dict[str, object]] = []
    journal = InMemoryConversationJournal()
    tools, gateway, request, pending = await pending_request(
        calls=calls,
        journal=journal,
    )
    handler = BoundToolConfirmationHandler(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=journal,
    )
    decision = ToolConfirmationDecision(
        confirmation_id=pending.pending.confirmation_id,
        action_digest=request.arguments_digest,
        context=replace(context(), call_id=None),
        channel=ConfirmationChannel.VOICE,
        approved=True,
    )

    first = await handler.resolve(decision)
    replayed = await handler.resolve(decision)

    assert calls == [{"text": "你好"}]
    assert first == replayed
    assert first.success is True
    assert first.model_output == "消息已发送"
    items = await journal.read(JournalScope.from_context(context()))
    assert [item.kind for item in items] == [
        ConversationItemKind.TOOL_REQUESTED,
        ConversationItemKind.CONFIRMATION_REQUESTED,
        ConversationItemKind.CONFIRMATION_DECIDED,
        ConversationItemKind.TOOL_RESULT,
    ]
    assert first.result_item == items[-1]


async def test_bound_confirmation_decline_never_executes_tool() -> None:
    calls: list[dict[str, object]] = []
    journal = InMemoryConversationJournal()
    tools, gateway, request, pending = await pending_request(
        calls=calls,
        journal=journal,
    )
    handler = BoundToolConfirmationHandler(
        gateway=gateway,
        executor=ToolExecutor(tools, gateway),
        journal=journal,
    )

    result = await handler.resolve(
        ToolConfirmationDecision(
            confirmation_id=pending.pending.confirmation_id,
            action_digest=request.arguments_digest,
            context=replace(context(), call_id=None),
            channel=ConfirmationChannel.VOICE,
            approved=False,
        )
    )

    assert calls == []
    assert result.success is False
    assert result.error_code == "confirmation_declined"
    assert result.result_item.status.value == "cancelled"
