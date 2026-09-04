"""Versioned JSON codecs for durable Agent task records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentCapabilityDescriptor,
    AgentRunHandle,
    AgentRunLocator,
    WorkspaceMode,
)
from server.agent_session.task_models import (
    AgentCandidate,
    AgentSelectionPlan,
    ConfirmationRule,
    DelegationRequest,
    TaskBudget,
)
from server.core.interaction_context import InteractionContext


SCHEMA_VERSION = 1


def encode_request(request: DelegationRequest) -> str:
    return _dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "delegation_request_id": request.delegation_request_id,
            "selection_plan": {
                "plan_id": request.selection_plan.plan_id,
                "version": request.selection_plan.version,
                "primary": _candidate_payload(request.selection_plan.primary),
                "allowed_fallbacks": [
                    _candidate_payload(candidate)
                    for candidate in request.selection_plan.allowed_fallbacks
                ],
                "required_capabilities": sorted(
                    capability.value for capability in request.selection_plan.required_capabilities
                ),
                "confirmation_on_fallback": (request.selection_plan.confirmation_on_fallback.value),
                "fallback_reason_allowlist": sorted(
                    request.selection_plan.fallback_reason_allowlist
                ),
            },
            "instruction": request.instruction,
            "context": context_payload(request.context),
            "workspace_root": request.workspace_root,
            "workspace_mode": request.workspace_mode.value,
            "budget": {
                "max_wall_time_s": request.budget.max_wall_time_s,
                "max_cost_usd": request.budget.max_cost_usd,
                "max_tokens": request.budget.max_tokens,
                "max_descendants": request.budget.max_descendants,
                "max_depth": request.budget.max_depth,
            },
            "input_refs": list(request.input_refs),
            "parent_worker_id": request.parent_worker_id,
            "force_new": request.force_new,
        }
    )


def decode_request(value: object) -> DelegationRequest:
    payload = _object(value, "request_payload")
    _require_version(payload)
    plan_payload = _object(payload.get("selection_plan"), "selection_plan")
    budget_payload = _object(payload.get("budget"), "budget")
    return DelegationRequest(
        delegation_request_id=_text(payload, "delegation_request_id"),
        selection_plan=AgentSelectionPlan(
            plan_id=_text(plan_payload, "plan_id"),
            version=int(plan_payload["version"]),
            primary=_decode_candidate(plan_payload.get("primary")),
            allowed_fallbacks=tuple(
                _decode_candidate(candidate)
                for candidate in _list(plan_payload.get("allowed_fallbacks"))
            ),
            required_capabilities=frozenset(
                AgentCapability(capability)
                for capability in _list(plan_payload.get("required_capabilities"))
            ),
            confirmation_on_fallback=ConfirmationRule(
                _text(plan_payload, "confirmation_on_fallback")
            ),
            fallback_reason_allowlist=frozenset(
                str(reason) for reason in _list(plan_payload.get("fallback_reason_allowlist"))
            ),
        ),
        instruction=_text(payload, "instruction"),
        context=decode_context(payload.get("context")),
        workspace_root=_text(payload, "workspace_root"),
        workspace_mode=WorkspaceMode(_text(payload, "workspace_mode")),
        budget=TaskBudget(
            max_wall_time_s=float(budget_payload["max_wall_time_s"]),
            max_cost_usd=_optional_float(budget_payload.get("max_cost_usd")),
            max_tokens=_optional_int(budget_payload.get("max_tokens")),
            max_descendants=int(budget_payload.get("max_descendants", 0)),
            max_depth=int(budget_payload.get("max_depth", 0)),
        ),
        input_refs=tuple(str(ref) for ref in _list(payload.get("input_refs"))),
        parent_worker_id=_optional_text(payload.get("parent_worker_id")),
        force_new=bool(payload.get("force_new", False)),
    )


def context_payload(context: InteractionContext) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "device_id": context.device_id,
        "voice_session_id": context.voice_session_id,
        "thread_id": context.thread_id,
        "turn_id": context.turn_id,
        "generation": context.generation,
        "response_id": context.response_id,
        "call_id": context.call_id,
        "worker_id": context.worker_id,
        "confirmation_id": context.confirmation_id,
        "handoff_id": context.handoff_id,
    }


def encode_context(context: InteractionContext) -> str:
    return _dumps(context_payload(context))


def decode_context(value: object) -> InteractionContext:
    payload = _object(value, "context_payload")
    _require_version(payload)
    return InteractionContext(
        tenant_id=_text(payload, "tenant_id"),
        user_id=_text(payload, "user_id"),
        device_id=_text(payload, "device_id"),
        voice_session_id=_text(payload, "voice_session_id"),
        thread_id=_text(payload, "thread_id"),
        turn_id=_text(payload, "turn_id"),
        generation=int(payload["generation"]),
        response_id=_optional_text(payload.get("response_id")),
        call_id=_optional_text(payload.get("call_id")),
        worker_id=_optional_text(payload.get("worker_id")),
        confirmation_id=_optional_text(payload.get("confirmation_id")),
        handoff_id=_optional_text(payload.get("handoff_id")),
    )


def encode_handle(handle: AgentRunHandle | None) -> str | None:
    if handle is None:
        return None
    return _dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "worker_id": handle.worker_id,
            "dispatch_token": handle.dispatch_token,
            "locator": {
                "driver_kind": handle.locator.driver_kind,
                "backend_session_id": handle.locator.backend_session_id,
                "backend_run_id": handle.locator.backend_run_id,
            },
            "capabilities": {
                "driver_kind": handle.capabilities.driver_kind,
                "driver_version": handle.capabilities.driver_version,
                "protocol_version": handle.capabilities.protocol_version,
                "values": sorted(
                    capability.value for capability in handle.capabilities.capabilities
                ),
            },
        }
    )


def decode_handle(value: object) -> AgentRunHandle | None:
    if value is None:
        return None
    payload = _object(value, "handle_payload")
    _require_version(payload)
    locator = _object(payload.get("locator"), "locator")
    capabilities = _object(payload.get("capabilities"), "capabilities")
    return AgentRunHandle(
        worker_id=_text(payload, "worker_id"),
        dispatch_token=_text(payload, "dispatch_token"),
        locator=AgentRunLocator(
            driver_kind=_text(locator, "driver_kind"),
            backend_session_id=_text(locator, "backend_session_id"),
            backend_run_id=_optional_text(locator.get("backend_run_id")),
        ),
        capabilities=AgentCapabilityDescriptor(
            driver_kind=_text(capabilities, "driver_kind"),
            driver_version=_text(capabilities, "driver_version"),
            protocol_version=_text(capabilities, "protocol_version"),
            capabilities=frozenset(
                AgentCapability(capability) for capability in _list(capabilities.get("values"))
            ),
        ),
    )


def _candidate_payload(candidate: AgentCandidate) -> dict[str, Any]:
    return {
        "agent_name": candidate.agent_name,
        "model": candidate.model,
        "required_capabilities": sorted(
            capability.value for capability in candidate.required_capabilities
        ),
    }


def _decode_candidate(value: object) -> AgentCandidate:
    payload = _object(value, "candidate")
    return AgentCandidate(
        agent_name=_text(payload, "agent_name"),
        model=_optional_text(payload.get("model")),
        required_capabilities=frozenset(
            AgentCapability(capability)
            for capability in _list(payload.get("required_capabilities"))
        ),
    )


def _object(value: object, name: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("JSON value must be a list")
    return value


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional JSON value must be a string or null")
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _require_version(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported Agent task payload version: {payload.get('schema_version')}")


def _dumps(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
