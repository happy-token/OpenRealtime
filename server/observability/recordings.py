"""Verified Session recording references and bytes; never a playback authority."""

from __future__ import annotations

import asyncio
import hashlib
import io
import wave
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactPhase,
    ArtifactRecord,
    ArtifactStore,
    RecordingPreservation,
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
from server.observability.recording_playback import (
    project_playback,
    receipt_index,
    recording_receipt_key,
    validate_receipt_result,
)
from server.observability.telemetry import DiagnosticsQuery, PlaybackReceiptQuery

MAX_AUDIO_BYTES = 4 * 1024 * 1024 + 44
RecordingOptionalOperation = Callable[[], Coroutine[Any, Any, dict[str, Any]]]
OwnedOptionalQuery = Callable[[str, RecordingOptionalOperation], Awaitable[dict[str, Any] | None]]


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
    def __init__(
        self,
        journal: ConversationJournal,
        artifacts: ArtifactStore | None,
        *,
        storage_durable: bool = False,
        owned_optional_query: OwnedOptionalQuery | None = None,
        playback_query: DiagnosticsQuery | None = None,
        playback_health: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._journal = journal
        self._artifacts = artifacts
        self._storage_durable = storage_durable
        self._owned_optional_query = owned_optional_query
        self._playback_query = playback_query
        self._playback_health = playback_health

    async def _playback(self, session_id: str, evidence: list[_Evidence]) -> dict[str, Any]:
        source: dict[str, Any] = {"status": "unavailable", "truncated": False, "collection_healthy": None}
        try:
            if self._playback_query is None:
                return {"source": source, "receipts": None}
            if isinstance(self._playback_query, PlaybackReceiptQuery) and callable(self._playback_query.playback_receipts_for):
                keys = tuple(dict.fromkeys(key for item in evidence
                    if (key := recording_receipt_key(item.item, item.manifest)) is not None))
                receipts = validate_receipt_result(keys, await self._playback_query.playback_receipts_for(keys))
                source["status"] = "available"
            else:
                detail = await self._playback_query.session_detail(session_id)
                if detail is not None and (detail.summary.voice_session_id != session_id or len(detail.events) > 5000):
                    raise ValueError("invalid playback evidence page")
                source.update(status="available" if detail is not None else "missing", truncated=detail.next_cursor is not None if detail else False)
                receipts = receipt_index(detail.events if detail else ())
            if self._playback_health is not None:
                health = self._playback_health()
                source["collection_healthy"] = health.get("status") == "ok" and health.get("pending_events") == 0
            return {"source": source, "receipts": receipts}
        except Exception:  # noqa: BLE001 - optional evidence does not hide verified audio
            return {"source": {"status": "unavailable", "truncated": False, "collection_healthy": None}, "receipts": None}

    def _policy_view(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "marked_at": None,
            "preserved_segments": None,
            "pending_segments": None,
            "unavailable_segments": None,
            "storage_durable": self._storage_durable,
        }

    async def _preservation(self, session_id: str) -> dict[str, Any]:
        view = self._policy_view("unsupported")
        if not isinstance(self._artifacts, RecordingPreservation):
            return view
        # An optional policy failure must not erase otherwise usable recording references.
        try:
            scope = await self.source_scope(session_id)
            if scope is None:
                return view | {"status": "source-missing"}
            state = await self._artifacts.get_session_preservation_for(
                ArtifactAccessScope(scope.tenant_id, scope.user_id), session_id
            )
            if state is None:
                return view | {"status": "unmarked"}
            if state.voice_session_id != session_id or state.marked_at.utcoffset() is None:
                raise ValueError("invalid preservation source")
            return view | {
                "status": "preserved",
                "marked_at": state.marked_at.isoformat(),
                "preserved_segments": _uint(state.preserved_segments),
                "pending_segments": _uint(state.pending_segments),
                "unavailable_segments": _uint(state.unavailable_segments),
            }
        except Exception:  # noqa: BLE001 - optional state remains explicitly unavailable
            return view | {"status": "unavailable"}

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
        policy = self._policy_view("unsupported")
        if isinstance(self._artifacts, RecordingPreservation):
            # Optional IO requires an owner: a caller timeout must not abandon resources.
            policy = self._policy_view("unavailable")
            if self._owned_optional_query is not None:
                policy_result = await self._owned_optional_query(
                    session_id, lambda: self._preservation(session_id)
                )
                if policy_result is not None:
                    policy = policy_result
        playback: dict[str, Any] = {"source": {"status": "not-requested", "truncated": False, "collection_healthy": None}, "receipts": None}
        if any(e.manifest["direction"] == "sent" for e in evidence_items):
            playback["source"]["status"] = "not-configured" if self._playback_query is None else "unavailable"
            if self._playback_query is not None and self._owned_optional_query is not None:
                playback_result = await self._owned_optional_query(session_id, lambda: self._playback(session_id, evidence_items))
                if playback_result is not None:
                    playback = playback_result
        for row, evidence in zip(rows, evidence_items, strict=True):
            row["playback"] = project_playback(evidence.item, evidence.manifest, playback["receipts"])
        return {
            "voice_session_id": session_id,
            "items": rows,
            "next_cursor": str(page.next_sequence) if page.next_sequence is not None else None,
            "storage_status": "configured" if self._artifacts is not None else "not-configured",
            "preservation": policy,
            "playback_source": playback["source"],
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
