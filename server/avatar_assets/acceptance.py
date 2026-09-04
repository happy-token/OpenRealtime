"""Deep module that turns verified candidate artifacts into accepted motion assets."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactCreateRequest,
    ArtifactPhase,
    ArtifactStore,
)
from server.avatar_assets.media_probe import FfprobeMediaProbe, MediaProbe
from server.avatar_assets.models import (
    AcceptanceRequest,
    AcceptanceResult,
    CandidateConflict,
    CandidateCreateRequest,
    MotionBaseCandidate,
    MotionBaseVideo,
    WorkInProgress,
)
from server.avatar_assets.registry import MotionBaseRegistry


class MotionBaseAcceptanceModule:
    def __init__(
        self,
        *,
        registry: MotionBaseRegistry,
        artifacts: ArtifactStore,
        media_probe: MediaProbe | None = None,
    ) -> None:
        self._registry = registry
        self._artifacts = artifacts
        self._media_probe = media_probe or FfprobeMediaProbe()
        self._accept_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    async def register_candidate(self, request: CandidateCreateRequest) -> MotionBaseCandidate:
        artifact = await self._artifacts.get_record_for(
            ArtifactAccessScope(request.tenant_id, request.owner_id),
            request.artifact_id,
        )
        if artifact is None or artifact.phase is not ArtifactPhase.AVAILABLE:
            raise ValueError("candidate artifact must be available to the same owner")
        data = await self._artifacts.read_for(
            ArtifactAccessScope(request.tenant_id, request.owner_id),
            request.artifact_id,
        )
        observed = await self._media_probe.probe(data, artifact.request.media_type)
        if artifact.receipt is None or (
            artifact.receipt.size != observed.size_bytes
            or artifact.receipt.sha256 != observed.sha256
        ):
            raise ValueError("candidate probe does not match the verified artifact")
        return await self._registry.create_candidate(replace(request, media=observed))

    async def list_motion_bases(
        self,
        tenant_id: str,
        owner_id: str,
        visual_identity_id: str | None,
    ) -> tuple[MotionBaseVideo, ...]:
        return await self._registry.list_motion_bases(
            tenant_id,
            owner_id,
            visual_identity_id,
        )

    async def accept(self, request: AcceptanceRequest) -> AcceptanceResult:
        lock = self._accept_locks.setdefault(
            (request.tenant_id, request.owner_id, request.candidate_id),
            asyncio.Lock(),
        )
        async with lock:
            return await self._accept(request)

    async def _accept(self, request: AcceptanceRequest) -> AcceptanceResult:
        candidate = await self._registry.get_candidate(request)
        if candidate is None:
            raise KeyError(request.candidate_id)
        claim = await self._registry.claim_acceptance(request)
        acceptance = claim.record
        if acceptance.phase.value == "accepted":
            completed, motion_base = await self._registry.complete_acceptance(
                request.tenant_id,
                request.owner_id,
                acceptance.acceptance_id,
                source_master_artifact_id=acceptance.source_master_artifact_id or "",
            )
            return AcceptanceResult(completed.acceptance_id, motion_base)
        if not claim.acquired or not acceptance.lease_token:
            if acceptance.phase.value == "failed":
                raise CandidateConflict(
                    acceptance.failure_reason or "acceptance failed and cannot be retried"
                )
            raise WorkInProgress(acceptance.acceptance_id)

        source_record = None
        registry_completed = False
        scope = ArtifactAccessScope(request.tenant_id, request.owner_id)
        try:
            source_bytes = await self._artifacts.read_for(
                scope,
                candidate.request.artifact_id,
            )
            candidate_artifact = await self._artifacts.get_record_for(
                scope,
                candidate.request.artifact_id,
            )
            if candidate_artifact is None:
                raise RuntimeError("accepted candidate artifact disappeared")
            source_record = await self._artifacts.create_staging(
                ArtifactCreateRequest(
                    tenant_id=request.tenant_id,
                    owner_id=request.owner_id,
                    source_kind="motion_base_source_master",
                    source_id=candidate.candidate_id,
                    logical_name=candidate.request.logical_name,
                    media_type=candidate_artifact.request.media_type,
                    classification="internal",
                    idempotency_key=(
                        f"motion-base-source-master:{acceptance.acceptance_id}:"
                        f"{acceptance.attempt_count}"
                    ),
                    expected_size=candidate.request.media.size_bytes,
                    expected_sha256=candidate.request.media.sha256,
                )
            )
            if source_record.phase is ArtifactPhase.STAGING:
                source_record = await self._artifacts.upload(
                    source_record.artifact_id,
                    source_bytes,
                )
                source_record = await self._artifacts.finalize(source_record.artifact_id)
            if source_record.phase is not ArtifactPhase.AVAILABLE:
                raise RuntimeError("source master artifact did not become available")
            completed, motion_base = await self._registry.complete_acceptance(
                request.tenant_id,
                request.owner_id,
                acceptance.acceptance_id,
                source_master_artifact_id=source_record.artifact_id,
                lease_token=acceptance.lease_token,
            )
            registry_completed = True
            await self._artifacts.pin_for(scope, source_record.artifact_id)
            return AcceptanceResult(completed.acceptance_id, motion_base)
        except Exception as error:
            if not registry_completed:
                try:
                    await self._registry.fail_acceptance(
                        request.tenant_id,
                        request.owner_id,
                        acceptance.acceptance_id,
                        lease_token=acceptance.lease_token,
                        reason=str(error) or type(error).__name__,
                        retryable=not isinstance(error, (ValueError, CandidateConflict)),
                    )
                except Exception as compensation_error:  # noqa: BLE001 - preserve root error
                    error.add_note(f"failed to persist acceptance failure: {compensation_error}")
            if (
                not registry_completed
                and source_record is not None
                and not source_record.request.immutable
            ):
                try:
                    await self._artifacts.delete_for(scope, source_record.artifact_id)
                except Exception as compensation_error:  # noqa: BLE001 - durable cleanup remains
                    error.add_note(f"failed to clean source-master artifact: {compensation_error}")
            raise
