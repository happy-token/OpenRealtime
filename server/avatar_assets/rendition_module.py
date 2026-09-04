"""Persist both required playback Renditions for an accepted Motion Base."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactCreateRequest,
    ArtifactPhase,
    ArtifactStore,
)
from server.avatar_assets.models import (
    CandidateConflict,
    MotionBaseRendition,
    RenditionPhase,
    WorkInProgress,
)
from server.avatar_assets.registry import MotionBaseRegistry
from server.avatar_assets.renditions import FfmpegRenditionEngine, RenditionProfile


class MotionBaseRenditionModule:
    def __init__(
        self,
        *,
        registry: MotionBaseRegistry,
        artifacts: ArtifactStore,
        engine: FfmpegRenditionEngine,
    ) -> None:
        self._registry = registry
        self._artifacts = artifacts
        self._engine = engine
        self._generation_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    async def generate_all(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]:
        lock = self._generation_locks.setdefault(
            (tenant_id, owner_id, motion_base_id),
            asyncio.Lock(),
        )
        async with lock:
            return await self._generate_all(tenant_id, owner_id, motion_base_id)

    async def _generate_all(
        self,
        tenant_id: str,
        owner_id: str,
        motion_base_id: str,
    ) -> tuple[MotionBaseRendition, ...]:
        motion_base = await self._registry.get_motion_base(
            tenant_id,
            owner_id,
            motion_base_id,
        )
        if motion_base is None:
            raise KeyError(motion_base_id)
        jobs = await self._registry.create_renditions(
            tenant_id,
            owner_id,
            motion_base_id,
        )
        results = {
            job.rendition_id: job
            for job in jobs
            if job.phase in {RenditionPhase.READY_FOR_REVIEW, RenditionPhase.APPROVED}
        }
        if len(results) == len(jobs):
            return tuple(results[job.rendition_id] for job in jobs)

        scope = ArtifactAccessScope(tenant_id, owner_id)
        source_bytes = await self._artifacts.read_for(
            scope,
            motion_base.source_master_artifact_id,
        )
        with tempfile.TemporaryDirectory(prefix="openrealtime-renditions-") as directory:
            workspace = Path(directory)
            os.chmod(workspace, 0o700)
            source = workspace / "source-master"
            source.write_bytes(source_bytes)
            os.chmod(source, 0o600)
            for queued_job in jobs:
                if queued_job.rendition_id in results:
                    continue
                claim = await self._registry.claim_rendition(
                    tenant_id,
                    owner_id,
                    queued_job.rendition_id,
                )
                if not claim.acquired or not claim.record.lease_token:
                    if claim.record.phase is RenditionPhase.FAILED:
                        raise CandidateConflict(
                            claim.record.failure_reason or "rendition failed and cannot be retried"
                        )
                    raise WorkInProgress(claim.record.rendition_id)
                job = claim.record
                artifact = None
                registry_completed = False
                try:
                    profile = RenditionProfile(job.profile)
                    output = workspace / f"{profile.value}.mp4"
                    media = await self._engine.render(source, output, profile)
                    data = output.read_bytes()
                    artifact = await self._artifacts.create_staging(
                        ArtifactCreateRequest(
                            tenant_id=tenant_id,
                            owner_id=owner_id,
                            source_kind="motion_base_rendition",
                            source_id=job.rendition_id,
                            logical_name=f"{motion_base_id}-{profile.value}.mp4",
                            media_type="video/mp4",
                            classification="internal",
                            idempotency_key=(
                                f"motion-base-rendition:{job.rendition_id}:{job.attempt_count}"
                            ),
                            expected_size=media.size_bytes,
                            expected_sha256=media.sha256,
                        )
                    )
                    if artifact.phase is ArtifactPhase.STAGING:
                        artifact = await self._artifacts.upload(artifact.artifact_id, data)
                        artifact = await self._artifacts.finalize(artifact.artifact_id)
                    if artifact.phase is not ArtifactPhase.AVAILABLE:
                        raise RuntimeError("rendition artifact did not become available")
                    completed = await self._registry.complete_rendition(
                        tenant_id,
                        owner_id,
                        job.rendition_id,
                        artifact_id=artifact.artifact_id,
                        media=media,
                        lease_token=job.lease_token,
                    )
                    registry_completed = True
                    results[job.rendition_id] = completed
                    await self._artifacts.pin_for(scope, artifact.artifact_id)
                except Exception as error:
                    if not registry_completed:
                        try:
                            await self._registry.fail_rendition(
                                tenant_id,
                                owner_id,
                                job.rendition_id,
                                lease_token=job.lease_token,
                                reason=str(error) or type(error).__name__,
                                retryable=not isinstance(
                                    error,
                                    (ValueError, CandidateConflict),
                                ),
                            )
                        except Exception as compensation_error:  # noqa: BLE001 - preserve root
                            error.add_note(
                                f"failed to persist rendition failure: {compensation_error}"
                            )
                    if (
                        not registry_completed
                        and artifact is not None
                        and not artifact.request.immutable
                    ):
                        try:
                            await self._artifacts.delete_for(scope, artifact.artifact_id)
                        except Exception as compensation_error:  # noqa: BLE001 - ledger retries it
                            error.add_note(
                                f"failed to clean rendition artifact: {compensation_error}"
                            )
                    raise
        return tuple(results[job.rendition_id] for job in jobs)
