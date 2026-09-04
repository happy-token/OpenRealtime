"""Bound Confirmation resolution and durable Tool result commitment."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, replace

from server.conversation_journal import (
    ConversationItem,
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationJournal,
    ConversationVisibility,
    StructuredContent,
)
from server.core.interaction_context import InteractionContext
from server.tools.fast_loop import ToolExecutionResult, tool_item_id, tool_result_item
from server.tools.policy_gateway import (
    Allow,
    ConfirmationChannel,
    ConfirmationRejected,
    DefaultToolPolicyGateway,
    Deny,
    GrantRejected,
    ToolExecutor,
)


@dataclass(frozen=True, slots=True)
class ToolConfirmationDecision:
    confirmation_id: str
    action_digest: str
    context: InteractionContext
    channel: ConfirmationChannel
    approved: bool

    def __post_init__(self) -> None:
        if not self.confirmation_id or not self.action_digest:
            raise ValueError("confirmation decision identity and digest are required")
        if self.context.confirmation_id not in {None, self.confirmation_id}:
            raise ValueError("confirmation context carries a different confirmation_id")


@dataclass(frozen=True, slots=True)
class ToolConfirmationResolution:
    confirmation_id: str
    approved: bool
    success: bool
    model_output: str
    error_code: str | None
    committed_drafts: tuple[ConversationItemDraft, ...]
    committed_items: tuple[ConversationItem, ...]
    result_item: ConversationItem


class BoundToolConfirmationHandler:
    """Resolve one exact pending action and never execute it twice in-process."""

    def __init__(
        self,
        *,
        gateway: DefaultToolPolicyGateway,
        executor: ToolExecutor,
        journal: ConversationJournal,
    ) -> None:
        self._gateway = gateway
        self._executor = executor
        self._journal = journal
        self._locks: dict[str, asyncio.Lock] = {}
        self._resolved: dict[
            str, tuple[ToolConfirmationDecision, ToolConfirmationResolution]
        ] = {}

    async def resolve(
        self,
        decision: ToolConfirmationDecision,
    ) -> ToolConfirmationResolution:
        lock = self._locks.setdefault(decision.confirmation_id, asyncio.Lock())
        async with lock:
            cached = self._resolved.get(decision.confirmation_id)
            if cached is not None:
                if cached[0] != decision:
                    raise ConfirmationRejected(
                        "confirmation retry does not match the original decision"
                    )
                return cached[1]

            state = await self._gateway.pending_confirmation(
                decision.confirmation_id
            )
            if state is None:
                raise ConfirmationRejected(
                    "confirmation is missing or already consumed"
                )
            if not _same_session_subject(decision.context, state.request.context):
                raise ConfirmationRejected(
                    "confirmation does not belong to this Voice Session"
                )
            authority = await self._gateway.confirm(
                confirmation_id=decision.confirmation_id,
                action_digest=decision.action_digest,
                context=state.request.context,
                channel=decision.channel,
                approved=decision.approved,
            )
            request = state.request
            decided_draft = _confirmation_decided_item(decision, request=request)
            decided = await self._journal.append(decided_draft)
            outcome = await self._execute(request=request, authority=authority)
            result_draft = tool_result_item(request, outcome)
            result = await self._journal.append(result_draft)
            resolution = ToolConfirmationResolution(
                confirmation_id=decision.confirmation_id,
                approved=decision.approved,
                success=outcome.success,
                model_output=(
                    outcome.output
                    if outcome.success and outcome.output
                    else outcome.safe_message or "工具执行失败。"
                ),
                error_code=outcome.error_code,
                committed_drafts=(decided_draft, result_draft),
                committed_items=(decided.item, result.item),
                result_item=result.item,
            )
            self._resolved[decision.confirmation_id] = (decision, resolution)
            return resolution

    async def _execute(self, *, request, authority) -> ToolExecutionResult:
        if isinstance(authority, Deny):
            return ToolExecutionResult(
                success=False,
                error_code=authority.reason_code,
                safe_message=authority.safe_message,
                cancelled=authority.reason_code == "confirmation_declined",
            )
        if not isinstance(authority, Allow):
            raise TypeError(
                f"unsupported confirmation resolution: {type(authority).__name__}"
            )
        try:
            output = await self._executor.execute(request, authority.grant)
            return ToolExecutionResult(success=True, output=output)
        except TimeoutError:
            return ToolExecutionResult(
                success=False,
                error_code="timeout",
                safe_message="工具执行超时，已停止等待。",
            )
        except GrantRejected:
            return ToolExecutionResult(
                success=False,
                error_code="authorization_rejected",
                safe_message="工具授权已失效，未执行操作。",
            )
        except Exception:  # noqa: BLE001 - sanitized tool execution boundary
            return ToolExecutionResult(
                success=False,
                error_code="execution_failed",
                safe_message="工具执行失败。",
            )


def _confirmation_decided_item(
    decision: ToolConfirmationDecision,
    *,
    request,
) -> ConversationItemDraft:
    context = replace(
        request.context,
        confirmation_id=decision.confirmation_id,
    )
    item_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            (
                f"urn:voiceagent:confirmation:{context.tenant_id}:"
                f"{context.user_id}:{context.thread_id}:{decision.confirmation_id}:decided"
            ),
        )
    )
    return ConversationItemDraft(
        item_id=item_id,
        context=context,
        kind=ConversationItemKind.CONFIRMATION_DECIDED,
        status=(
            ConversationItemStatus.COMPLETED
            if decision.approved
            else ConversationItemStatus.CANCELLED
        ),
        producer="bound-tool-confirmation-handler",
        visibility=frozenset(
            {
                ConversationVisibility.USER,
                ConversationVisibility.MODEL,
                ConversationVisibility.INTERNAL,
            }
        ),
        content=(
            StructuredContent(
                {
                    "confirmation_id": decision.confirmation_id,
                    "action_digest": decision.action_digest,
                    "approved": decision.approved,
                    "channel": decision.channel.value,
                }
            ),
        ),
        parent_item_id=tool_item_id(request, "confirmation"),
    )


def _same_session_subject(
    first: InteractionContext,
    second: InteractionContext,
) -> bool:
    return (
        first.tenant_id,
        first.user_id,
        first.device_id,
        first.voice_session_id,
        first.thread_id,
    ) == (
        second.tenant_id,
        second.user_id,
        second.device_id,
        second.voice_session_id,
        second.thread_id,
    )
