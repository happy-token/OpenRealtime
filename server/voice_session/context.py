"""Budgeted, traceable model-context projection for Cascaded Realtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from server.conversation_journal import (
    ArtifactReferenceContent,
    ConversationItem,
    ConversationItemKind,
    ConversationVisibility,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextPolicy:
    policy_version: str
    context_window_tokens: int
    max_output_tokens: int
    tool_schema_tokens: int
    governing_instruction_tokens: int
    current_input_tokens: int
    safety_margin_tokens: int
    compression_trigger_ratio: float = 0.7

    def __post_init__(self) -> None:
        if not self.policy_version:
            raise ValueError("Context Policy version must be non-empty")
        if min(
            self.context_window_tokens,
            self.max_output_tokens,
            self.tool_schema_tokens,
            self.governing_instruction_tokens,
            self.current_input_tokens,
            self.safety_margin_tokens,
        ) < 0:
            raise ValueError("Context Policy token budgets must not be negative")
        if self.context_window_tokens == 0:
            raise ValueError("Context window must be positive")
        if not 0 < self.compression_trigger_ratio <= 1:
            raise ValueError("compression trigger ratio must be in (0, 1]")


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextBudget:
    history_tokens: int
    compression_trigger_tokens: int


class ContextBudgeter:
    def __init__(self, policy: ContextPolicy) -> None:
        self._policy = policy

    def allocate(self) -> ContextBudget:
        reserved = (
            self._policy.max_output_tokens
            + self._policy.tool_schema_tokens
            + self._policy.governing_instruction_tokens
            + self._policy.current_input_tokens
            + self._policy.safety_margin_tokens
        )
        history_tokens = self._policy.context_window_tokens - reserved
        if history_tokens < 0:
            raise ValueError("required Context Policy sections exceed the model window")
        return ContextBudget(
            history_tokens=history_tokens,
            compression_trigger_tokens=int(
                history_tokens * self._policy.compression_trigger_ratio
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryCheckpoint:
    checkpoint_id: str
    narrative: str
    source_sequence_start: int
    source_sequence_end: int
    source_digest: str
    compressor_model: str
    compressor_version: str
    prompt_version: str
    compression_policy_version: str
    input_tokens: int
    output_tokens: int
    decisions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    commitments: tuple[str, ...] = ()
    active_work_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            (
                self.checkpoint_id,
                self.narrative,
                self.compressor_model,
                self.compressor_version,
                self.prompt_version,
                self.compression_policy_version,
            )
        ):
            raise ValueError("Summary Checkpoint identity fields must be non-empty")
        if self.source_sequence_start < 1:
            raise ValueError("Summary Checkpoint source sequence must be positive")
        if self.source_sequence_end < self.source_sequence_start:
            raise ValueError("Summary Checkpoint source range is invalid")
        if len(self.source_digest) != 64:
            raise ValueError("Summary Checkpoint source digest must be sha256")
        if min(self.input_tokens, self.output_tokens) < 0:
            raise ValueError("Summary Checkpoint token counts must not be negative")


def digest_projected_item(item: ConversationItem) -> str:
    """Fingerprint model projection without rewriting the immutable Journal digest."""
    payload = {
        "projection_schema": 1,
        "item_id": item.item_id,
        "sequence": item.sequence,
        "journal_digest": item.item_digest,
        "kind": item.kind.value,
        "status": item.status.value,
        "visibility": sorted(value.value for value in item.visibility),
        "content": [part.to_payload() for part in item.content],
        "provider_metadata": item.provider_metadata,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def digest_source_items(items: tuple[ConversationItem, ...]) -> str:
    digest = hashlib.sha256()
    for item in sorted(items, key=lambda candidate: candidate.sequence):
        digest.update(f"{item.sequence}:{digest_projected_item(item)}\n".encode())
    return digest.hexdigest()


class SummarySourceChangedError(ValueError):
    """The checkpoint covered a different projection, not the current heard facts."""


class SummaryCheckpointValidator:
    def validate(
        self,
        checkpoint: SummaryCheckpoint,
        *,
        source_items: tuple[ConversationItem, ...],
    ) -> None:
        sequences = tuple(item.sequence for item in source_items)
        expected_sequences = tuple(
            range(checkpoint.source_sequence_start, checkpoint.source_sequence_end + 1)
        )
        if sequences != expected_sequences:
            raise SummarySourceChangedError("Summary Checkpoint source range is incomplete")
        if digest_source_items(source_items) != checkpoint.source_digest:
            raise SummarySourceChangedError("Summary Checkpoint source digest does not match")
        source_ids = {item.item_id for item in source_items}
        unresolved_refs = set(checkpoint.active_work_refs) - source_ids
        if unresolved_refs:
            raise ValueError("Summary Checkpoint contains unresolved work references")


class InMemorySummaryCheckpointStore:
    def __init__(self, validator: SummaryCheckpointValidator) -> None:
        self._validator = validator
        self._by_policy: dict[str, list[SummaryCheckpoint]] = {}

    def publish(
        self,
        checkpoint: SummaryCheckpoint,
        *,
        source_items: tuple[ConversationItem, ...],
    ) -> None:
        self._validator.validate(checkpoint, source_items=source_items)
        self._by_policy.setdefault(checkpoint.compression_policy_version, []).append(
            checkpoint
        )

    def latest_valid(self, policy_version: str) -> SummaryCheckpoint | None:
        checkpoints = self._by_policy.get(policy_version, [])
        return checkpoints[-1] if checkpoints else None


class ConservativeTokenCounter:
    """Conservative fallback used when a provider tokenizer is unavailable."""

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text.encode("utf-8")) / 3))

    def count_item(self, item: ConversationItem) -> int:
        payload = json.dumps(
            [part.to_payload() for part in item.content],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return self.count_text(payload)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextProjection:
    checkpoint: SummaryCheckpoint | None
    recent_items: tuple[ConversationItem, ...]
    projected_through: int
    token_count: int
    projection_digest: str


class ConversationProjector:
    def __init__(
        self,
        *,
        policy: ContextPolicy,
        token_counter: ConservativeTokenCounter,
        checkpoint_validator: SummaryCheckpointValidator,
    ) -> None:
        self._policy = policy
        self._token_counter = token_counter
        self._checkpoint_validator = checkpoint_validator

    def project(
        self,
        *,
        items: tuple[ConversationItem, ...],
        checkpoint: SummaryCheckpoint | None,
    ) -> ContextProjection:
        visible_items = tuple(
            item for item in items if ConversationVisibility.MODEL in item.visibility
        )
        budget = ContextBudgeter(self._policy).allocate().history_tokens
        if checkpoint is not None:
            source_items = tuple(
                item
                for item in items
                if checkpoint.source_sequence_start
                <= item.sequence
                <= checkpoint.source_sequence_end
            )
            self._checkpoint_validator.validate(
                checkpoint,
                source_items=source_items,
            )
            recent_items = tuple(
                item
                for item in visible_items
                if item.sequence > checkpoint.source_sequence_end
            )
            token_count = self._token_counter.count_text(
                render_summary_checkpoint(checkpoint)
            )
        else:
            recent_items = visible_items
            token_count = 0
        token_count += sum(
            self._token_counter.count_item(item) for item in recent_items
        )
        if token_count > budget:
            raise ValueError("model-visible context does not fit the history budget")

        projected_through = visible_items[-1].sequence if visible_items else 0
        digest = hashlib.sha256()
        if checkpoint is not None:
            digest.update(
                f"{checkpoint.checkpoint_id}:{checkpoint.source_digest}\n".encode()
            )
        for item in recent_items:
            digest.update(f"{item.sequence}:{digest_projected_item(item)}\n".encode())
        return ContextProjection(
            checkpoint=checkpoint,
            recent_items=recent_items,
            projected_through=projected_through,
            token_count=token_count,
            projection_digest=digest.hexdigest(),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryNarrative:
    narrative: str
    decisions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    commitments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.narrative:
            raise ValueError("compressed narrative must be non-empty")


class SummaryNarrativeModel(Protocol):
    async def summarize(
        self, items: tuple[ConversationItem, ...]
    ) -> SummaryNarrative: ...


class CompleteTextModel(Protocol):
    async def complete(self, *, system_prompt: str, user_text: str) -> str: ...


class JsonSummaryNarrativeModel:
    """Strict adapter that keeps model output inside the narrative fields."""

    _SYSTEM_PROMPT = (
        "Compress the supplied model-visible conversation records. Return one JSON "
        "object with exactly narrative (string), decisions (string array), "
        "open_questions (string array), and commitments (string array). Preserve "
        "facts and uncertainty. Do not invent tool, task, confirmation, or artifact "
        "state; authoritative references are extracted separately by code."
    )

    def __init__(self, model: CompleteTextModel) -> None:
        self._model = model

    async def summarize(
        self, items: tuple[ConversationItem, ...]
    ) -> SummaryNarrative:
        records = [
            {
                "item_id": item.item_id,
                "sequence": item.sequence,
                "kind": item.kind.value,
                "content": [part.to_payload() for part in item.content],
            }
            for item in items
        ]
        raw = await self._model.complete(
            system_prompt=self._SYSTEM_PROMPT,
            user_text=json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("context compressor returned invalid JSON") from error
        if not isinstance(payload, dict) or set(payload) != {
            "narrative",
            "decisions",
            "open_questions",
            "commitments",
        }:
            raise ValueError("context compressor returned an invalid schema")
        narrative = payload["narrative"]
        if not isinstance(narrative, str) or not narrative.strip():
            raise ValueError("context compressor narrative must be non-empty")
        return SummaryNarrative(
            narrative=narrative.strip(),
            decisions=_string_tuple(payload["decisions"], field="decisions"),
            open_questions=_string_tuple(
                payload["open_questions"], field="open_questions"
            ),
            commitments=_string_tuple(payload["commitments"], field="commitments"),
        )


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"context compressor {field} must be a string array")
    return tuple(item.strip() for item in value)


class HybridContextCompressor:
    """Let the model summarize prose while code owns authoritative references."""

    _ACTIVE_WORK_KINDS = frozenset(
        {
            ConversationItemKind.TOOL_REQUESTED,
            ConversationItemKind.DELEGATION_REQUESTED,
            ConversationItemKind.DELEGATION_PROGRESS,
            ConversationItemKind.CONFIRMATION_REQUESTED,
        }
    )

    def __init__(
        self,
        *,
        model: SummaryNarrativeModel,
        compressor_model: str,
        compressor_version: str,
        prompt_version: str,
        compression_policy_version: str,
        token_counter: ConservativeTokenCounter,
    ) -> None:
        self._model = model
        self._compressor_model = compressor_model
        self._compressor_version = compressor_version
        self._prompt_version = prompt_version
        self._compression_policy_version = compression_policy_version
        self._token_counter = token_counter

    async def compress(
        self, items: tuple[ConversationItem, ...]
    ) -> SummaryCheckpoint:
        if not items:
            raise ValueError("cannot compress an empty source range")
        ordered = tuple(sorted(items, key=lambda item: item.sequence))
        expected_sequences = tuple(
            range(ordered[0].sequence, ordered[-1].sequence + 1)
        )
        if tuple(item.sequence for item in ordered) != expected_sequences:
            raise ValueError("cannot compress a source range with sequence gaps")
        model_visible = tuple(
            item
            for item in ordered
            if ConversationVisibility.MODEL in item.visibility
        )
        if not model_visible:
            raise ValueError("cannot compress a range without model-visible items")
        narrative = await self._model.summarize(model_visible)
        active_work_refs = tuple(
            item.item_id for item in ordered if item.kind in self._ACTIVE_WORK_KINDS
        )
        artifact_refs = tuple(
            content.artifact_id
            for item in ordered
            for content in item.content
            if isinstance(content, ArtifactReferenceContent)
        )
        input_tokens = sum(self._token_counter.count_item(item) for item in ordered)
        output_text = "\n".join(
            (
                narrative.narrative,
                *narrative.decisions,
                *narrative.open_questions,
                *narrative.commitments,
            )
        )
        return SummaryCheckpoint(
            checkpoint_id=str(uuid4()),
            narrative=narrative.narrative,
            decisions=narrative.decisions,
            open_questions=narrative.open_questions,
            commitments=narrative.commitments,
            active_work_refs=active_work_refs,
            artifact_refs=artifact_refs,
            source_sequence_start=ordered[0].sequence,
            source_sequence_end=ordered[-1].sequence,
            source_digest=digest_source_items(ordered),
            compressor_model=self._compressor_model,
            compressor_version=self._compressor_version,
            prompt_version=self._prompt_version,
            compression_policy_version=self._compression_policy_version,
            input_tokens=input_tokens,
            output_tokens=self._token_counter.count_text(output_text),
        )


class ModelContextProjector(Protocol):
    async def project_text(self, items: tuple[ConversationItem, ...]) -> str | None: ...


def render_summary_checkpoint(checkpoint: SummaryCheckpoint) -> str:
    sections = [f"历史摘要：{checkpoint.narrative}"]
    if checkpoint.decisions:
        sections.append("已有决定：" + "；".join(checkpoint.decisions))
    if checkpoint.open_questions:
        sections.append("未解决问题：" + "；".join(checkpoint.open_questions))
    if checkpoint.commitments:
        sections.append("承诺：" + "；".join(checkpoint.commitments))
    if checkpoint.active_work_refs:
        sections.append("活动工作引用：" + "，".join(checkpoint.active_work_refs))
    if checkpoint.artifact_refs:
        sections.append("产物引用：" + "，".join(checkpoint.artifact_refs))
    return "\n".join(sections)


def render_conversation_items(items: tuple[ConversationItem, ...]) -> str | None:
    messages: list[str] = []
    for item in items:
        if ConversationVisibility.MODEL not in item.visibility:
            continue
        if item.kind is ConversationItemKind.USER_INPUT:
            role = "用户"
        elif item.kind is ConversationItemKind.ASSISTANT_OUTPUT:
            role = "助手"
        elif item.kind is ConversationItemKind.TOOL_RESULT:
            role = "工具结果"
        elif item.kind is ConversationItemKind.DELEGATION_RESULT:
            role = "任务结果"
        elif item.kind is ConversationItemKind.CONTEXT_SUMMARY:
            role = "历史摘要"
        else:
            continue
        text = "\n".join(
            part.text.strip()
            for part in item.content
            if hasattr(part, "text") and part.text.strip()
        )
        if text:
            messages.append(f"{role}：{text}")
    return "\n".join(messages) or None


class FullConversationContextProjector:
    """Explicit no-truncation fallback for conformers without compression."""

    async def project_text(self, items: tuple[ConversationItem, ...]) -> str | None:
        return render_conversation_items(items)


class BudgetedConversationContextProjector:
    """Project a validated summary plus recent source without silent omission."""

    def __init__(
        self,
        *,
        policy: ContextPolicy,
        token_counter: ConservativeTokenCounter,
        checkpoint_store: InMemorySummaryCheckpointStore,
        checkpoint_validator: SummaryCheckpointValidator,
        compressor: HybridContextCompressor | None,
    ) -> None:
        self._policy = policy
        self._token_counter = token_counter
        self._checkpoint_store = checkpoint_store
        self._projector = ConversationProjector(
            policy=policy,
            token_counter=token_counter,
            checkpoint_validator=checkpoint_validator,
        )
        self._compressor = compressor
        self._compression_task: asyncio.Task[SummaryCheckpoint] | None = None

    async def project_text(self, items: tuple[ConversationItem, ...]) -> str | None:
        checkpoint = await self._consume_finished_compression()
        checkpoint = checkpoint or self._checkpoint_store.latest_valid(
            self._policy.policy_version
        )
        try:
            try:
                projection = self._projector.project(items=items, checkpoint=checkpoint)
            except SummarySourceChangedError:
                # A once-valid summary is not valid for updated heard history.
                # Reproject all current source; recompress below if it no longer fits.
                projection = self._projector.project(items=items, checkpoint=None)
        except ValueError as error:
            if "does not fit" not in str(error) or self._compressor is None:
                raise
            checkpoint = await self._compress_now(items)
            projection = self._projector.project(items=items, checkpoint=checkpoint)

        trigger = ContextBudgeter(self._policy).allocate().compression_trigger_tokens
        if (
            projection.token_count >= trigger
            and self._compressor is not None
            and self._compression_task is None
        ):
            source = self._compression_source(items)
            if source:
                self._compression_task = asyncio.create_task(
                    self._compress_and_publish(source),
                    name="voice-context-compression",
                )
                self._compression_task.add_done_callback(_consume_task_exception)
        return self._render_projection(projection)

    async def _consume_finished_compression(self) -> SummaryCheckpoint | None:
        task = self._compression_task
        if task is None or not task.done():
            return None
        self._compression_task = None
        try:
            return await task
        except Exception:  # noqa: BLE001 - invalid background summaries stay invisible
            return None

    async def _compress_now(
        self, items: tuple[ConversationItem, ...]
    ) -> SummaryCheckpoint:
        if self._compression_task is not None:
            task = self._compression_task
            self._compression_task = None
            checkpoint = await task
            try:
                self._projector.project(items=items, checkpoint=checkpoint)
            except ValueError as error:
                if not isinstance(error, SummarySourceChangedError) and "does not fit" not in str(error):
                    raise
            else:
                return checkpoint
        source = self._compression_source(items)
        if not source:
            raise ValueError("model-visible context cannot be compressed safely")
        return await self._compress_and_publish(source)

    def _compression_source(
        self, items: tuple[ConversationItem, ...]
    ) -> tuple[ConversationItem, ...]:
        if len(items) < 2:
            return ()
        history_budget = ContextBudgeter(self._policy).allocate().history_tokens
        recent_budget = max(1, history_budget // 2)
        recent_tokens = 0
        first_recent_index = len(items)
        for index in range(len(items) - 1, -1, -1):
            item = items[index]
            item_tokens = (
                self._token_counter.count_item(item)
                if ConversationVisibility.MODEL in item.visibility
                else 0
            )
            if first_recent_index < len(items) and recent_tokens + item_tokens > recent_budget:
                break
            recent_tokens += item_tokens
            first_recent_index = index
        source_end = max(0, first_recent_index - 1)
        if source_end == 0 and len(items) > 1:
            source_end = len(items) - 2
        source = items[: source_end + 1]
        if not any(ConversationVisibility.MODEL in item.visibility for item in source):
            return ()
        return source

    async def _compress_and_publish(
        self, source: tuple[ConversationItem, ...]
    ) -> SummaryCheckpoint:
        assert self._compressor is not None
        checkpoint = await self._compressor.compress(source)
        self._checkpoint_store.publish(checkpoint, source_items=source)
        return checkpoint

    @staticmethod
    def _render_projection(projection: ContextProjection) -> str | None:
        sections: list[str] = []
        if projection.checkpoint is not None:
            sections.append(render_summary_checkpoint(projection.checkpoint))
        recent = render_conversation_items(projection.recent_items)
        if recent:
            sections.append(recent)
        return "\n".join(sections) or None


def _consume_task_exception(task: asyncio.Task[SummaryCheckpoint]) -> None:
    if task.cancelled():
        return
    task.exception()
