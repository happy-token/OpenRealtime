"""Bounded low-latency tool orchestration over the policy gateway."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from server.conversation_journal import (
    ConversationItem,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationJournal,
    ConversationVisibility,
    StructuredContent,
    TextContent,
)
from server.observability.telemetry import (
    SessionTelemetry,
    TelemetryKind,
    TelemetryOutcome,
)
from server.tools.policy_gateway import (
    Allow,
    DefaultToolPolicyGateway,
    DelegateBackground,
    Deny,
    GrantRejected,
    RequireConfirmation,
    ToolExecutor,
    ToolPolicyContext,
    ToolPolicyDecision,
    ToolRequest,
)


@dataclass(frozen=True, slots=True)
class FastToolBudget:
    max_calls: int = 4
    # VARIABLE tools acknowledge before execution and may use a longer grant
    # than FAST tools. Individual descriptors still impose their own bound.
    max_elapsed_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.max_calls < 1 or self.max_elapsed_seconds <= 0:
            raise ValueError("Fast Tool Loop budgets must be positive")


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    success: bool
    output: str | None = None
    error_code: str | None = None
    safe_message: str | None = None
    cancelled: bool = False


FastToolOutcome = ToolExecutionResult | ToolPolicyDecision


class FastToolLoop:
    def __init__(
        self,
        *,
        gateway: DefaultToolPolicyGateway,
        executor: ToolExecutor,
        journal: ConversationJournal,
        budget: FastToolBudget | None = None,
        telemetry: SessionTelemetry | None = None,
    ) -> None:
        self._gateway = gateway
        self._executor = executor
        self._journal = journal
        self._budget = budget or FastToolBudget()
        self._telemetry = telemetry
        # The loop is constructed before the first LLM tool-planning call.
        # Start its execution budget only when a tool action actually arrives,
        # otherwise model latency silently consumes the tool's whole deadline.
        self._started_at: float | None = None
        self._calls_used = 0
        self._outcomes: dict[str, tuple[str, FastToolOutcome]] = {}
        self._committed_result_items: dict[str, ConversationItem] = {}
        self._committed_items: dict[str, list[ConversationItem]] = {}
        self._lock = asyncio.Lock()

    async def handle(
        self,
        request: ToolRequest,
        policy_context: ToolPolicyContext,
    ) -> FastToolOutcome:
        async with self._lock:
            prior = self._outcomes.get(request.call_id)
            if prior is not None:
                if prior[0] == request.request_digest:
                    return prior[1]
                return Deny(
                    "call_id_conflict",
                    "同一工具调用标识不能用于不同操作。",
                )
            if self._started_at is None:
                self._started_at = time.monotonic()
            remaining = self._remaining_seconds()
            if self._calls_used >= self._budget.max_calls:
                return Deny("fast_tool_call_limit", "本轮工具调用次数已达到上限。")
            if remaining <= 0:
                return Deny("fast_tool_deadline", "本轮快速工具处理时间已用尽。")
            self._calls_used += 1

            policy_started_ns = time.monotonic_ns()
            try:
                decision = await self._gateway.evaluate(request, policy_context)
            except Exception as error:
                self._record_phase(
                    "tool.policy.evaluate",
                    request,
                    started_ns=policy_started_ns,
                    outcome=TelemetryOutcome.ERROR,
                    error=error,
                )
                raise
            self._record_phase(
                "tool.policy.evaluate",
                request,
                started_ns=policy_started_ns,
                attributes={"decision": _decision_name(decision)},
            )
            requested = await self._journal.append(_tool_request_item(request, decision))
            committed_items = [requested.item]
            self._committed_items[request.call_id] = committed_items
            if isinstance(decision, RequireConfirmation):
                confirmation = await self._journal.append(
                    _confirmation_item(request, decision)
                )
                committed_items.append(confirmation.item)
                self._outcomes[request.call_id] = (request.request_digest, decision)
                return decision
            if isinstance(decision, (Deny, DelegateBackground)):
                self._outcomes[request.call_id] = (request.request_digest, decision)
                return decision
            if not isinstance(decision, Allow):  # pragma: no cover - union exhaustiveness
                raise TypeError(f"unsupported tool policy decision: {type(decision).__name__}")

            was_cancelled = False
            execution_started_ns = time.monotonic_ns()
            execution_timeout_s = max(
                0.0,
                min(
                    self._remaining_seconds(),
                    decision.grant.timeout_ms / 1000,
                ),
            )
            try:
                async with asyncio.timeout(execution_timeout_s):
                    output = await self._executor.execute(request, decision.grant)
                outcome = ToolExecutionResult(success=True, output=output)
            except asyncio.CancelledError:
                outcome = ToolExecutionResult(
                    success=False,
                    error_code="cancelled",
                    safe_message="工具执行已取消。",
                    cancelled=True,
                )
                was_cancelled = True
            except TimeoutError:
                outcome = ToolExecutionResult(
                    success=False,
                    error_code="timeout",
                    safe_message="工具执行超时，已停止等待。",
                )
            except GrantRejected:
                outcome = ToolExecutionResult(
                    success=False,
                    error_code="authorization_rejected",
                    safe_message="工具授权已失效，未执行操作。",
                )
            except Exception:  # noqa: BLE001 - sanitized tool execution boundary
                outcome = ToolExecutionResult(
                    success=False,
                    error_code="execution_failed",
                    safe_message="工具执行失败。",
                )
            self._record_phase(
                "tool.execute",
                request,
                started_ns=execution_started_ns,
                outcome=_execution_outcome(outcome),
                timeout_ms=execution_timeout_s * 1000,
                error=outcome.error_code,
                attributes={"success": outcome.success},
            )
            appended = await self._journal.append(tool_result_item(request, outcome))
            committed_items.append(appended.item)
            self._committed_result_items[request.call_id] = appended.item
            self._outcomes[request.call_id] = (request.request_digest, outcome)
            if was_cancelled:
                raise asyncio.CancelledError
            return outcome

    def committed_tool_result(self, call_id: str) -> ConversationItem | None:
        """Return the durable tool result produced for ``call_id``, if any."""

        return self._committed_result_items.get(call_id)

    def committed_tool_items(self, call_id: str) -> tuple[ConversationItem, ...]:
        """Return every durable item for ``call_id`` in Journal order."""

        return tuple(self._committed_items.get(call_id, ()))

    def _remaining_seconds(self) -> float:
        if self._started_at is None:
            return self._budget.max_elapsed_seconds
        return self._budget.max_elapsed_seconds - (time.monotonic() - self._started_at)

    def _record_phase(
        self,
        name: str,
        request: ToolRequest,
        *,
        started_ns: int,
        outcome: TelemetryOutcome = TelemetryOutcome.OK,
        timeout_ms: float | None = None,
        error: BaseException | str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> None:
        if self._telemetry is None:
            return
        self._telemetry.record(
            name,
            generation=request.context.generation,
            kind=TelemetryKind.SPAN,
            outcome=outcome,
            duration_ms=(time.monotonic_ns() - started_ns) / 1_000_000,
            timeout_ms=timeout_ms,
            turn_id=request.context.turn_id,
            response_id=request.context.response_id,
            call_id=request.call_id,
            error=error,
            attributes={
                "tool_name": request.tool_name,
                "tool_version": request.tool_version,
                **(attributes or {}),
            },
        )


def _decision_name(decision: ToolPolicyDecision) -> str:
    return {
        Allow: "allow",
        RequireConfirmation: "require_confirmation",
        DelegateBackground: "delegate_background",
        Deny: "deny",
    }[type(decision)]


def _execution_outcome(result: ToolExecutionResult) -> TelemetryOutcome:
    if result.success:
        return TelemetryOutcome.OK
    if result.cancelled:
        return TelemetryOutcome.CANCELLED
    if result.error_code == "timeout":
        return TelemetryOutcome.TIMEOUT
    return TelemetryOutcome.ERROR


def _tool_request_item(
    request: ToolRequest,
    decision: ToolPolicyDecision,
) -> ConversationItemDraft:
    decision_name = _decision_name(decision)
    return ConversationItemDraft(
        item_id=tool_item_id(request, "request"),
        context=request.context,
        kind=ConversationItemKind.TOOL_REQUESTED,
        status=ConversationItemStatus.COMMITTED,
        producer="fast-tool-loop",
        visibility=frozenset(
            {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
        ),
        content=(
            StructuredContent(
                {
                    "tool_name": request.tool_name,
                    "tool_version": request.tool_version,
                    "arguments": request.arguments,
                    "arguments_digest": request.arguments_digest,
                    "origin": request.origin.value,
                    "policy_decision": decision_name,
                }
            ),
        ),
    )


def _confirmation_item(
    request: ToolRequest,
    decision: RequireConfirmation,
) -> ConversationItemDraft:
    pending = decision.pending
    return ConversationItemDraft(
        item_id=tool_item_id(request, "confirmation"),
        context=request.context,
        kind=ConversationItemKind.CONFIRMATION_REQUESTED,
        status=ConversationItemStatus.COMMITTED,
        producer="tool-policy-gateway",
        visibility=frozenset(
            {ConversationVisibility.USER, ConversationVisibility.MODEL}
        ),
        content=(
            StructuredContent(
                {
                    "confirmation_id": pending.confirmation_id,
                    "action_digest": pending.action_digest,
                    "action_summary": pending.action_summary,
                    "required_channel": pending.required_channel.value,
                    "expires_at": pending.expires_at.isoformat(),
                }
            ),
        ),
        parent_item_id=tool_item_id(request, "request"),
    )


def tool_result_item(
    request: ToolRequest,
    result: ToolExecutionResult,
) -> ConversationItemDraft:
    if result.success:
        model_output = result.output or "工具执行成功。"
    else:
        model_output = result.safe_message or "工具执行失败。"
    return ConversationItemDraft(
        item_id=tool_item_id(request, "result"),
        context=request.context,
        kind=ConversationItemKind.TOOL_RESULT,
        status=(
            ConversationItemStatus.CANCELLED
            if result.cancelled
            else (
                ConversationItemStatus.COMPLETED
                if result.success
                else ConversationItemStatus.FAILED
            )
        ),
        producer="fast-tool-loop",
        visibility=frozenset(
            {ConversationVisibility.MODEL, ConversationVisibility.INTERNAL}
        ),
        content=(
            TextContent(model_output),
            StructuredContent(
                {
                    "success": result.success,
                    "output": result.output,
                    "error_code": result.error_code,
                    "safe_message": result.safe_message,
                }
            ),
        ),
        parent_item_id=tool_item_id(request, "request"),
    )


def tool_item_id(request: ToolRequest, boundary: str) -> str:
    identity = (
        f"urn:voiceagent:tool:{request.context.tenant_id}:"
        f"{request.context.user_id}:{request.context.thread_id}:"
        f"{request.call_id}:{boundary}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
