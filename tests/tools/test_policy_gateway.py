from __future__ import annotations

from dataclasses import replace

import pytest

from server.core.interaction_context import InteractionContext
from server.tools.canonical import (
    CanonicalTool,
    ConfirmationRequirement,
    IdempotencyClass,
    LatencyClass,
    RiskLevel,
    ToolEffect,
)
from server.tools.policy_gateway import (
    Allow,
    ConfirmationChannel,
    ConfirmationRejected,
    DefaultToolPolicyGateway,
    DelegateBackground,
    Deny,
    GrantRejected,
    RequireConfirmation,
    ToolExecutor,
    ToolOrigin,
    ToolPolicyContext,
    ToolRequest,
)
from server.tools.registry import ToolRegistry


def context(call_id: str = "call-1") -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
        call_id=call_id,
    )


def request(
    *,
    call_id: str = "call-1",
    arguments: dict | None = None,
) -> ToolRequest:
    return ToolRequest(
        call_id=call_id,
        tool_name="weather",
        tool_version="1.0.0",
        arguments=arguments or {"city": "Shanghai"},
        context=context(call_id),
        origin=ToolOrigin.PIPELINE_BRAIN,
    )


def registry(
    handler,
    *,
    risk: RiskLevel = RiskLevel.LOW,
    effects: frozenset[ToolEffect] = frozenset({ToolEffect.READ_PUBLIC}),
    latency: LatencyClass = LatencyClass.FAST,
    confirmation: ConfirmationRequirement = ConfirmationRequirement.POLICY,
) -> ToolRegistry:
    class Source:
        def list_tools(self):
            return [
                CanonicalTool(
                    name="weather",
                    version="1.0.0",
                    description="weather",
                    parameters={
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                        "additionalProperties": False,
                    },
                    handler=handler,
                    effects=effects,
                    risk=risk,
                    idempotency=IdempotencyClass.IDEMPOTENT,
                    latency=latency,
                    confirmation=confirmation,
                )
            ]

    return ToolRegistry([Source()])


@pytest.mark.asyncio
async def test_low_risk_request_gets_bound_single_use_grant() -> None:
    calls: list[dict] = []

    async def handler(arguments: dict) -> str:
        calls.append(arguments)
        return "sunny"

    gateway = DefaultToolPolicyGateway(registry(handler))
    executor = ToolExecutor(registry(handler), gateway)
    tool_request = request()

    decision = await gateway.evaluate(tool_request, ToolPolicyContext())

    assert isinstance(decision, Allow)
    assert decision.grant.arguments_digest == tool_request.arguments_digest
    assert await executor.execute(tool_request, decision.grant) == "sunny"
    with pytest.raises(GrantRejected):
        await executor.execute(tool_request, decision.grant)


@pytest.mark.asyncio
async def test_high_risk_confirmation_is_bound_to_exact_action_and_single_use() -> None:
    async def handler(arguments: dict) -> str:
        return str(arguments)

    gateway = DefaultToolPolicyGateway(
        registry(
            handler,
            risk=RiskLevel.HIGH,
            effects=frozenset({ToolEffect.COMMUNICATE_EXTERNAL}),
        )
    )
    tool_request = request()
    decision = await gateway.evaluate(tool_request, ToolPolicyContext())

    assert isinstance(decision, RequireConfirmation)
    with pytest.raises(ConfirmationRejected):
        await gateway.confirm(
            confirmation_id=decision.pending.confirmation_id,
            action_digest=request(arguments={"city": "Beijing"}).arguments_digest,
            context=context(),
            channel=ConfirmationChannel.VOICE,
            approved=True,
        )

    allowed = await gateway.confirm(
        confirmation_id=decision.pending.confirmation_id,
        action_digest=tool_request.arguments_digest,
        context=context(),
        channel=ConfirmationChannel.VOICE,
        approved=True,
    )
    assert isinstance(allowed, Allow)
    assert allowed.grant.confirmation_id == decision.pending.confirmation_id
    with pytest.raises(ConfirmationRejected):
        await gateway.confirm(
            confirmation_id=decision.pending.confirmation_id,
            action_digest=tool_request.arguments_digest,
            context=context(),
            channel=ConfirmationChannel.VOICE,
            approved=True,
        )


@pytest.mark.asyncio
async def test_strong_confirmation_can_be_safely_declined_from_voice_channel() -> None:
    async def handler(arguments: dict) -> str:
        raise AssertionError("declined action must not execute")

    gateway = DefaultToolPolicyGateway(
        registry(
            handler,
            confirmation=ConfirmationRequirement.STRONG,
        )
    )
    tool_request = request()
    pending = await gateway.evaluate(tool_request, ToolPolicyContext())
    assert isinstance(pending, RequireConfirmation)

    declined = await gateway.confirm(
        confirmation_id=pending.pending.confirmation_id,
        action_digest=tool_request.arguments_digest,
        context=context(),
        channel=ConfirmationChannel.VOICE,
        approved=False,
    )

    assert isinstance(declined, Deny)
    assert declined.reason_code == "confirmation_declined"

@pytest.mark.asyncio
async def test_background_and_critical_tools_fail_outside_inline_execution() -> None:
    async def handler(arguments: dict) -> str:
        raise AssertionError("must not execute")

    background = DefaultToolPolicyGateway(
        registry(handler, latency=LatencyClass.BACKGROUND)
    )
    critical = DefaultToolPolicyGateway(
        registry(
            handler,
            risk=RiskLevel.CRITICAL,
            effects=frozenset({ToolEffect.SPEND_OR_TRANSFER}),
        )
    )

    assert isinstance(
        await background.evaluate(request(), ToolPolicyContext()),
        DelegateBackground,
    )
    assert isinstance(
        await critical.evaluate(request(), ToolPolicyContext()),
        Deny,
    )


@pytest.mark.asyncio
async def test_strict_schema_and_authenticated_scopes_fail_closed() -> None:
    async def handler(arguments: dict) -> str:
        return str(arguments)

    tools = registry(handler)
    binding = tools.resolve_binding("weather", "1.0.0")
    assert binding is not None
    tools = ToolRegistry.from_bindings(
        [
            replace(
                binding,
                descriptor=replace(
                    binding.descriptor,
                    required_scopes=frozenset({"weather:read"}),
                ),
            )
        ]
    )
    gateway = DefaultToolPolicyGateway(tools)

    unknown_field = await gateway.evaluate(
        request(arguments={"city": "Shanghai", "admin": True}),
        ToolPolicyContext(authenticated_scopes=frozenset({"weather:read"})),
    )
    missing_scope = await gateway.evaluate(
        request(call_id="call-2"),
        ToolPolicyContext(),
    )

    assert isinstance(unknown_field, Deny)
    assert unknown_field.reason_code == "invalid_arguments"
    assert isinstance(missing_scope, Deny)
    assert missing_scope.reason_code == "missing_scope"


@pytest.mark.asyncio
async def test_call_identity_is_scoped_to_the_voice_session() -> None:
    async def handler(arguments: dict) -> str:
        return str(arguments)

    gateway = DefaultToolPolicyGateway(registry(handler))
    first = request()
    second = replace(
        first,
        context=replace(first.context, voice_session_id="voice-2"),
    )

    assert isinstance(await gateway.evaluate(first, ToolPolicyContext()), Allow)
    assert isinstance(await gateway.evaluate(second, ToolPolicyContext()), Allow)
