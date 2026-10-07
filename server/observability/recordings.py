"""Verified Session recording references and bytes; never a playback authority."""

from __future__ import annotations

import asyncio
import hashlib
import io
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactPhase,
    ArtifactRecord,
    ArtifactStore,
)
from server.conversation_journal import (
    ArtifactReferenceContent,
    ConversationItem,
    ConversationItemKind,
    ConversationItemStatus,
    ConversationJournal,
    ConversationVisibility,
    JournalScope,
    SessionConversationQuery,
    SessionRecordingQuery,
    StructuredContent,
)
from server.conversation_journal.models import utc_now

MAX_AUDIO_BYTES = 4 * 1024 * 1024 + 44


class RecordingUnavailable(ValueError):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _uint(value: Any, *, positive: bool = False) -> int:
    if type(value) is not int or not int(positive) <= value <= 2**53 - 1:
        raise RecordingUnavailable(503, "invalid_recording_manifest")
    return value


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 512:
        raise RecordingUnavailable(503, "invalid_recording_manifest")
    return value


@dataclass(frozen=True)
class _Evidence:
    item: ConversationItem
    manifest: dict[str, Any]
    reference: ArtifactReferenceContent

    @property
    def scope(self) -> ArtifactAccessScope:
        return ArtifactAccessScope(self.item.context.tenant_id, self.item.context.user_id)

    def project(self, status: str, pinned: bool) -> dict[str, Any]:
        m = self.manifest
        return {
            key: m[key]
            for key in (
                "voice_session_id",
                "direction",
                "epoch",
                "speech_id",
                "stream_id",
                "artifact_id",
                "sample_rate_hz",
                "channels",
                "start_sample",
                "sample_count",
                "discontinuity",
                "captured_at",
                "retention_until",
                "storage_durable",
                "capture_boundary",
                "playback_confirmation",
            )
        } | {
            "item_id": self.item.item_id,
            "journal_sequence": str(self.item.sequence),
            "generation": self.item.context.generation,
            "turn_id": self.item.context.turn_id,
            "response_id": self.item.context.response_id,
            "size_bytes": self.reference.size_bytes,
            "sha256": self.reference.sha256,
            "duration_ms": m["sample_count"] * 1000 / m["sample_rate_hz"],
            "status": status,
            "pinned": pinned,
        }


def _evidence(item: ConversationItem, session_id: str) -> _Evidence:
    def invalid() -> RecordingUnavailable:
        return RecordingUnavailable(503, "invalid_recording_manifest")

    if (
        item.context.voice_session_id != session_id
        or item.producer != "voice-session-recording"
        or item.kind is not ConversationItemKind.CORRECTION
        or item.status is not ConversationItemStatus.COMPLETED
        or item.visibility != frozenset({ConversationVisibility.INTERNAL})
        or len(item.content) != 2
    ):
        raise invalid()
    structures = [part.value for part in item.content if isinstance(part, StructuredContent)]
    references = [part for part in item.content if isinstance(part, ArtifactReferenceContent)]
    if len(structures) != 1 or len(references) != 1:
        raise invalid()
    m, ref = structures[0], references[0]
    if (
        m.get("type") != "voice_recording.segment"
        or type(m.get("schema_version")) is not int
        or m["schema_version"] != 1
        or m.get("voice_session_id") != session_id
        or m.get("direction") not in {"input", "sent"}
        or item.context.thread_id != f"{m.get('source_thread_id')}::recording:{session_id}"
        or not isinstance(m.get("source_thread_id"), str)
        or not m["source_thread_id"]
        or m.get("artifact_id") != ref.artifact_id
        or ref.media_type != "audio/wav"
        or type(ref.size_bytes) is not int
        or not 44 < ref.size_bytes <= MAX_AUDIO_BYTES
        or len(ref.artifact_id) > 128
        or any(c not in "0123456789abcdef" for c in ref.sha256)
        or m.get("playback_confirmation") != "not-inferred"
        or m.get("capture_boundary")
        != ("validated_input" if m["direction"] == "input" else "transport_send_completed")
        or type(m.get("storage_durable")) is not bool
        or type(m.get("discontinuity")) is not bool
    ):
        raise invalid()
    _identity(m.get("epoch"))
    _identity(m.get("stream_id"))
    if m["direction"] == "sent":
        _identity(m.get("speech_id"))
    elif m.get("speech_id") is not None:
        raise invalid()
    rate = _uint(m.get("sample_rate_hz"), positive=True)
    channels = _uint(m.get("channels"), positive=True)
    samples = _uint(m.get("sample_count"), positive=True)
    start = _uint(m.get("start_sample"))
    if (
        rate > 192000
        or channels not in {1, 2}
        or samples > rate * 5
        or ref.size_bytes != samples * 2 * channels + 44
    ):
        raise invalid()
    _uint(start + samples)
    frames = m.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= 256:
        raise invalid()
    end = start
    for frame in frames:
        if not isinstance(frame, list) or len(frame) != 3:
            raise invalid()
        _uint(frame[0])
        position = _uint(frame[1])
        count = _uint(frame[2], positive=True)
        if position != end:
            raise invalid()
        end += count
    if end != start + samples:
        raise invalid()
    try:
        captured = datetime.fromisoformat(m["captured_at"])
        retention = datetime.fromisoformat(m["retention_until"])
        if (
            captured.utcoffset() is None
            or retention.utcoffset() is None
            or retention - captured != timedelta(days=7)
        ):
            raise invalid()
    except (KeyError, TypeError, ValueError) as error:
        raise invalid() from error
    return _Evidence(item, m, ref)


class SessionRecordingReader:
    def __init__(self, journal: ConversationJournal, artifacts: ArtifactStore | None) -> None:
        self._journal = journal
        self._artifacts = artifacts

    def _query(self) -> SessionRecordingQuery:
        if not isinstance(self._journal, SessionRecordingQuery):
            raise RecordingUnavailable(503, "recording_query_not_configured")
        return self._journal

    async def source_scope(self, session_id: str) -> JournalScope | None:
        """Resolve original source using bounded authoritative Journal queries."""
        page = await self._query().read_recording_page(session_id, limit=1)
        if page.items:
            evidence = _evidence(page.items[0], session_id)
            return JournalScope(
                evidence.scope.tenant_id,
                evidence.scope.owner_id,
                evidence.manifest["source_thread_id"],
            )
        if isinstance(self._journal, SessionConversationQuery):
            page = await self._journal.read_session_page(session_id, limit=1)
            if page.items:
                return JournalScope.from_context(page.items[0].context)
        return None

    async def _record(self, evidence: _Evidence) -> tuple[str, ArtifactRecord | None]:
        if self._artifacts is None:
            return "unavailable", None
        record = await self._artifacts.get_record_for(
            evidence.scope, evidence.reference.artifact_id
        )
        if record is None:
            return "unavailable", None
        request, ref = record.request, evidence.reference
        if (
            record.artifact_id != ref.artifact_id
            or request.tenant_id != evidence.scope.tenant_id
            or request.owner_id != evidence.scope.owner_id
            or request.source_kind != "voice_session_recording"
            or request.source_id != evidence.item.context.voice_session_id
            or request.media_type != "audio/wav"
            or request.classification != "restricted"
            or request.expected_size != ref.size_bytes
            or request.expected_sha256 != ref.sha256
            or type(request.immutable) is not bool
            or request.retention_until is None
            or request.retention_until.isoformat() != evidence.manifest["retention_until"]
        ):
            return "unavailable", None
        if not request.immutable and request.retention_until <= utc_now():
            return "expired", record
        if record.phase is ArtifactPhase.DELETED:
            return "deleted", record
        if (
            record.phase is not ArtifactPhase.AVAILABLE
            or record.receipt is None
            or record.receipt.size != ref.size_bytes
            or record.receipt.sha256 != ref.sha256
        ):
            return "unavailable", record
        return "available", record

    async def read_page(
        self, session_id: str, after_sequence: int = 0, limit: int = 200
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise RecordingUnavailable(400, "invalid_recording_page_limit")
        page = await self._query().read_recording_page(
            session_id, after_sequence=after_sequence, limit=limit
        )
        evidence_items = [_evidence(item, session_id) for item in page.items]
        rows: list[dict[str, Any]] = [{} for _ in evidence_items]
        work = iter(enumerate(evidence_items))

        async def metadata_worker() -> None:
            for index, evidence in work:
                status, record = await self._record(evidence)
                rows[index] = evidence.project(
                    status, record.request.immutable if record else False
                )

        # Fixed workers belong to this actual read; gather joins all even on errors.
        results = await asyncio.gather(
            *(metadata_worker() for _ in range(min(4, len(evidence_items)))),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return {
            "voice_session_id": session_id,
            "items": rows,
            "next_cursor": str(page.next_sequence) if page.next_sequence is not None else None,
            "storage_status": "configured" if self._artifacts is not None else "not-configured",
        }

    async def read_audio(self, session_id: str, artifact_id: str) -> bytes:
        item = await self._query().find_recording_artifact(session_id, artifact_id)
        if item is None:
            raise RecordingUnavailable(404, "recording_not_found")
        evidence = _evidence(item, session_id)
        status, _ = await self._record(evidence)
        if status != "available" or self._artifacts is None:
            raise RecordingUnavailable(
                410 if status in {"expired", "deleted"} else 503, f"recording_{status}"
            )
        data = await self._artifacts.read_for(evidence.scope, artifact_id)
        if (
            len(data) != evidence.reference.size_bytes
            or hashlib.sha256(data).hexdigest() != evidence.reference.sha256
        ):
            raise RecordingUnavailable(503, "recording_integrity_failed")
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                if (
                    wav.getcomptype() != "NONE"
                    or wav.getsampwidth() != 2
                    or wav.getnchannels() != evidence.manifest["channels"]
                    or wav.getframerate() != evidence.manifest["sample_rate_hz"]
                    or wav.getnframes() != evidence.manifest["sample_count"]
                ):
                    raise RecordingUnavailable(503, "recording_integrity_failed")
        except (wave.Error, EOFError) as error:
            raise RecordingUnavailable(503, "recording_integrity_failed") from error
        # Recheck authority and expiry after IO; bytes do not outlive access policy.
        current = await self._query().find_recording_artifact(session_id, artifact_id)
        if current is None or current.item_digest != item.item_digest:
            raise RecordingUnavailable(404, "recording_not_found")
        status, _ = await self._record(evidence)
        if status != "available":
            raise RecordingUnavailable(
                410 if status in {"expired", "deleted"} else 503, f"recording_{status}"
            )
        return data
