"""Positive client-receipt evidence on a saved speech-local PCM interval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeGuard

from server.conversation_journal import ConversationItem
from server.core.playback import sample_position_us
from server.observability.telemetry import ReceiptKey, TelemetryOutcome, TelemetryRecord


def _uint(value: Any) -> TypeGuard[int]:
    return type(value) is int and 0 <= value <= 2**53 - 1


def _text(value: Any) -> TypeGuard[str]:
    if not isinstance(value, str) or not value:
        return False
    try:
        return len(value.encode()) <= 512
    except UnicodeEncodeError:
        return False


def validated_receipt_keys(keys: Sequence[ReceiptKey]) -> tuple[ReceiptKey, ...]:
    if len(keys) > 200:
        raise ValueError("playback attachment lookup exceeds recording page limit")
    for key in keys:
        if (
            not isinstance(key, tuple)
            or len(key) != 10
            or not all(_text(key[index]) for index in (0, 1, 2, 3, 7, 8))
            or not _uint(key[4])
            or not _uint(key[9])
            or not 1 <= key[9] <= 192000
            or any(key[index] is not None and not _text(key[index]) for index in (5, 6))
        ):
            raise ValueError("invalid original playback attachment")
    return tuple(dict.fromkeys(keys))


def recording_receipt_key(item: ConversationItem, manifest: dict[str, Any]) -> ReceiptKey | None:
    if manifest["direction"] != "sent" or manifest["stream_id"] != manifest["speech_id"]:
        return None
    ctx = item.context
    return (
        ctx.tenant_id,
        ctx.user_id,
        ctx.voice_session_id,
        manifest["source_thread_id"],
        ctx.generation,
        ctx.turn_id,
        ctx.response_id,
        manifest["epoch"],
        manifest["speech_id"],
        manifest["sample_rate_hz"],
    )


def validate_receipt_result(
    keys: Sequence[ReceiptKey], result: dict[ReceiptKey, int]
) -> dict[ReceiptKey, int]:
    selected = frozenset(validated_receipt_keys(keys))
    if not isinstance(result, dict):
        raise ValueError("invalid targeted playback evidence")  # noqa: TRY004 - one invalid-source contract
    validated_receipt_keys(tuple(result))
    if len(result) > len(selected) or any(
        key not in selected
        or not _uint(position)
        or sample_position_us(position, key[9]) > 2**53 - 1
        for key, position in result.items()
    ):
        raise ValueError("invalid targeted playback evidence")
    return result


def receipt_index(events: Sequence[TelemetryRecord]) -> dict[ReceiptKey, int]:
    """Index only internally coherent exact receipts; never turn gaps into negatives."""
    result: dict[ReceiptKey, int] = {}
    for event in events:
        if event.name != "client.playback_progress" or event.outcome != TelemetryOutcome.OK:
            continue
        attrs = event.attributes
        position, rate = attrs.get("played_position_samples"), attrs.get("sample_rate_hz")
        epoch, speech = attrs.get("output_epoch"), attrs.get("speech_id")
        phase = [attrs.get(name) for name in ("started", "stopped", "completed")]
        micros = attrs.get("played_audio_end_us")
        if (
            not _uint(position)
            or not _uint(rate)
            or not 1 <= rate <= 192000
            or not _uint(micros)
            or sample_position_us(position, rate) != micros
            or attrs.get("precision") != "segment"
            or not _text(epoch)
            or not _text(speech)
            or not all(type(flag) is bool for flag in phase)
            or sum(flag is True for flag in phase) > 1
            or not _uint(event.generation)
            or not all(
                _text(value)
                for value in (
                    event.tenant_id,
                    event.user_id,
                    event.voice_session_id,
                    event.thread_id,
                )
            )
            or event.turn_id is not None
            and not _text(event.turn_id)
            or event.response_id is not None
            and not _text(event.response_id)
        ):
            continue
        key = (
            event.tenant_id,
            event.user_id,
            event.voice_session_id,
            event.thread_id,
            event.generation,
            event.turn_id,
            event.response_id,
            epoch,
            speech,
            rate,
        )
        result[key] = max(result.get(key, 0), position)
    return result


def playback_view(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "reported_end_sample": None,
        "overlap_samples": None,
        "sample_rate_hz": None,
    }


def project_playback(
    item: ConversationItem, manifest: dict[str, Any], receipts: dict[ReceiptKey, int] | None
) -> dict[str, Any]:
    if manifest["direction"] == "input":
        return playback_view("not-applicable")
    if receipts is None:
        return playback_view("unavailable")
    # Only the Bridge's normalized speech-local stream shares the receipt clock.
    key = recording_receipt_key(item, manifest)
    if key is None:
        return playback_view("unknown")
    end = receipts.get(key)
    if end is None:
        return playback_view("unknown")
    start, count = manifest["start_sample"], manifest["sample_count"]
    return {
        "status": "reported",
        "reported_end_sample": end,
        "overlap_samples": max(0, min(end, start + count) - start),
        "sample_rate_hz": manifest["sample_rate_hz"],
    }
