from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationVisibility,
    InMemoryConversationJournal,
    StructuredContent,
)
from server.core.interaction_context import InteractionContext
from server.voice_session import VoiceSessionIdentity
from server.voice_session.control_recovery import (
    AtomicVoiceSessionRecovery,
    AuthoritativeControlStateRestorer,
    ControlRecoveryState,
    JournalControlStateRestorer,
    PendingConfirmationProjection,
)

ACTION_DIGEST = "a" * 64


class CountingContextRestorer:
    def __init__(self) -> None:
        self.calls = 0

    async def restore(self, *, target_thread_sequence: int):
        self.calls += 1
        return target_thread_sequence, "context-digest"


class CountingControlRestorer:
    def __init__(self) -> None:
        self.calls = 0

    async def restore(self, *, target_thread_sequence: int):
        self.calls += 1
        assert target_thread_sequence == 42
        return ControlRecoveryState(
            completed_tool_call_ids=("call-1",),
            active_worker_ids=("worker-1",),
            pending_confirmation=PendingConfirmationProjection(
                confirmation_id="confirmation-1",
                action_digest=ACTION_DIGEST,
                action_summary="删除文件",
                required_channel="voice",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                generation=3,
            ),
            pending_delivery_ids=("delivery-1",),
        )


class RecordingSink:
    def __init__(self) -> None:
        self.applications = []

    async def apply(self, *, idempotency_key: str, state: ControlRecoveryState):
        self.applications.append((idempotency_key, state))


def identity() -> VoiceSessionIdentity:
    return VoiceSessionIdentity(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
    )


async def test_control_recovery_is_idempotent_and_confirmation_requires_restatement() -> None:
    context = CountingContextRestorer()
    control = CountingControlRestorer()
    sink = RecordingSink()
    recovery = AtomicVoiceSessionRecovery(
        identity=identity(),
        context_restorer=context,
        control_restorer=control,
        sink=sink,
    )

    first = await recovery.restore(target_thread_sequence=42)
    second = await recovery.restore(target_thread_sequence=42)

    assert first == second == (42, "context-digest")
    assert context.calls == 1
    assert control.calls == 1
    assert len(sink.applications) == 1
    recovered = sink.applications[0][1]
    assert recovered.pending_confirmation is not None
    assert recovered.pending_confirmation.requires_restatement is True


class StaticControlSource:
    def __init__(self, values) -> None:
        self.values = values

    async def load(self, *, identity: VoiceSessionIdentity, target_thread_sequence: int):
        del identity, target_thread_sequence
        return self.values


async def test_recovery_rejects_ambiguous_frontmost_confirmations() -> None:
    confirmations = (
        PendingConfirmationProjection(
            confirmation_id="confirmation-1",
            action_digest=ACTION_DIGEST,
            action_summary="删除文件 A",
            required_channel="voice",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            generation=3,
        ),
        PendingConfirmationProjection(
            confirmation_id="confirmation-2",
            action_digest="b" * 64,
            action_summary="删除文件 B",
            required_channel="strong",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            generation=3,
        ),
    )
    restorer = AuthoritativeControlStateRestorer(
        identity=identity(),
        completed_tools=StaticControlSource(("call-1",)),
        active_workers=StaticControlSource(("worker-1",)),
        pending_confirmations=StaticControlSource(confirmations),
        pending_deliveries=StaticControlSource(("delivery-1",)),
    )

    try:
        await restorer.restore(target_thread_sequence=42)
    except ValueError as error:
        assert "one foreground confirmation" in str(error)
    else:
        raise AssertionError("ambiguous confirmations must block recovery")


async def test_journal_control_recovery_restates_only_the_frozen_pending_prefix() -> None:
    journal = InMemoryConversationJournal()
    base = InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-3",
        generation=3,
        call_id="call-1",
    )
    request = await journal.append(
        ConversationItemDraft(
            item_id="confirmation-requested-1",
            context=base,
            kind=ConversationItemKind.CONFIRMATION_REQUESTED,
            status=ConversationItemStatus.COMMITTED,
            producer="test",
            visibility=frozenset(
                {ConversationVisibility.USER, ConversationVisibility.MODEL}
            ),
            content=(
                StructuredContent(
                    {
                        "confirmation_id": "confirmation-1",
                        "action_digest": ACTION_DIGEST,
                        "action_summary": "删除文件 A（不可撤销）",
                        "required_channel": "strong",
                        "expires_at": (
                            datetime.now(UTC) + timedelta(minutes=5)
                        ).isoformat(),
                    }
                ),
            ),
        )
    )
    decided = await journal.append(
        ConversationItemDraft(
            item_id="confirmation-decided-1",
            context=replace(base, confirmation_id="confirmation-1"),
            kind=ConversationItemKind.CONFIRMATION_DECIDED,
            status=ConversationItemStatus.CANCELLED,
            producer="test",
            visibility=frozenset(
                {ConversationVisibility.USER, ConversationVisibility.MODEL}
            ),
            content=(
                StructuredContent(
                    {
                        "confirmation_id": "confirmation-1",
                        "action_digest": ACTION_DIGEST,
                        "approved": False,
                        "channel": "voice",
                    }
                ),
            ),
        )
    )
    restorer = JournalControlStateRestorer(identity=identity(), journal=journal)

    frozen = await restorer.restore(target_thread_sequence=request.item.sequence)
    current = await restorer.restore(target_thread_sequence=decided.item.sequence)

    assert frozen.pending_confirmation is not None
    assert frozen.pending_confirmation == PendingConfirmationProjection(
        confirmation_id="confirmation-1",
        action_digest=ACTION_DIGEST,
        action_summary="删除文件 A（不可撤销）",
        required_channel="strong",
        expires_at=frozen.pending_confirmation.expires_at,
        generation=3,
    )
    assert frozen.pending_confirmation.requires_restatement is True
    assert current.pending_confirmation is None


@pytest.mark.parametrize(("invalid_fields", "message"), [
    ({"confirmation_id": "", "required_channel": "unknown"}, "must be identified"),
    ({"action_digest": "bad", "required_channel": "unknown"}, "digest must be sha256"),
    ({"required_channel": "unknown"}, "channel is unsupported"),
    ({"expires_at": "bad", "required_channel": "unknown"}, "expiry is invalid"),
])
async def test_journal_confirmation_validation_preserves_failure_precedence(
    invalid_fields: dict[str, str], message: str,
) -> None:
    journal = InMemoryConversationJournal()
    context = InteractionContext(
        tenant_id="tenant-1", user_id="user-1", device_id="device-1",
        voice_session_id="voice-1", thread_id="thread-1", turn_id="turn-3", generation=3,
    )
    payload = {
        "confirmation_id": "confirmation-1", "action_digest": ACTION_DIGEST,
        "action_summary": "删除文件", "required_channel": "voice",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        **invalid_fields,
    }
    committed = await journal.append(ConversationItemDraft(
        item_id="invalid-confirmation", context=context,
        kind=ConversationItemKind.CONFIRMATION_REQUESTED,
        status=ConversationItemStatus.COMMITTED, producer="test",
        content=(StructuredContent(payload),),
        visibility=frozenset({ConversationVisibility.USER, ConversationVisibility.MODEL}),
    ))
    restorer = JournalControlStateRestorer(identity=identity(), journal=journal)
    with pytest.raises(ValueError, match=message):
        await restorer.restore(target_thread_sequence=committed.item.sequence)
