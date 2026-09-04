"""Canonical Tool Control interface shared by Realtime and legacy adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from server.conversation_journal import ConversationItem
from server.tools.fast_loop import FastToolLoop, ToolExecutionResult
from server.tools.policy_gateway import (
    DelegateBackground,
    Deny,
    RequireConfirmation,
    ToolPolicyContext,
    ToolRequest,
)


class ToolControlCancelled(Exception):
    """Raised when a response is cancelled while its tool is executing."""


class ToolCancellation:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason or "cancelled"

    def cancel(self, reason: str = "cancelled") -> bool:
        if self._event.is_set():
            return False
        self._reason = reason or "cancelled"
        self._event.set()
        return True

    async def wait(self) -> None:
        await self._event.wait()


@dataclass(frozen=True, slots=True)
class ToolControlResult:
    call_id: str
    success: bool
    model_output: str
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.call_id or not self.model_output:
            raise ValueError("tool control result identity and output must be non-empty")
        if self.success and self.error_code is not None:
            raise ValueError("successful tool control result cannot carry an error code")


class ToolControlHandler(Protocol):
    async def handle(
        self,
        request: ToolRequest,
        cancellation: ToolCancellation,
    ) -> ToolControlResult: ...


@runtime_checkable
class CommittedToolResultProvider(Protocol):
    def committed_tool_result(self, call_id: str) -> ConversationItem | None: ...


@runtime_checkable
class CommittedToolItemsProvider(Protocol):
    """Expose the complete durable projection for one tool call in sequence."""

    def committed_tool_items(self, call_id: str) -> tuple[ConversationItem, ...]: ...


class DefaultToolControlHandler:
    """Run one canonical request through policy, budget, executor and Journal."""

    def __init__(
        self,
        *,
        loop: FastToolLoop,
        policy_context: ToolPolicyContext,
    ) -> None:
        self._loop = loop
        self._policy_context = policy_context

    async def handle(
        self,
        request: ToolRequest,
        cancellation: ToolCancellation,
    ) -> ToolControlResult:
        if cancellation.is_cancelled:
            raise ToolControlCancelled(cancellation.reason)
        execution = asyncio.create_task(
            self._loop.handle(request, self._policy_context),
            name=f"tool-control-{request.call_id}",
        )
        cancelled = asyncio.create_task(
            cancellation.wait(),
            name=f"tool-control-cancellation-{request.call_id}",
        )
        try:
            done, _ = await asyncio.wait(
                {execution, cancelled},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done or cancellation.is_cancelled:
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                raise ToolControlCancelled(cancellation.reason)
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)
            return _control_result(request, execution.result())
        finally:
            if not execution.done():
                execution.cancel()
            if not cancelled.done():
                cancelled.cancel()
            await asyncio.gather(execution, cancelled, return_exceptions=True)

    def committed_tool_result(self, call_id: str) -> ConversationItem | None:
        return self._loop.committed_tool_result(call_id)

    def committed_tool_items(self, call_id: str) -> tuple[ConversationItem, ...]:
        return self._loop.committed_tool_items(call_id)


def _control_result(
    request: ToolRequest,
    outcome: ToolExecutionResult | RequireConfirmation | DelegateBackground | Deny,
) -> ToolControlResult:
    if isinstance(outcome, ToolExecutionResult):
        if outcome.success:
            return ToolControlResult(
                call_id=request.call_id,
                success=True,
                model_output=outcome.output or "工具执行成功。",
            )
        return ToolControlResult(
            call_id=request.call_id,
            success=False,
            model_output=outcome.safe_message or "工具执行失败。",
            error_code=outcome.error_code or "execution_failed",
        )
    if isinstance(outcome, RequireConfirmation):
        return ToolControlResult(
            call_id=request.call_id,
            success=False,
            model_output=f"需要确认：{outcome.pending.action_summary}",
            error_code="confirmation_required",
        )
    if isinstance(outcome, DelegateBackground):
        return ToolControlResult(
            call_id=request.call_id,
            success=False,
            model_output=outcome.safe_message,
            error_code=outcome.reason_code,
        )
    return ToolControlResult(
        call_id=request.call_id,
        success=False,
        model_output=outcome.safe_message,
        error_code=outcome.reason_code,
    )
