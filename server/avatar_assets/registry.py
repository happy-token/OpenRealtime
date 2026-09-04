"""Metadata seam for the PostgreSQL-backed Avatar Asset Registry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import Protocol

from server.agent_session.driver_protocol import utc_now
from server.avatar_assets.models import (
    AcceptanceClaim,
    AcceptancePhase,
    AcceptanceRecord,
    AcceptanceRequest,
    CandidateConflict,
    CandidateCreateRequest,
    LoopWindow,
    MediaFacts,
    MotionBaseCandidate,
    MotionBaseCandidatePhase,
    MotionBasePhase,
    MotionBaseRendition,
    MotionBaseSelection,
    MotionBaseVideo,
    RenditionClaim,
    RenditionPhase,
)
from server.avatar_assets.renditions import RenditionProfile, validate_rendition_media


class MotionBaseRegistry(Protocol):
    async def create_candidate(self, request: CandidateCreateRequest) -> MotionBaseCandidate: ...

    async def find_candidate_by_idempotency(
        self,
        tenant_id: str,
        owner_id: str,
        idempotency_key: str,
    ) -> MotionBaseCandidate | None: ...

    async def list_motion_bases(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str | None,
    ) -> tuple[MotionBaseVideo, ...]: ...

    async def get_candidate(self, request: AcceptanceRequest) -> MotionBaseCandidate | None: ...

    async def claim_acceptance(self, request: AcceptanceRequest) -> AcceptanceClaim: ...

    async def get_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
    ) -> AcceptanceRecord | None: ...

    async def fail_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
        *,
        lease_token: str,
        reason: str,
        retryable: bool,
    ) -> AcceptanceRecord: ...

    async def complete_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
        *,
        source_master_artifact_id: str,
        lease_token: str | None = None,
    ) -> tuple[AcceptanceRecord, MotionBaseVideo]: ...

    async def get_motion_base(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> MotionBaseVideo | None: ...

    async def create_renditions(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]: ...

    async def complete_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
        *,
        artifact_id: str,
        media: MediaFacts,
        lease_token: str | None = None,
    ) -> MotionBaseRendition: ...

    async def claim_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
    ) -> RenditionClaim: ...

    async def fail_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
        *,
        lease_token: str,
        reason: str,
        retryable: bool,
    ) -> MotionBaseRendition: ...

    async def list_renditions(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]: ...

    async def approve_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
        *,
        loop: LoopWindow,
    ) -> tuple[MotionBaseRendition, MotionBaseVideo]: ...

    async def select_motion_base(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str,
        motion_base_id: str,
    ) -> MotionBaseSelection: ...

    async def get_selection(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str,
    ) -> MotionBaseSelection | None: ...


class InMemoryMotionBaseRegistry(MotionBaseRegistry):
    """Test adapter; it never claims durable Avatar Asset Registry semantics."""

    def __init__(
        self,
        *,
        candidate_id_factory: Callable[[], str] | None = None,
        acceptance_id_factory: Callable[[], str] | None = None,
        motion_base_id_factory: Callable[[], str] | None = None,
        rendition_id_factory: Callable[[], str] | None = None,
        acceptance_lease_seconds: int = 300,
        rendition_lease_seconds: int = 900,
    ) -> None:
        self._candidate_id_factory = candidate_id_factory or (lambda: str(uuid.uuid4()))
        self._acceptance_id_factory = acceptance_id_factory or (lambda: str(uuid.uuid4()))
        self._motion_base_id_factory = motion_base_id_factory or (lambda: str(uuid.uuid4()))
        self._rendition_id_factory = rendition_id_factory or (lambda: str(uuid.uuid4()))
        self._acceptance_lease_seconds = acceptance_lease_seconds
        self._rendition_lease_seconds = rendition_lease_seconds
        self._candidates: dict[str, MotionBaseCandidate] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._motion_bases: dict[str, MotionBaseVideo] = {}
        self._renditions: dict[str, MotionBaseRendition] = {}
        self._rendition_profiles: dict[tuple[str, RenditionProfile], str] = {}
        self._acceptances: dict[str, AcceptanceRecord] = {}
        self._acceptance_idempotency: dict[tuple[str, str], str] = {}
        self._candidate_acceptance: dict[str, str] = {}
        self._selections: dict[tuple[str, str, str], MotionBaseSelection] = {}
        self._lock = asyncio.Lock()

    async def create_candidate(self, request: CandidateCreateRequest) -> MotionBaseCandidate:
        key = (request.tenant_id, request.idempotency_key)
        digest = _candidate_digest(request)
        async with self._lock:
            existing = self._idempotency.get(key)
            if existing is not None:
                candidate_id, existing_digest = existing
                if existing_digest != digest:
                    raise CandidateConflict(
                        "candidate idempotency_key was reused with different provenance"
                    )
                return self._candidates[candidate_id]
            candidate_id = self._candidate_id_factory()
            if not candidate_id or candidate_id in self._candidates:
                raise ValueError("candidate_id_factory returned an invalid or duplicate id")
            now = utc_now()
            candidate = MotionBaseCandidate(
                candidate_id=candidate_id,
                request=request,
                phase=MotionBaseCandidatePhase.CANDIDATE,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            self._candidates[candidate_id] = candidate
            self._idempotency[key] = (candidate_id, digest)
            return candidate

    async def find_candidate_by_idempotency(
        self,
        tenant_id: str,
        owner_id: str,
        idempotency_key: str,
    ) -> MotionBaseCandidate | None:
        async with self._lock:
            existing = self._idempotency.get((tenant_id, idempotency_key))
            if existing is None:
                return None
            candidate = self._candidates[existing[0]]
            if candidate.request.owner_id != owner_id:
                return None
            return candidate

    async def get_candidate(self, request: AcceptanceRequest) -> MotionBaseCandidate | None:
        async with self._lock:
            candidate = self._candidates.get(request.candidate_id)
            if candidate is None or (
                candidate.request.tenant_id,
                candidate.request.owner_id,
            ) != (request.tenant_id, request.owner_id):
                return None
            return candidate

    async def claim_acceptance(self, request: AcceptanceRequest) -> AcceptanceClaim:
        if not request.checks.all_passed:
            raise ValueError("every Motion Base Acceptance check must pass")
        async with self._lock:
            candidate = self._candidates.get(request.candidate_id)
            if candidate is None or (
                candidate.request.tenant_id,
                candidate.request.owner_id,
            ) != (request.tenant_id, request.owner_id):
                raise KeyError(request.candidate_id)
            key = (request.tenant_id, request.idempotency_key)
            existing_id = self._acceptance_idempotency.get(key)
            if existing_id is not None:
                existing = self._acceptances[existing_id]
                if existing.request != request:
                    raise CandidateConflict(
                        "acceptance idempotency_key was reused with different review"
                    )
                if existing.phase is AcceptancePhase.ACCEPTED:
                    return AcceptanceClaim(existing, acquired=False)
                now = utc_now()
                can_recover = (
                    existing.phase is AcceptancePhase.FAILED and existing.failure_retryable is True
                ) or (
                    existing.phase is AcceptancePhase.ACCEPTING
                    and existing.lease_expires_at is not None
                    and existing.lease_expires_at <= now
                )
                if not can_recover:
                    return AcceptanceClaim(existing, acquired=False)
                recovered = replace(
                    existing,
                    phase=AcceptancePhase.ACCEPTING,
                    attempt_count=existing.attempt_count + 1,
                    failure_reason=None,
                    failure_retryable=None,
                    lease_token=str(uuid.uuid4()),
                    lease_expires_at=now + timedelta(seconds=self._acceptance_lease_seconds),
                    revision=existing.revision + 1,
                    updated_at=now,
                )
                self._acceptances[existing_id] = recovered
                self._candidates[request.candidate_id] = replace(
                    candidate,
                    phase=MotionBaseCandidatePhase.ACCEPTING,
                    failure_reason=None,
                    revision=candidate.revision + 1,
                    updated_at=now,
                )
                return AcceptanceClaim(recovered, acquired=True)
            claimed_id = self._candidate_acceptance.get(request.candidate_id)
            if claimed_id is not None:
                raise CandidateConflict("candidate already has an acceptance")
            acceptance_id = self._acceptance_id_factory()
            if not acceptance_id or acceptance_id in self._acceptances:
                raise ValueError("acceptance_id_factory returned an invalid or duplicate id")
            now = utc_now()
            acceptance = AcceptanceRecord(
                acceptance_id=acceptance_id,
                request=request,
                phase=AcceptancePhase.ACCEPTING,
                revision=1,
                created_at=now,
                updated_at=now,
                lease_token=str(uuid.uuid4()),
                lease_expires_at=now + timedelta(seconds=self._acceptance_lease_seconds),
            )
            self._acceptances[acceptance_id] = acceptance
            self._acceptance_idempotency[key] = acceptance_id
            self._candidate_acceptance[request.candidate_id] = acceptance_id
            self._candidates[request.candidate_id] = replace(
                candidate,
                phase=MotionBaseCandidatePhase.ACCEPTING,
                revision=candidate.revision + 1,
                updated_at=now,
            )
            return AcceptanceClaim(acceptance, acquired=True)

    async def get_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
    ) -> AcceptanceRecord | None:
        async with self._lock:
            acceptance = self._acceptances.get(acceptance_id)
            if acceptance is None or (
                acceptance.request.tenant_id,
                acceptance.request.owner_id,
            ) != (tenant_id, owner_id):
                return None
            return acceptance

    async def fail_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
        *,
        lease_token: str,
        reason: str,
        retryable: bool,
    ) -> AcceptanceRecord:
        if not reason:
            raise ValueError("acceptance failure reason must be non-empty")
        async with self._lock:
            acceptance = self._acceptances[acceptance_id]
            if (
                acceptance.request.tenant_id,
                acceptance.request.owner_id,
                acceptance.lease_token,
            ) != (tenant_id, owner_id, lease_token):
                raise CandidateConflict("acceptance lease is not owned by this worker")
            if acceptance.phase is not AcceptancePhase.ACCEPTING:
                return acceptance
            failed = replace(
                acceptance,
                phase=AcceptancePhase.FAILED,
                failure_reason=reason,
                failure_retryable=retryable,
                lease_token=None,
                lease_expires_at=None,
                revision=acceptance.revision + 1,
                updated_at=utc_now(),
            )
            self._acceptances[acceptance_id] = failed
            candidate = self._candidates[acceptance.request.candidate_id]
            self._candidates[candidate.candidate_id] = replace(
                candidate,
                phase=MotionBaseCandidatePhase.FAILED,
                failure_reason=reason,
                revision=candidate.revision + 1,
                updated_at=failed.updated_at,
            )
            return failed

    async def complete_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
        *,
        source_master_artifact_id: str,
        lease_token: str | None = None,
    ) -> tuple[AcceptanceRecord, MotionBaseVideo]:
        async with self._lock:
            acceptance = self._acceptances[acceptance_id]
            if (acceptance.request.tenant_id, acceptance.request.owner_id) != (
                tenant_id,
                owner_id,
            ):
                raise KeyError(acceptance_id)
            if acceptance.phase is AcceptancePhase.ACCEPTED:
                assert acceptance.motion_base_id is not None
                return acceptance, self._motion_bases[acceptance.motion_base_id]
            if acceptance.phase is not AcceptancePhase.ACCEPTING:
                raise CandidateConflict("acceptance is not active")
            if not lease_token or acceptance.lease_token != lease_token:
                raise CandidateConflict("acceptance lease is not owned by this worker")
            candidate = self._candidates[acceptance.request.candidate_id]
            motion_base_id = self._motion_base_id_factory()
            if not motion_base_id or motion_base_id in self._motion_bases:
                raise ValueError("motion_base_id_factory returned an invalid or duplicate id")
            now = utc_now()
            motion_base = MotionBaseVideo(
                motion_base_id=motion_base_id,
                tenant_id=acceptance.request.tenant_id,
                owner_id=acceptance.request.owner_id,
                visual_identity_id=candidate.request.visual_identity_id,
                candidate_id=candidate.candidate_id,
                source_master_artifact_id=source_master_artifact_id,
                source_media=candidate.request.media,
                phase=MotionBasePhase.PREPARING,
                created_at=now,
            )
            completed = replace(
                acceptance,
                phase=AcceptancePhase.ACCEPTED,
                revision=acceptance.revision + 1,
                updated_at=now,
                motion_base_id=motion_base_id,
                source_master_artifact_id=source_master_artifact_id,
                lease_token=None,
                lease_expires_at=None,
            )
            self._motion_bases[motion_base_id] = motion_base
            self._acceptances[acceptance_id] = completed
            self._candidates[candidate.candidate_id] = replace(
                candidate,
                phase=MotionBaseCandidatePhase.ACCEPTED,
                revision=candidate.revision + 1,
                updated_at=now,
            )
            return completed, motion_base

    async def get_motion_base(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> MotionBaseVideo | None:
        async with self._lock:
            motion_base = self._motion_bases.get(motion_base_id)
            if motion_base is None or (
                motion_base.tenant_id,
                motion_base.owner_id,
            ) != (tenant_id, owner_id):
                return None
            return motion_base

    async def create_renditions(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]:
        async with self._lock:
            motion_base = self._motion_bases.get(motion_base_id)
            if motion_base is None or (
                motion_base.tenant_id,
                motion_base.owner_id,
            ) != (tenant_id, owner_id):
                raise KeyError(motion_base_id)
            now = utc_now()
            results: list[MotionBaseRendition] = []
            for profile in RenditionProfile:
                key = (motion_base_id, profile)
                rendition_id = self._rendition_profiles.get(key)
                if rendition_id is None:
                    rendition_id = self._rendition_id_factory()
                    if not rendition_id or rendition_id in self._renditions:
                        raise ValueError("rendition_id_factory returned an invalid or duplicate id")
                    rendition = MotionBaseRendition(
                        rendition_id=rendition_id,
                        tenant_id=tenant_id,
                        owner_id=owner_id,
                        motion_base_id=motion_base_id,
                        profile=profile.value,
                        phase=RenditionPhase.QUEUED,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                    self._renditions[rendition_id] = rendition
                    self._rendition_profiles[key] = rendition_id
                results.append(self._renditions[rendition_id])
            return tuple(results)

    async def complete_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
        *,
        artifact_id: str,
        media: MediaFacts,
        lease_token: str | None = None,
    ) -> MotionBaseRendition:
        rendition = self._renditions.get(rendition_id)
        if rendition is None:
            raise KeyError(rendition_id)
        validate_rendition_media(RenditionProfile(rendition.profile), media)
        async with self._lock:
            rendition = self._renditions[rendition_id]
            if (rendition.tenant_id, rendition.owner_id) != (tenant_id, owner_id):
                raise KeyError(rendition_id)
            if rendition.phase in {
                RenditionPhase.READY_FOR_REVIEW,
                RenditionPhase.APPROVED,
            }:
                if rendition.artifact_id != artifact_id or rendition.media != media:
                    raise CandidateConflict("rendition already has different immutable media")
                return rendition
            if rendition.phase not in {
                RenditionPhase.QUEUED,
                RenditionPhase.PROCESSING,
            }:
                raise CandidateConflict("rendition is not active")
            if not lease_token or rendition.lease_token != lease_token:
                raise CandidateConflict("rendition lease is not owned by this worker")
            completed = replace(
                rendition,
                phase=RenditionPhase.READY_FOR_REVIEW,
                revision=rendition.revision + 1,
                updated_at=utc_now(),
                artifact_id=artifact_id,
                media=media,
                lease_token=None,
                lease_expires_at=None,
            )
            self._renditions[rendition_id] = completed
            return completed

    async def claim_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
    ) -> RenditionClaim:
        async with self._lock:
            rendition = self._renditions.get(rendition_id)
            if rendition is None or (rendition.tenant_id, rendition.owner_id) != (
                tenant_id,
                owner_id,
            ):
                raise KeyError(rendition_id)
            if rendition.phase in {
                RenditionPhase.READY_FOR_REVIEW,
                RenditionPhase.APPROVED,
            }:
                return RenditionClaim(rendition, acquired=False)
            now = utc_now()
            claimable = (
                rendition.phase is RenditionPhase.QUEUED
                or (
                    rendition.phase is RenditionPhase.FAILED and rendition.failure_retryable is True
                )
                or (
                    rendition.phase is RenditionPhase.PROCESSING
                    and rendition.lease_expires_at is not None
                    and rendition.lease_expires_at <= now
                )
            )
            if not claimable:
                return RenditionClaim(rendition, acquired=False)
            claimed = replace(
                rendition,
                phase=RenditionPhase.PROCESSING,
                attempt_count=rendition.attempt_count + 1,
                failure_reason=None,
                failure_retryable=None,
                lease_token=str(uuid.uuid4()),
                lease_expires_at=now + timedelta(seconds=self._rendition_lease_seconds),
                revision=rendition.revision + 1,
                updated_at=now,
            )
            self._renditions[rendition_id] = claimed
            return RenditionClaim(claimed, acquired=True)

    async def fail_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
        *,
        lease_token: str,
        reason: str,
        retryable: bool,
    ) -> MotionBaseRendition:
        if not reason:
            raise ValueError("rendition failure reason must be non-empty")
        async with self._lock:
            rendition = self._renditions[rendition_id]
            if (rendition.tenant_id, rendition.owner_id, rendition.lease_token) != (
                tenant_id,
                owner_id,
                lease_token,
            ):
                raise CandidateConflict("rendition lease is not owned by this worker")
            if rendition.phase is not RenditionPhase.PROCESSING:
                return rendition
            failed = replace(
                rendition,
                phase=RenditionPhase.FAILED,
                failure_reason=reason,
                failure_retryable=retryable,
                lease_token=None,
                lease_expires_at=None,
                revision=rendition.revision + 1,
                updated_at=utc_now(),
            )
            self._renditions[rendition_id] = failed
            return failed

    async def list_motion_bases(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str | None,
    ) -> tuple[MotionBaseVideo, ...]:
        async with self._lock:
            return tuple(
                motion_base
                for motion_base in self._motion_bases.values()
                if (
                    motion_base.tenant_id,
                    motion_base.owner_id,
                )
                == (tenant_id, owner_id)
                and (
                    visual_identity_id is None
                    or motion_base.visual_identity_id == visual_identity_id
                )
            )

    async def approve_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
        *,
        loop: LoopWindow,
    ) -> tuple[MotionBaseRendition, MotionBaseVideo]:
        async with self._lock:
            rendition = self._renditions.get(rendition_id)
            if rendition is None or (rendition.tenant_id, rendition.owner_id) != (
                tenant_id,
                owner_id,
            ):
                raise KeyError(rendition_id)
            if rendition.media is None:
                raise CandidateConflict("rendition has no verified media")
            if loop.end_ms > rendition.media.duration_ms:
                raise ValueError("loop window exceeds rendition duration")
            if rendition.phase is RenditionPhase.APPROVED:
                if rendition.loop != loop:
                    raise CandidateConflict("rendition already has a different loop review")
                return rendition, self._motion_bases[rendition.motion_base_id]
            if rendition.phase is not RenditionPhase.READY_FOR_REVIEW:
                raise CandidateConflict("rendition is not ready for review")
            now = utc_now()
            approved = replace(
                rendition,
                phase=RenditionPhase.APPROVED,
                loop=loop,
                revision=rendition.revision + 1,
                updated_at=now,
            )
            motion_base = replace(
                self._motion_bases[rendition.motion_base_id],
                phase=MotionBasePhase.READY,
            )
            self._renditions[rendition_id] = approved
            self._motion_bases[motion_base.motion_base_id] = motion_base
            return approved, motion_base

    async def list_renditions(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]:
        async with self._lock:
            motion_base = self._motion_bases.get(motion_base_id)
            if motion_base is None or (
                motion_base.tenant_id,
                motion_base.owner_id,
            ) != (tenant_id, owner_id):
                return ()
            return tuple(
                rendition
                for rendition in self._renditions.values()
                if rendition.motion_base_id == motion_base_id
            )

    async def select_motion_base(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str,
        motion_base_id: str,
    ) -> MotionBaseSelection:
        async with self._lock:
            motion_base = self._motion_bases.get(motion_base_id)
            if motion_base is None or (
                motion_base.tenant_id,
                motion_base.owner_id,
                motion_base.visual_identity_id,
            ) != (tenant_id, owner_id, visual_identity_id):
                raise KeyError(motion_base_id)
            if motion_base.phase is not MotionBasePhase.READY or not any(
                rendition.motion_base_id == motion_base_id
                and rendition.phase is RenditionPhase.APPROVED
                for rendition in self._renditions.values()
            ):
                raise CandidateConflict("motion base has no approved rendition")
            key = (tenant_id, owner_id, visual_identity_id)
            existing = self._selections.get(key)
            if existing is not None and existing.motion_base_id == motion_base_id:
                return existing
            selection = MotionBaseSelection(
                tenant_id=tenant_id,
                owner_id=owner_id,
                visual_identity_id=visual_identity_id,
                motion_base_id=motion_base_id,
                revision=1 if existing is None else existing.revision + 1,
                selected_at=utc_now(),
            )
            self._selections[key] = selection
            return selection

    async def get_selection(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str,
    ) -> MotionBaseSelection | None:
        async with self._lock:
            return self._selections.get((tenant_id, owner_id, visual_identity_id))


def _candidate_digest(request: CandidateCreateRequest) -> str:
    payload = {
        "tenant_id": request.tenant_id,
        "owner_id": request.owner_id,
        "visual_identity_id": request.visual_identity_id,
        "source_kind": request.source_kind.value,
        "source_id": request.source_id,
        "artifact_id": request.artifact_id,
        "logical_name": request.logical_name,
        "rights_scope": request.rights_scope,
        "media": {
            "size_bytes": request.media.size_bytes,
            "sha256": request.media.sha256,
            "duration_ms": request.media.duration_ms,
            "width": request.media.width,
            "height": request.media.height,
            "frame_rate_numerator": request.media.frame_rate_numerator,
            "frame_rate_denominator": request.media.frame_rate_denominator,
            "video_codec": request.media.video_codec,
            "has_audio": request.media.has_audio,
            "audio_codec": request.media.audio_codec,
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
