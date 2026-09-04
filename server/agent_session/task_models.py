"""Canonical Agent task selection and lifecycle values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from server.agent_session.driver_protocol import (
    AgentCapability,
    AgentRunHandle,
    WorkspaceMode,
)
from server.core.interaction_context import InteractionContext


class AgentTaskPhase(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"

    @property
    def terminal(self) -> bool:
        return self in {
            AgentTaskPhase.SUCCEEDED,
            AgentTaskPhase.FAILED,
            AgentTaskPhase.CANCELLED,
            AgentTaskPhase.TIMED_OUT,
        }


class BackendHealthState(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ConfirmationRule(StrEnum):
    NOTIFY = "notify"
    REQUIRE = "require"
    STRONG = "strong"


class TaskCreateDisposition(StrEnum):
    CREATED = "created"
    IDEMPOTENT_REUSE = "idempotent_reuse"
    SEMANTIC_REUSE = "semantic_reuse"


@dataclass(frozen=True, slots=True)
class AgentCandidate:
    agent_name: str
    required_capabilities: frozenset[AgentCapability] = frozenset()
    model: str | None = None

    def __post_init__(self) -> None:
        if not self.agent_name:
            raise ValueError("agent_name must be non-empty")


@dataclass(frozen=True, slots=True)
class AgentSelectionPlan:
    plan_id: str
    version: int
    primary: AgentCandidate
    allowed_fallbacks: tuple[AgentCandidate, ...] = ()
    required_capabilities: frozenset[AgentCapability] = frozenset()
    confirmation_on_fallback: ConfirmationRule = ConfirmationRule.NOTIFY
    fallback_reason_allowlist: frozenset[str] = frozenset(
        {"backend_unavailable", "capability_mismatch"}
    )

    def __post_init__(self) -> None:
        if not self.plan_id or self.version < 1:
            raise ValueError("selection plan requires a non-empty id and positive version")
        names = [candidate.agent_name for candidate in self.candidates]
        if len(names) != len(set(names)):
            raise ValueError("selection plan candidates must be unique")

    @property
    def candidates(self) -> tuple[AgentCandidate, ...]:
        return (self.primary, *self.allowed_fallbacks)


@dataclass(frozen=True, slots=True)
class AgentBackendHealth:
    agent_name: str
    state: BackendHealthState
    checked_at: datetime
    reason: str | None = None
    driver_version: str | None = None
    protocol_version: str | None = None


@dataclass(frozen=True, slots=True)
class TaskBudget:
    max_wall_time_s: float = 300.0
    max_cost_usd: float | None = None
    max_tokens: int | None = None
    max_descendants: int = 0
    max_depth: int = 0

    def __post_init__(self) -> None:
        if self.max_wall_time_s <= 0:
            raise ValueError("max_wall_time_s must be positive")
        for value in (self.max_tokens, self.max_descendants, self.max_depth):
            if value is not None and value < 0:
                raise ValueError("task budget values must be non-negative")


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    delegation_request_id: str
    selection_plan: AgentSelectionPlan
    instruction: str
    context: InteractionContext
    workspace_root: str
    workspace_mode: WorkspaceMode
    budget: TaskBudget = field(default_factory=TaskBudget)
    input_refs: tuple[str, ...] = ()
    parent_worker_id: str | None = None
    force_new: bool = False

    def __post_init__(self) -> None:
        if not self.delegation_request_id or not self.instruction or not self.workspace_root:
            raise ValueError("delegation request identity, instruction, and workspace are required")
        if self.context.worker_id is not None:
            raise ValueError("DelegationRequest context cannot carry worker_id before acceptance")

    @property
    def canonical_digest(self) -> str:
        return _digest(self._canonical_payload())

    @property
    def semantic_fingerprint(self) -> str:
        return _digest(
            {
                "tenant_id": self.context.tenant_id,
                "thread_id": self.context.thread_id,
                "turn_id": self.context.turn_id,
                "instruction": " ".join(self.instruction.split()),
                "workspace_root": self.workspace_root,
                "input_refs": list(self.input_refs),
                "parent_worker_id": self.parent_worker_id,
            }
        )

    def _canonical_payload(self) -> dict[str, object]:
        return {
            "delegation_request_id": self.delegation_request_id,
            "force_new": self.force_new,
            "context": {
                "tenant_id": self.context.tenant_id,
                "user_id": self.context.user_id,
                "device_id": self.context.device_id,
                "voice_session_id": self.context.voice_session_id,
                "thread_id": self.context.thread_id,
                "turn_id": self.context.turn_id,
                "generation": self.context.generation,
                "response_id": self.context.response_id,
                "call_id": self.context.call_id,
                "confirmation_id": self.context.confirmation_id,
                "handoff_id": self.context.handoff_id,
            },
            "instruction": " ".join(self.instruction.split()),
            "workspace_root": self.workspace_root,
            "workspace_mode": self.workspace_mode.value,
            "input_refs": list(self.input_refs),
            "parent_worker_id": self.parent_worker_id,
            "budget": {
                "max_wall_time_s": self.budget.max_wall_time_s,
                "max_cost_usd": self.budget.max_cost_usd,
                "max_tokens": self.budget.max_tokens,
                "max_descendants": self.budget.max_descendants,
                "max_depth": self.budget.max_depth,
            },
            "selection_plan": {
                "plan_id": self.selection_plan.plan_id,
                "version": self.selection_plan.version,
                "confirmation_on_fallback": (self.selection_plan.confirmation_on_fallback.value),
                "fallback_reason_allowlist": sorted(self.selection_plan.fallback_reason_allowlist),
                "candidates": [
                    {
                        "name": candidate.agent_name,
                        "model": candidate.model,
                        "required_capabilities": sorted(
                            capability.value for capability in candidate.required_capabilities
                        ),
                    }
                    for candidate in self.selection_plan.candidates
                ],
                "required_capabilities": sorted(
                    capability.value for capability in self.selection_plan.required_capabilities
                ),
            },
        }


@dataclass(frozen=True, slots=True)
class AgentTaskRecord:
    worker_id: str
    delegation_request_id: str
    request_digest: str
    semantic_fingerprint: str
    request: DelegationRequest
    context: InteractionContext
    phase: AgentTaskPhase
    revision: int
    created_at: datetime
    updated_at: datetime
    dedupe_guard: bool = True
    dispatch_attempt_count: int = 0
    selected_agent: str | None = None
    selected_candidate_index: int | None = None
    backend_committed: bool = False
    dispatch_token: str | None = None
    handle: AgentRunHandle | None = None
    blocker: str | None = None
    result: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.revision < 1 or self.dispatch_attempt_count < 0:
            raise ValueError("task revision must be positive and dispatch attempts non-negative")


@dataclass(frozen=True, slots=True)
class CreateTaskResult:
    record: AgentTaskRecord
    disposition: TaskCreateDisposition

    @property
    def created(self) -> bool:
        return self.disposition is TaskCreateDisposition.CREATED


class AgentTaskStoreError(RuntimeError):
    pass


class IdempotencyConflict(AgentTaskStoreError):
    pass


class RevisionConflict(AgentTaskStoreError):
    pass


class InvalidTaskTransition(AgentTaskStoreError):
    pass


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
