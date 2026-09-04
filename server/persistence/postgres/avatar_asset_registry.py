"""PostgreSQL authority for Motion Base Candidate acceptance metadata."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from server.agent_session.driver_protocol import utc_now
from server.avatar_assets.models import (
    AcceptanceChecks,
    AcceptanceClaim,
    AcceptancePhase,
    AcceptanceRecord,
    AcceptanceRequest,
    CandidateConflict,
    CandidateCreateRequest,
    CandidateSourceKind,
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
from server.persistence.postgres._connection import connection_scope
from server.persistence.postgres.schema import validate_schema_name


class PostgresMotionBaseRegistry:
    def __init__(
        self,
        executor: Any,
        *,
        schema: str = "voiceagent",
        candidate_id_factory: Callable[[], str] | None = None,
        acceptance_id_factory: Callable[[], str] | None = None,
        motion_base_id_factory: Callable[[], str] | None = None,
        rendition_id_factory: Callable[[], str] | None = None,
        acceptance_lease_seconds: int = 300,
        rendition_lease_seconds: int = 900,
    ) -> None:
        self._executor = executor
        validated = validate_schema_name(schema)
        self._candidates = f'"{validated}".motion_base_candidates'
        self._acceptances = f'"{validated}".motion_base_acceptances'
        self._motion_bases = f'"{validated}".motion_base_videos'
        self._renditions = f'"{validated}".motion_base_renditions'
        self._selections = f'"{validated}".motion_base_selections'
        self._artifacts = f'"{validated}".artifacts'
        self._candidate_id_factory = candidate_id_factory or (lambda: str(uuid.uuid4()))
        self._acceptance_id_factory = acceptance_id_factory or (lambda: str(uuid.uuid4()))
        self._motion_base_id_factory = motion_base_id_factory or (lambda: str(uuid.uuid4()))
        self._rendition_id_factory = rendition_id_factory or (lambda: str(uuid.uuid4()))
        self._acceptance_lease_seconds = acceptance_lease_seconds
        self._rendition_lease_seconds = rendition_lease_seconds

    async def create_candidate(self, request: CandidateCreateRequest) -> MotionBaseCandidate:
        candidate_id = self._candidate_id_factory()
        if not candidate_id:
            raise ValueError("candidate_id_factory returned an empty id")
        digest = _candidate_digest(request)
        now = utc_now()
        media = request.media
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                INSERT INTO {self._candidates} (
                    candidate_id, tenant_id, owner_id, visual_identity_id,
                    source_kind, source_id, artifact_id, logical_name, rights_scope,
                    idempotency_key, request_digest, size_bytes, sha256, duration_ms,
                    width, height, frame_rate_numerator, frame_rate_denominator,
                    video_codec, has_audio, audio_codec, phase, revision,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    $12, $13, $14, $15, $16, $17, $18, $19, $20, $21,
                    'candidate', 1, $22, $22
                )
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                RETURNING *
                """,
                candidate_id,
                request.tenant_id,
                request.owner_id,
                request.visual_identity_id,
                request.source_kind.value,
                request.source_id,
                request.artifact_id,
                request.logical_name,
                request.rights_scope,
                request.idempotency_key,
                digest,
                media.size_bytes,
                media.sha256,
                media.duration_ms,
                media.width,
                media.height,
                media.frame_rate_numerator,
                media.frame_rate_denominator,
                media.video_codec,
                media.has_audio,
                media.audio_codec,
                now,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT * FROM {self._candidates} WHERE tenant_id = $1 AND idempotency_key = $2",
                    request.tenant_id,
                    request.idempotency_key,
                )
                if row is None:
                    raise RuntimeError("candidate idempotency record disappeared")
                if row["request_digest"] != digest:
                    raise CandidateConflict(
                        "candidate idempotency_key was reused with different provenance"
                    )
        return _candidate(row)

    async def find_candidate_by_idempotency(
        self,
        tenant_id: str,
        owner_id: str,
        idempotency_key: str,
    ) -> MotionBaseCandidate | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._candidates}
                WHERE tenant_id = $1 AND owner_id = $2 AND idempotency_key = $3
                """,
                tenant_id,
                owner_id,
                idempotency_key,
            )
        return _candidate(row) if row is not None else None

    async def get_candidate(self, request: AcceptanceRequest) -> MotionBaseCandidate | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._candidates}
                WHERE candidate_id = $1 AND tenant_id = $2 AND owner_id = $3
                """,
                request.candidate_id,
                request.tenant_id,
                request.owner_id,
            )
        return _candidate(row) if row is not None else None

    async def claim_acceptance(self, request: AcceptanceRequest) -> AcceptanceClaim:
        if not request.checks.all_passed:
            raise ValueError("every Motion Base Acceptance check must pass")
        acceptance_id = self._acceptance_id_factory()
        if not acceptance_id:
            raise ValueError("acceptance_id_factory returned an empty id")
        digest = _acceptance_digest(request)
        now = utc_now()
        lease_token = str(uuid.uuid4())
        lease_expires_at = now + timedelta(seconds=self._acceptance_lease_seconds)
        checks = request.checks
        async with connection_scope(self._executor) as connection, connection.transaction():
            candidate = await connection.fetchrow(
                f"""
                    SELECT * FROM {self._candidates}
                    WHERE candidate_id = $1 AND tenant_id = $2 AND owner_id = $3
                    FOR UPDATE
                    """,
                request.candidate_id,
                request.tenant_id,
                request.owner_id,
            )
            if candidate is None:
                raise KeyError(request.candidate_id)
            row = await connection.fetchrow(
                f"""
                    INSERT INTO {self._acceptances} (
                        acceptance_id, tenant_id, owner_id, candidate_id, reviewer_id,
                        idempotency_key, request_digest, identity_match, single_person,
                        closed_mouth, fixed_camera, no_gestures, rights_confirmed,
                        phase, revision, created_at, updated_at
                        , attempt_count, lease_token, lease_expires_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8, $9, $10, $11, $12, $13,
                        'accepting', 1, $14, $14, 1, $15, $16
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING *
                    """,
                acceptance_id,
                request.tenant_id,
                request.owner_id,
                request.candidate_id,
                request.reviewer_id,
                request.idempotency_key,
                digest,
                checks.identity_match,
                checks.single_person,
                checks.closed_mouth,
                checks.fixed_camera,
                checks.no_gestures,
                checks.rights_confirmed,
                now,
                lease_token,
                lease_expires_at,
            )
            acquired = row is not None
            if row is None:
                row = await connection.fetchrow(
                    f"""
                        SELECT * FROM {self._acceptances}
                        WHERE tenant_id = $1 AND idempotency_key = $2
                           OR candidate_id = $3
                        ORDER BY (tenant_id = $1 AND idempotency_key = $2) DESC
                        LIMIT 1
                        """,
                    request.tenant_id,
                    request.idempotency_key,
                    request.candidate_id,
                )
                if row is None:
                    raise RuntimeError("acceptance conflict record disappeared")
                if row["request_digest"] != digest:
                    raise CandidateConflict("candidate already has a different acceptance")
                if row["phase"] == AcceptancePhase.ACCEPTED.value:
                    return AcceptanceClaim(_acceptance(row), acquired=False)
                can_recover = (
                    row["phase"] == AcceptancePhase.FAILED.value
                    and row["failure_retryable"] is True
                ) or (
                    row["phase"] == AcceptancePhase.ACCEPTING.value
                    and row["lease_expires_at"] is not None
                    and row["lease_expires_at"] <= now
                )
                if can_recover:
                    recovered = await connection.fetchrow(
                        f"""
                        UPDATE {self._acceptances}
                        SET phase = 'accepting', attempt_count = attempt_count + 1,
                            failure_reason = NULL, failure_retryable = NULL,
                            lease_token = $2, lease_expires_at = $3,
                            revision = revision + 1, updated_at = $4
                        WHERE acceptance_id = $1 AND revision = $5
                        RETURNING *
                        """,
                        row["acceptance_id"],
                        lease_token,
                        lease_expires_at,
                        now,
                        row["revision"],
                    )
                    if recovered is not None:
                        row = recovered
                        acquired = True
            if candidate["phase"] == MotionBaseCandidatePhase.CANDIDATE.value:
                await connection.execute(
                    f"""
                        UPDATE {self._candidates}
                        SET phase = 'accepting', revision = revision + 1, updated_at = $2
                        WHERE candidate_id = $1 AND phase = 'candidate'
                        """,
                    request.candidate_id,
                    now,
                )
            elif acquired:
                await connection.execute(
                    f"""
                    UPDATE {self._candidates}
                    SET phase = 'accepting', failure_reason = NULL,
                        revision = revision + 1, updated_at = $2
                    WHERE candidate_id = $1
                    """,
                    request.candidate_id,
                    now,
                )
        return AcceptanceClaim(_acceptance(row), acquired=acquired)

    async def get_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
    ) -> AcceptanceRecord | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._acceptances}
                WHERE acceptance_id = $1 AND tenant_id = $2 AND owner_id = $3
                """,
                acceptance_id,
                tenant_id,
                owner_id,
            )
        return _acceptance(row) if row is not None else None

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
        now = utc_now()
        async with connection_scope(self._executor) as connection, connection.transaction():
            row = await connection.fetchrow(
                f"""
                UPDATE {self._acceptances}
                SET phase = 'failed', failure_reason = $5, failure_retryable = $6,
                    lease_token = NULL, lease_expires_at = NULL,
                    revision = revision + 1, updated_at = $7
                WHERE acceptance_id = $1 AND tenant_id = $2 AND owner_id = $3
                  AND phase = 'accepting' AND lease_token = $4
                RETURNING *
                """,
                acceptance_id,
                tenant_id,
                owner_id,
                lease_token,
                reason,
                retryable,
                now,
            )
            if row is None:
                current = await connection.fetchrow(
                    f"""
                    SELECT * FROM {self._acceptances}
                    WHERE acceptance_id = $1 AND tenant_id = $2 AND owner_id = $3
                    """,
                    acceptance_id,
                    tenant_id,
                    owner_id,
                )
                if current is None or current["lease_token"] != lease_token:
                    raise CandidateConflict("acceptance lease is not owned by this worker")
                return _acceptance(current)
            await connection.execute(
                f"""
                UPDATE {self._candidates}
                SET phase = 'failed', failure_reason = $2,
                    revision = revision + 1, updated_at = $3
                WHERE candidate_id = $1
                """,
                row["candidate_id"],
                reason,
                now,
            )
        return _acceptance(row)

    async def complete_acceptance(
        self,
        tenant_id: str,
        owner_id: str,
        acceptance_id: str,
        *,
        source_master_artifact_id: str,
        lease_token: str | None = None,
    ) -> tuple[AcceptanceRecord, MotionBaseVideo]:
        async with connection_scope(self._executor) as connection, connection.transaction():
            acceptance_row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._acceptances}
                WHERE acceptance_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                acceptance_id,
                tenant_id,
                owner_id,
            )
            if acceptance_row is None:
                raise KeyError(acceptance_id)
            if acceptance_row["phase"] == AcceptancePhase.ACCEPTED.value:
                if acceptance_row["source_master_artifact_id"] != source_master_artifact_id:
                    raise CandidateConflict("acceptance already has a different source master")
                motion_base_row = await connection.fetchrow(
                    f"SELECT * FROM {self._motion_bases} WHERE motion_base_id = $1",
                    acceptance_row["motion_base_id"],
                )
                if motion_base_row is None:
                    raise RuntimeError("accepted motion base record disappeared")
                return _acceptance(acceptance_row), _motion_base(motion_base_row)
            if acceptance_row["phase"] != AcceptancePhase.ACCEPTING.value:
                raise CandidateConflict("acceptance is not active")
            if not lease_token or acceptance_row["lease_token"] != lease_token:
                raise CandidateConflict("acceptance lease is not owned by this worker")
            candidate_row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._candidates}
                WHERE candidate_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                acceptance_row["candidate_id"],
                tenant_id,
                owner_id,
            )
            if candidate_row is None:
                raise RuntimeError("accepted candidate record disappeared")
            source_master = await connection.fetchrow(
                f"""
                SELECT * FROM {self._artifacts}
                WHERE artifact_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                source_master_artifact_id,
                tenant_id,
                owner_id,
            )
            if source_master is None:
                raise CandidateConflict("source master is outside the acceptance scope")
            if (
                source_master["phase"] != "available"
                or source_master["source_kind"] != "motion_base_source_master"
                or source_master["source_id"] != candidate_row["candidate_id"]
                or source_master["object_size"] != candidate_row["size_bytes"]
                or source_master["object_sha256"] != candidate_row["sha256"]
            ):
                raise CandidateConflict("source master does not match the accepted candidate")
            motion_base_id = self._motion_base_id_factory()
            if not motion_base_id:
                raise ValueError("motion_base_id_factory returned an empty id")
            now = utc_now()
            motion_base_row = await connection.fetchrow(
                f"""
                    INSERT INTO {self._motion_bases} (
                        motion_base_id, tenant_id, owner_id, visual_identity_id,
                        candidate_id, acceptance_id, source_master_artifact_id,
                        size_bytes, sha256, duration_ms, width, height,
                        frame_rate_numerator, frame_rate_denominator,
                        video_codec, has_audio, audio_codec, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18
                    ) RETURNING *
                    """,
                motion_base_id,
                acceptance_row["tenant_id"],
                acceptance_row["owner_id"],
                candidate_row["visual_identity_id"],
                candidate_row["candidate_id"],
                acceptance_id,
                source_master_artifact_id,
                candidate_row["size_bytes"],
                candidate_row["sha256"],
                candidate_row["duration_ms"],
                candidate_row["width"],
                candidate_row["height"],
                candidate_row["frame_rate_numerator"],
                candidate_row["frame_rate_denominator"],
                candidate_row["video_codec"],
                candidate_row["has_audio"],
                candidate_row["audio_codec"],
                now,
            )
            acceptance_row = await connection.fetchrow(
                f"""
                    UPDATE {self._acceptances}
                    SET phase = 'accepted', source_master_artifact_id = $2,
                        motion_base_id = $3, lease_token = NULL, lease_expires_at = NULL,
                        revision = revision + 1, updated_at = $4
                    WHERE acceptance_id = $1
                    RETURNING *
                    """,
                acceptance_id,
                source_master_artifact_id,
                motion_base_id,
                now,
            )
            await connection.execute(
                f"""
                    UPDATE {self._candidates}
                    SET phase = 'accepted', revision = revision + 1, updated_at = $2
                    WHERE candidate_id = $1
                    """,
                candidate_row["candidate_id"],
                now,
            )
            await connection.execute(
                f"""
                UPDATE {self._artifacts}
                SET immutable = true, revision = revision + 1, updated_at = $2
                WHERE artifact_id = $1 AND immutable = false
                """,
                source_master_artifact_id,
                now,
            )
        return _acceptance(acceptance_row), _motion_base(motion_base_row)

    async def list_motion_bases(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str | None,
    ) -> tuple[MotionBaseVideo, ...]:
        async with connection_scope(self._executor) as connection:
            if visual_identity_id is None:
                rows = await connection.fetch(
                    f"""
                    SELECT * FROM {self._motion_bases}
                    WHERE tenant_id = $1 AND owner_id = $2
                    ORDER BY created_at, motion_base_id
                    """,
                    tenant_id,
                    owner_id,
                )
            else:
                rows = await connection.fetch(
                    f"""
                    SELECT * FROM {self._motion_bases}
                    WHERE tenant_id = $1 AND owner_id = $2 AND visual_identity_id = $3
                    ORDER BY created_at, motion_base_id
                    """,
                    tenant_id,
                    owner_id,
                    visual_identity_id,
                )
        return tuple(_motion_base(row) for row in rows)

    async def get_motion_base(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> MotionBaseVideo | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._motion_bases}
                WHERE motion_base_id = $1 AND tenant_id = $2 AND owner_id = $3
                """,
                motion_base_id,
                tenant_id,
                owner_id,
            )
        return _motion_base(row) if row is not None else None

    async def create_renditions(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]:
        now = utc_now()
        async with connection_scope(self._executor) as connection, connection.transaction():
            motion_base = await connection.fetchrow(
                f"""
                SELECT motion_base_id FROM {self._motion_bases}
                WHERE motion_base_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                motion_base_id,
                tenant_id,
                owner_id,
            )
            if motion_base is None:
                raise KeyError(motion_base_id)
            for profile in RenditionProfile:
                rendition_id = self._rendition_id_factory()
                if not rendition_id:
                    raise ValueError("rendition_id_factory returned an empty id")
                await connection.execute(
                    f"""
                    INSERT INTO {self._renditions} (
                        rendition_id, tenant_id, owner_id, motion_base_id,
                        profile, phase, fit_mode, revision, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, 'queued', 'blur_pad', 1, $6, $6)
                    ON CONFLICT (motion_base_id, profile) DO NOTHING
                    """,
                    rendition_id,
                    tenant_id,
                    owner_id,
                    motion_base_id,
                    profile.value,
                    now,
                )
            rows = await connection.fetch(
                f"""
                SELECT * FROM {self._renditions}
                WHERE motion_base_id = $1 AND tenant_id = $2 AND owner_id = $3
                ORDER BY profile
                """,
                motion_base_id,
                tenant_id,
                owner_id,
            )
        return tuple(_rendition(row) for row in rows)

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
        async with connection_scope(self._executor) as connection, connection.transaction():
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._renditions}
                WHERE rendition_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                rendition_id,
                tenant_id,
                owner_id,
            )
            if row is None:
                raise KeyError(rendition_id)
            validate_rendition_media(RenditionProfile(row["profile"]), media)
            if row["phase"] in {
                RenditionPhase.READY_FOR_REVIEW.value,
                RenditionPhase.APPROVED.value,
            }:
                existing = _rendition(row)
                if existing.artifact_id != artifact_id or existing.media != media:
                    raise CandidateConflict("rendition already has different immutable media")
                return existing
            if row["phase"] not in {
                RenditionPhase.QUEUED.value,
                RenditionPhase.PROCESSING.value,
            }:
                raise CandidateConflict("rendition is not active")
            if not lease_token or row["lease_token"] != lease_token:
                raise CandidateConflict("rendition lease is not owned by this worker")
            artifact = await connection.fetchrow(
                f"""
                SELECT * FROM {self._artifacts}
                WHERE artifact_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                artifact_id,
                tenant_id,
                owner_id,
            )
            if artifact is None:
                raise CandidateConflict("rendition artifact is outside the job scope")
            if (
                artifact["phase"] != "available"
                or artifact["source_kind"] != "motion_base_rendition"
                or artifact["source_id"] != rendition_id
                or artifact["object_size"] != media.size_bytes
                or artifact["object_sha256"] != media.sha256
            ):
                raise CandidateConflict("rendition artifact does not match the job output")
            row = await connection.fetchrow(
                f"""
                UPDATE {self._renditions}
                SET phase = 'ready_for_review', artifact_id = $2,
                    size_bytes = $3, sha256 = $4, duration_ms = $5,
                    width = $6, height = $7, frame_rate_numerator = $8,
                    frame_rate_denominator = $9, video_codec = $10,
                    has_audio = $11, audio_codec = $12,
                    lease_token = NULL, lease_expires_at = NULL,
                    revision = revision + 1, updated_at = $13
                WHERE rendition_id = $1
                RETURNING *
                """,
                rendition_id,
                artifact_id,
                media.size_bytes,
                media.sha256,
                media.duration_ms,
                media.width,
                media.height,
                media.frame_rate_numerator,
                media.frame_rate_denominator,
                media.video_codec,
                media.has_audio,
                media.audio_codec,
                utc_now(),
            )
            await connection.execute(
                f"""
                UPDATE {self._artifacts}
                SET immutable = true, revision = revision + 1, updated_at = $2
                WHERE artifact_id = $1 AND immutable = false
                """,
                artifact_id,
                utc_now(),
            )
        return _rendition(row)

    async def claim_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
    ) -> RenditionClaim:
        now = utc_now()
        lease_token = str(uuid.uuid4())
        lease_expires_at = now + timedelta(seconds=self._rendition_lease_seconds)
        async with connection_scope(self._executor) as connection, connection.transaction():
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._renditions}
                WHERE rendition_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                rendition_id,
                tenant_id,
                owner_id,
            )
            if row is None:
                raise KeyError(rendition_id)
            if row["phase"] in {
                RenditionPhase.READY_FOR_REVIEW.value,
                RenditionPhase.APPROVED.value,
            }:
                return RenditionClaim(_rendition(row), acquired=False)
            claimable = (
                row["phase"] == RenditionPhase.QUEUED.value
                or (
                    row["phase"] == RenditionPhase.FAILED.value and row["failure_retryable"] is True
                )
                or (
                    row["phase"] == RenditionPhase.PROCESSING.value
                    and row["lease_expires_at"] is not None
                    and row["lease_expires_at"] <= now
                )
            )
            if not claimable:
                return RenditionClaim(_rendition(row), acquired=False)
            row = await connection.fetchrow(
                f"""
                UPDATE {self._renditions}
                SET phase = 'processing', attempt_count = attempt_count + 1,
                    failure_reason = NULL, failure_retryable = NULL,
                    lease_token = $2, lease_expires_at = $3,
                    revision = revision + 1, updated_at = $4
                WHERE rendition_id = $1
                RETURNING *
                """,
                rendition_id,
                lease_token,
                lease_expires_at,
                now,
            )
        return RenditionClaim(_rendition(row), acquired=True)

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
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                UPDATE {self._renditions}
                SET phase = 'failed', failure_reason = $5, failure_retryable = $6,
                    lease_token = NULL, lease_expires_at = NULL,
                    revision = revision + 1, updated_at = $7
                WHERE rendition_id = $1 AND tenant_id = $2 AND owner_id = $3
                  AND phase = 'processing' AND lease_token = $4
                RETURNING *
                """,
                rendition_id,
                tenant_id,
                owner_id,
                lease_token,
                reason,
                retryable,
                utc_now(),
            )
        if row is not None:
            return _rendition(row)
        current = await self.list_renditions_for_id(tenant_id, owner_id, rendition_id)
        if current is None or current.lease_token != lease_token:
            raise CandidateConflict("rendition lease is not owned by this worker")
        return current

    async def list_renditions_for_id(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
    ) -> MotionBaseRendition | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._renditions}
                WHERE rendition_id = $1 AND tenant_id = $2 AND owner_id = $3
                """,
                rendition_id,
                tenant_id,
                owner_id,
            )
        return _rendition(row) if row is not None else None

    async def list_renditions(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]:
        async with connection_scope(self._executor) as connection:
            rows = await connection.fetch(
                f"""
                SELECT * FROM {self._renditions}
                WHERE motion_base_id = $1 AND tenant_id = $2 AND owner_id = $3
                ORDER BY profile
                """,
                motion_base_id,
                tenant_id,
                owner_id,
            )
        return tuple(_rendition(row) for row in rows)

    async def select_motion_base(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str,
        motion_base_id: str,
    ) -> MotionBaseSelection:
        now = utc_now()
        async with connection_scope(self._executor) as connection, connection.transaction():
            motion_base = await connection.fetchrow(
                f"""
                SELECT * FROM {self._motion_bases}
                WHERE motion_base_id = $1 AND tenant_id = $2 AND owner_id = $3
                  AND visual_identity_id = $4 AND phase = 'ready'
                FOR UPDATE
                """,
                motion_base_id,
                tenant_id,
                owner_id,
                visual_identity_id,
            )
            if motion_base is None:
                raise KeyError(motion_base_id)
            approved = await connection.fetchval(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM {self._renditions}
                    WHERE motion_base_id = $1 AND tenant_id = $2 AND owner_id = $3
                      AND phase = 'approved'
                )
                """,
                motion_base_id,
                tenant_id,
                owner_id,
            )
            if not approved:
                raise CandidateConflict("motion base has no approved rendition")
            existing = await connection.fetchrow(
                f"""
                SELECT * FROM {self._selections}
                WHERE tenant_id = $1 AND owner_id = $2 AND visual_identity_id = $3
                FOR UPDATE
                """,
                tenant_id,
                owner_id,
                visual_identity_id,
            )
            if existing is not None and existing["motion_base_id"] == motion_base_id:
                return _selection(existing)
            row = await connection.fetchrow(
                f"""
                INSERT INTO {self._selections} AS current (
                    tenant_id, owner_id, visual_identity_id, motion_base_id,
                    revision, selected_at
                ) VALUES ($1, $2, $3, $4, 1, $5)
                ON CONFLICT (tenant_id, owner_id, visual_identity_id) DO UPDATE
                SET motion_base_id = EXCLUDED.motion_base_id,
                    revision = current.revision + 1,
                    selected_at = EXCLUDED.selected_at
                RETURNING *
                """,
                tenant_id,
                owner_id,
                visual_identity_id,
                motion_base_id,
                now,
            )
        return _selection(row)

    async def get_selection(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str,
    ) -> MotionBaseSelection | None:
        async with connection_scope(self._executor) as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._selections}
                WHERE tenant_id = $1 AND owner_id = $2 AND visual_identity_id = $3
                """,
                tenant_id,
                owner_id,
                visual_identity_id,
            )
        return _selection(row) if row is not None else None

    async def approve_rendition(
        self,
        tenant_id: str,
        owner_id: str,
        rendition_id: str,
        *,
        loop: LoopWindow,
    ) -> tuple[MotionBaseRendition, MotionBaseVideo]:
        async with connection_scope(self._executor) as connection, connection.transaction():
            rendition_row = await connection.fetchrow(
                f"""
                SELECT * FROM {self._renditions}
                WHERE rendition_id = $1 AND tenant_id = $2 AND owner_id = $3
                FOR UPDATE
                """,
                rendition_id,
                tenant_id,
                owner_id,
            )
            if rendition_row is None:
                raise KeyError(rendition_id)
            if rendition_row["duration_ms"] is None:
                raise CandidateConflict("rendition has no verified media")
            if loop.end_ms > rendition_row["duration_ms"]:
                raise ValueError("loop window exceeds rendition duration")
            if rendition_row["phase"] == RenditionPhase.APPROVED.value:
                existing = _rendition(rendition_row)
                if existing.loop != loop:
                    raise CandidateConflict("rendition already has a different loop review")
            else:
                if rendition_row["phase"] != RenditionPhase.READY_FOR_REVIEW.value:
                    raise CandidateConflict("rendition is not ready for review")
                rendition_row = await connection.fetchrow(
                    f"""
                    UPDATE {self._renditions}
                    SET phase = 'approved', loop_start_ms = $2, loop_end_ms = $3,
                        loop_crossfade_ms = $4, revision = revision + 1, updated_at = $5
                    WHERE rendition_id = $1
                    RETURNING *
                    """,
                    rendition_id,
                    loop.start_ms,
                    loop.end_ms,
                    loop.crossfade_ms,
                    utc_now(),
                )
            motion_base_row = await connection.fetchrow(
                f"""
                UPDATE {self._motion_bases}
                SET phase = 'ready'
                WHERE motion_base_id = $1
                RETURNING *
                """,
                rendition_row["motion_base_id"],
            )
        return _rendition(rendition_row), _motion_base(motion_base_row)


def _media(row: Mapping[str, Any]) -> MediaFacts:
    return MediaFacts(
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        duration_ms=row["duration_ms"],
        width=row["width"],
        height=row["height"],
        frame_rate_numerator=row["frame_rate_numerator"],
        frame_rate_denominator=row["frame_rate_denominator"],
        video_codec=row["video_codec"],
        has_audio=row["has_audio"],
        audio_codec=row["audio_codec"],
    )


def _selection(row: Mapping[str, Any]) -> MotionBaseSelection:
    return MotionBaseSelection(
        tenant_id=row["tenant_id"],
        owner_id=row["owner_id"],
        visual_identity_id=row["visual_identity_id"],
        motion_base_id=row["motion_base_id"],
        revision=row["revision"],
        selected_at=row["selected_at"],
    )


def _candidate(row: Mapping[str, Any]) -> MotionBaseCandidate:
    request = CandidateCreateRequest(
        tenant_id=row["tenant_id"],
        owner_id=row["owner_id"],
        visual_identity_id=row["visual_identity_id"],
        source_kind=CandidateSourceKind(row["source_kind"]),
        source_id=row["source_id"],
        artifact_id=row["artifact_id"],
        logical_name=row["logical_name"],
        rights_scope=row["rights_scope"],
        idempotency_key=row["idempotency_key"],
        media=_media(row),
    )
    return MotionBaseCandidate(
        candidate_id=row["candidate_id"],
        request=request,
        phase=MotionBaseCandidatePhase(row["phase"]),
        revision=row["revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        failure_reason=row["failure_reason"],
    )


def _acceptance(row: Mapping[str, Any]) -> AcceptanceRecord:
    request = AcceptanceRequest(
        tenant_id=row["tenant_id"],
        owner_id=row["owner_id"],
        candidate_id=row["candidate_id"],
        reviewer_id=row["reviewer_id"],
        idempotency_key=row["idempotency_key"],
        checks=AcceptanceChecks(
            identity_match=row["identity_match"],
            single_person=row["single_person"],
            closed_mouth=row["closed_mouth"],
            fixed_camera=row["fixed_camera"],
            no_gestures=row["no_gestures"],
            rights_confirmed=row["rights_confirmed"],
        ),
    )
    return AcceptanceRecord(
        acceptance_id=row["acceptance_id"],
        request=request,
        phase=AcceptancePhase(row["phase"]),
        revision=row["revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        motion_base_id=row["motion_base_id"],
        source_master_artifact_id=row["source_master_artifact_id"],
        failure_reason=row["failure_reason"],
        attempt_count=row["attempt_count"],
        failure_retryable=row["failure_retryable"],
        lease_token=row["lease_token"],
        lease_expires_at=row["lease_expires_at"],
    )


def _motion_base(row: Mapping[str, Any]) -> MotionBaseVideo:
    return MotionBaseVideo(
        motion_base_id=row["motion_base_id"],
        tenant_id=row["tenant_id"],
        owner_id=row["owner_id"],
        visual_identity_id=row["visual_identity_id"],
        candidate_id=row["candidate_id"],
        source_master_artifact_id=row["source_master_artifact_id"],
        source_media=_media(row),
        phase=MotionBasePhase(row["phase"]),
        created_at=row["created_at"],
    )


def _rendition(row: Mapping[str, Any]) -> MotionBaseRendition:
    media = _media(row) if row["artifact_id"] is not None else None
    loop = None
    if row["loop_start_ms"] is not None:
        loop = LoopWindow(
            start_ms=row["loop_start_ms"],
            end_ms=row["loop_end_ms"],
            crossfade_ms=row["loop_crossfade_ms"],
        )
    return MotionBaseRendition(
        rendition_id=row["rendition_id"],
        tenant_id=row["tenant_id"],
        owner_id=row["owner_id"],
        motion_base_id=row["motion_base_id"],
        profile=row["profile"],
        phase=RenditionPhase(row["phase"]),
        revision=row["revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        artifact_id=row["artifact_id"],
        media=media,
        fit_mode=row["fit_mode"],
        loop=loop,
        failure_reason=row["failure_reason"],
        attempt_count=row["attempt_count"],
        failure_retryable=row["failure_retryable"],
        lease_token=row["lease_token"],
        lease_expires_at=row["lease_expires_at"],
    )


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
        "idempotency_key": request.idempotency_key,
        "media": _media_payload(request.media),
    }
    return _digest(payload)


def _acceptance_digest(request: AcceptanceRequest) -> str:
    payload = {
        "tenant_id": request.tenant_id,
        "owner_id": request.owner_id,
        "candidate_id": request.candidate_id,
        "reviewer_id": request.reviewer_id,
        "idempotency_key": request.idempotency_key,
        "checks": {
            "identity_match": request.checks.identity_match,
            "single_person": request.checks.single_person,
            "closed_mouth": request.checks.closed_mouth,
            "fixed_camera": request.checks.fixed_camera,
            "no_gestures": request.checks.no_gestures,
            "rights_confirmed": request.checks.rights_confirmed,
        },
    }
    return _digest(payload)


def _media_payload(media: MediaFacts) -> dict[str, object]:
    return {
        "size_bytes": media.size_bytes,
        "sha256": media.sha256,
        "duration_ms": media.duration_ms,
        "width": media.width,
        "height": media.height,
        "frame_rate_numerator": media.frame_rate_numerator,
        "frame_rate_denominator": media.frame_rate_denominator,
        "video_codec": media.video_codec,
        "has_audio": media.has_audio,
        "audio_codec": media.audio_codec,
    }


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
