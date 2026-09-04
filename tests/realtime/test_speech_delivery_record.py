from __future__ import annotations

import pytest

from server.core.interaction_context import InteractionContext
from server.realtime import (
    AppendSpeechText,
    CancelSpeech,
    CommitSpeech,
    InMemoryRealtimeConversation,
    PlaybackPrecision,
    ReportPlaybackProgress,
    SpeechPlaybackProgress,
    StartSpeech,
)
from server.realtime.speech import (
    InMemorySpeechDeliveryStore,
    SpeechDeliveryStatus,
)


def context() -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-1",
        user_id="user-1",
        device_id="device-1",
        voice_session_id="voice-1",
        thread_id="thread-1",
        turn_id="turn-1",
        generation=1,
    )


async def test_cancelled_speech_records_only_the_prefix_actually_played() -> None:
    deliveries = InMemorySpeechDeliveryStore()
    conversation = InMemoryRealtimeConversation(
        context=context(),
        speech_deliveries=deliveries,
    )
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="start-1",
            idempotency_key="start-1",
            context=context(),
            speech_id="speech-1",
            source_item_id="assistant-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="append-1",
            idempotency_key="append-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="任务已经完成，测试全部通过。",
        )
    )
    await conversation.send(
        ReportPlaybackProgress(
            command_id="progress-1",
            idempotency_key="progress-1",
            context=context(),
            speech_id="speech-1",
            delivered_text_end=6,
            played_audio_end_us=480_000,
            precision=PlaybackPrecision.SEGMENT,
        )
    )
    await conversation.send(
        CancelSpeech(
            command_id="cancel-1",
            idempotency_key="cancel-1",
            context=context(),
            speech_id="speech-1",
            reason="barge_in",
        )
    )

    emitted = [await anext(events) for _ in range(4)]
    assert isinstance(emitted[2], SpeechPlaybackProgress)
    record = await deliveries.get("speech-1")
    assert record is not None
    assert record.status is SpeechDeliveryStatus.INTERRUPTED
    assert record.intended_spoken_content == "任务已经完成，测试全部通过。"
    assert record.delivered_speech_transcript == "任务已经完成"
    assert record.played_audio_end_us == 480_000
    assert record.precision is PlaybackPrecision.SEGMENT
    assert record.reason == "barge_in"

    await conversation.close()


async def test_client_can_report_the_exact_played_prefix_after_cancel_arrives() -> None:
    """The browser learns its final playhead only after clearing its queue."""

    deliveries = InMemorySpeechDeliveryStore()
    conversation = InMemoryRealtimeConversation(
        context=context(),
        speech_deliveries=deliveries,
    )
    await conversation.send(
        StartSpeech(
            command_id="start-late-progress",
            idempotency_key="start-late-progress",
            context=context(),
            speech_id="speech-late-progress",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="append-late-progress",
            idempotency_key="append-late-progress",
            context=context(),
            speech_id="speech-late-progress",
            text_sequence=1,
            delta="北京今天晴朗，明天有小雨。",
        )
    )
    await conversation.send(
        CancelSpeech(
            command_id="cancel-late-progress",
            idempotency_key="cancel-late-progress",
            context=context(),
            speech_id="speech-late-progress",
            reason="barge_in",
        )
    )
    await conversation.send(
        ReportPlaybackProgress(
            command_id="progress-after-cancel",
            idempotency_key="progress-after-cancel",
            context=context(),
            speech_id="speech-late-progress",
            delivered_text_end=len("北京今天晴朗"),
            played_audio_end_us=420_000,
            precision=PlaybackPrecision.EXACT,
        )
    )

    record = await deliveries.get("speech-late-progress")
    assert record is not None
    assert record.status is SpeechDeliveryStatus.INTERRUPTED
    assert record.delivered_speech_transcript == "北京今天晴朗"
    assert record.reason == "barge_in"
    await conversation.close()


async def test_playback_progress_cannot_claim_text_that_was_not_accepted() -> None:
    deliveries = InMemorySpeechDeliveryStore()
    conversation = InMemoryRealtimeConversation(
        context=context(), speech_deliveries=deliveries
    )
    await conversation.send(
        StartSpeech(
            command_id="start-1",
            idempotency_key="start-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="append-1",
            idempotency_key="append-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="你好",
        )
    )

    with pytest.raises(ValueError, match="accepted speech text"):
        await conversation.send(
            ReportPlaybackProgress(
                command_id="progress-1",
                idempotency_key="progress-1",
                context=context(),
                speech_id="speech-1",
                delivered_text_end=3,
                played_audio_end_us=100_000,
            )
        )

    await conversation.close()


async def test_final_playback_progress_settles_committed_speech_as_completed() -> None:
    deliveries = InMemorySpeechDeliveryStore()
    conversation = InMemoryRealtimeConversation(
        context=context(), speech_deliveries=deliveries
    )
    events = conversation.events()
    await conversation.send(
        StartSpeech(
            command_id="start-1",
            idempotency_key="start-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="append-1",
            idempotency_key="append-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="你好",
        )
    )
    await conversation.send(
        CommitSpeech(
            command_id="commit-1",
            idempotency_key="commit-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        ReportPlaybackProgress(
            command_id="progress-final",
            idempotency_key="progress-final",
            context=context(),
            speech_id="speech-1",
            delivered_text_end=2,
            played_audio_end_us=220_000,
            precision=PlaybackPrecision.EXACT,
            completed=True,
        )
    )

    emitted = [await anext(events) for _ in range(4)]
    assert isinstance(emitted[-1], SpeechPlaybackProgress)
    assert emitted[-1].completed is True
    record = await deliveries.get("speech-1")
    assert record is not None
    assert record.status is SpeechDeliveryStatus.COMPLETED
    assert record.text_committed is True
    assert record.delivered_speech_transcript == "你好"

    await conversation.close()


async def test_close_marks_unsettled_playback_as_uncertain() -> None:
    deliveries = InMemorySpeechDeliveryStore()
    conversation = InMemoryRealtimeConversation(
        context=context(), speech_deliveries=deliveries
    )
    await conversation.send(
        StartSpeech(
            command_id="start-1",
            idempotency_key="start-1",
            context=context(),
            speech_id="speech-1",
        )
    )
    await conversation.send(
        AppendSpeechText(
            command_id="append-1",
            idempotency_key="append-1",
            context=context(),
            speech_id="speech-1",
            text_sequence=1,
            delta="正在播放",
        )
    )
    await conversation.send(
        CommitSpeech(
            command_id="commit-1",
            idempotency_key="commit-1",
            context=context(),
            speech_id="speech-1",
        )
    )

    await conversation.close()

    record = await deliveries.get("speech-1")
    assert record is not None
    assert record.status is SpeechDeliveryStatus.UNCERTAIN
    assert record.delivered_speech_transcript == ""
    assert record.reason == "conversation_closed_before_playback_terminal"
