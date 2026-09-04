from __future__ import annotations

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentCapabilityDescriptor,
    AgentRunHandle,
    AgentRunLocator,
    WorkspaceMode,
)
from server.agent_session.task_codec import (
    decode_context,
    decode_handle,
    decode_request,
    encode_context,
    encode_handle,
    encode_request,
)
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    ConfirmationRule,
    DelegationRequest,
    TaskBudget,
)
from server.core.interaction_context import InteractionContext


def test_durable_request_and_context_codec_round_trip() -> None:
    context = InteractionContext(
        tenant_id="tenant",
        user_id="user",
        device_id="device",
        voice_session_id="voice",
        thread_id="thread",
        turn_id="turn",
        generation=2,
        confirmation_id="confirmation",
    )
    request = DelegationRequest(
        delegation_request_id="request",
        selection_plan=AgentSelectionPlan(
            plan_id="plan",
            version=3,
            primary=AgentCandidate(
                "codex",
                required_capabilities=frozenset({AgentCapability.EVENT_STREAM}),
                model="gpt-test",
            ),
            allowed_fallbacks=(AgentCandidate("claude"),),
            required_capabilities=frozenset({AgentCapability.CANCEL}),
            confirmation_on_fallback=ConfirmationRule.STRONG,
            fallback_reason_allowlist=frozenset({"backend_unavailable"}),
        ),
        instruction="Do the work",
        context=context,
        workspace_root="/workspace",
        workspace_mode=WorkspaceMode.PRIVATE_WRITABLE,
        budget=TaskBudget(
            max_wall_time_s=90,
            max_cost_usd=1.25,
            max_tokens=5_000,
            max_descendants=2,
            max_depth=1,
        ),
        input_refs=("artifact-1",),
        parent_worker_id="parent",
    )

    assert decode_request(encode_request(request)) == request
    assert decode_context(encode_context(context)) == context


def test_durable_handle_codec_round_trip() -> None:
    handle = AgentRunHandle(
        worker_id="worker",
        dispatch_token="dispatch",
        locator=AgentRunLocator("codex", "thread", "turn"),
        capabilities=AgentCapabilityDescriptor(
            driver_kind="codex",
            driver_version="1",
            protocol_version="2",
            capabilities=frozenset({AgentCapability.EVENT_STREAM, AgentCapability.STATUS_LOOKUP}),
        ),
    )

    assert decode_handle(encode_handle(handle)) == handle
    assert decode_handle(None) is None
