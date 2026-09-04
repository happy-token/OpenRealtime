"""Universal v2 Agent Driver Protocol.

Drivers translate backend-native thread/run/session APIs into these values.
They do not own task deduplication, selection policy, budgets, or result
delivery; those belong to AgentTaskSupervisor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol, TypeAlias

from server.core.interaction_context import InteractionContext


class AgentCapability(StrEnum):
    IDEMPOTENT_START = "idempotent_start"
    STATUS_LOOKUP = "status_lookup"
    RESUME = "resume"
    EVENT_STREAM = "event_stream"
    EVENT_REPLAY = "event_replay"
    STEERING = "steering"
    CANCEL = "cancel"
    PERMISSION_BRIDGE = "permission_bridge"
    WORKSPACE_ISOLATION = "workspace_isolation"
    STRUCTURED_RESULT = "structured_result"
    ARTIFACT_MANIFEST = "artifact_manifest"
    USAGE_REPORTING = "usage_reporting"


class AgentRunPhase(StrEnum):
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
            AgentRunPhase.SUCCEEDED,
            AgentRunPhase.FAILED,
            AgentRunPhase.CANCELLED,
            AgentRunPhase.TIMED_OUT,
        }


class WorkspaceMode(StrEnum):
    READ_ONLY = "read_only"
    PRIVATE_WRITABLE = "private_writable"
    EXCLUSIVE_SHARED = "exclusive_shared"


@dataclass(frozen=True, slots=True)
class WorkspaceLease:
    lease_id: str
    worker_id: str
    root: str
    mode: WorkspaceMode
    fencing_token: int
    expires_at: datetime
    allowed_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.lease_id or not self.worker_id or not self.root:
            raise ValueError("workspace lease identity and root must be non-empty")
        if self.fencing_token < 1:
            raise ValueError("workspace fencing_token must be positive")
        if self.expires_at.tzinfo is None:
            raise ValueError("workspace lease expiry must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AgentCapabilityDescriptor:
    driver_kind: str
    driver_version: str
    protocol_version: str
    capabilities: frozenset[AgentCapability]

    def supports(self, required: frozenset[AgentCapability]) -> bool:
        return required.issubset(self.capabilities)


@dataclass(frozen=True, slots=True)
class AgentRunLocator:
    driver_kind: str
    backend_session_id: str
    backend_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunHandle:
    worker_id: str
    dispatch_token: str
    locator: AgentRunLocator
    capabilities: AgentCapabilityDescriptor


@dataclass(frozen=True, slots=True)
class AgentStartRequest:
    worker_id: str
    dispatch_token: str
    instruction: str
    context: InteractionContext
    workspace: WorkspaceLease
    model: str | None = None
    budget: Mapping[str, int | float] = field(default_factory=dict)
    handoff: Mapping[str, Any] | None = None
    output_schema: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.context.worker_id != self.worker_id:
            raise ValueError("AgentStartRequest context must carry the same worker_id")
        if self.workspace.worker_id != self.worker_id:
            raise ValueError("WorkspaceLease must belong to AgentStartRequest worker_id")
        if not self.dispatch_token or not self.instruction:
            raise ValueError("dispatch_token and instruction must be non-empty")


@dataclass(frozen=True, slots=True)
class AgentInput:
    text: str
    client_input_id: str


@dataclass(frozen=True, slots=True)
class AgentRunSnapshot:
    worker_id: str
    phase: AgentRunPhase
    locator: AgentRunLocator
    last_event_sequence: int
    result: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CancelResult:
    requested: bool
    stopped: bool
    phase: AgentRunPhase


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentEventBase:
    worker_id: str
    event_id: str
    sequence: int
    occurred_at: datetime
    locator: AgentRunLocator

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("Agent event sequence must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Agent event timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentRunStarted(AgentEventBase):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentProgressUpdated(AgentEventBase):
    text: str
    progress_version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentMessageDelta(AgentEventBase):
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentPlanUpdated(AgentEventBase):
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentPermissionRequested(AgentEventBase):
    request_id: str
    method: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentInputRequested(AgentEventBase):
    request_id: str
    prompt: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentArtifactPublished(AgentEventBase):
    artifact_id: str
    logical_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentUsageUpdated(AgentEventBase):
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentRunWaiting(AgentEventBase):
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentRunTerminal(AgentEventBase):
    phase: AgentRunPhase
    result: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        AgentEventBase.__post_init__(self)
        if not self.phase.terminal:
            raise ValueError("AgentRunTerminal phase must be terminal")
        if self.phase is AgentRunPhase.SUCCEEDED and self.error is not None:
            raise ValueError("successful terminal event cannot carry an error")
        if self.phase is not AgentRunPhase.SUCCEEDED and self.result is not None:
            raise ValueError("non-success terminal event cannot carry a result")


AgentEvent: TypeAlias = (
    AgentRunStarted
    | AgentProgressUpdated
    | AgentMessageDelta
    | AgentPlanUpdated
    | AgentPermissionRequested
    | AgentInputRequested
    | AgentArtifactPublished
    | AgentUsageUpdated
    | AgentRunWaiting
    | AgentRunTerminal
)


class AgentDriver(Protocol):
    async def capabilities(self) -> AgentCapabilityDescriptor: ...

    async def start(self, request: AgentStartRequest) -> AgentRunHandle: ...

    async def resume(
        self,
        locator: AgentRunLocator,
        *,
        worker_id: str,
        dispatch_token: str,
        after_sequence: int,
    ) -> AgentRunHandle: ...

    async def status(self, handle: AgentRunHandle) -> AgentRunSnapshot: ...

    def events(
        self, handle: AgentRunHandle, *, after: int | None = None
    ) -> AsyncIterator[AgentEvent]: ...

    async def send_input(self, handle: AgentRunHandle, input: AgentInput) -> None: ...

    async def cancel(self, handle: AgentRunHandle, reason: str) -> CancelResult: ...

    async def close(self, handle: AgentRunHandle) -> None: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
