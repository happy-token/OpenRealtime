from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from server.artifacts import InMemoryArtifactStore
from server.artifacts.protocol import ArtifactCreateRequest
from server.avatar_assets import (
    AcceptanceChecks,
    AcceptanceRequest,
    CandidateConflict,
    CandidateCreateRequest,
    CandidateSourceKind,
    FfmpegRenditionEngine,
    InMemoryMotionBaseRegistry,
    LoopWindow,
    MediaFacts,
    MotionBaseAcceptanceModule,
    MotionBasePhase,
    MotionBaseRenditionModule,
    RenditionPhase,
    RenditionProfile,
)


def _source_video(path: Path) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=#8b3f46:s=720x1280:r=30:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


@pytest.mark.asyncio
async def test_generation_persists_two_unapproved_renditions(tmp_path: Path) -> None:
    class FailingOnceEngine:
        def __init__(self) -> None:
            self._delegate = FfmpegRenditionEngine()
            self._failed = False

        async def render(self, source: Path, output: Path, profile: RenditionProfile):
            if not self._failed:
                self._failed = True
                raise RuntimeError("temporary FFmpeg worker outage")
            return await self._delegate.render(source, output, profile)

    source_path = tmp_path / "source.mp4"
    data = _source_video(source_path)
    digest = hashlib.sha256(data).hexdigest()
    artifacts = InMemoryArtifactStore()
    registry = InMemoryMotionBaseRegistry()
    acceptance = MotionBaseAcceptanceModule(registry=registry, artifacts=artifacts)
    staging = await artifacts.create_staging(
        ArtifactCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            source_kind="upload",
            source_id="upload-1",
            logical_name="source.mp4",
            media_type="video/mp4",
            classification="internal",
            idempotency_key="source-upload-1",
            expected_size=len(data),
            expected_sha256=digest,
        )
    )
    await artifacts.upload(staging.artifact_id, data)
    source_artifact = await artifacts.finalize(staging.artifact_id)
    candidate = await acceptance.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="upload-1",
            artifact_id=source_artifact.artifact_id,
            logical_name="Shuchang natural idle",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-1",
            media=MediaFacts(
                size_bytes=len(data),
                sha256=digest,
                duration_ms=1200,
                width=720,
                height=1280,
                frame_rate_numerator=30,
                frame_rate_denominator=1,
                video_codec="h264",
                has_audio=True,
                audio_codec="aac",
            ),
        )
    )
    result = await acceptance.accept(
        AcceptanceRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            candidate_id=candidate.candidate_id,
            reviewer_id="admin-1",
            idempotency_key="acceptance-1",
            checks=AcceptanceChecks(True, True, True, True, True, True),
        )
    )
    renditions = MotionBaseRenditionModule(
        registry=registry,
        artifacts=artifacts,
        engine=FailingOnceEngine(),
    )

    with pytest.raises(RuntimeError, match="temporary FFmpeg worker outage"):
        await renditions.generate_all(
            "tenant-1",
            "admin-1",
            result.motion_base.motion_base_id,
        )
    failed = await registry.list_renditions(
        "tenant-1",
        "admin-1",
        result.motion_base.motion_base_id,
    )
    generated = await renditions.generate_all(
        "tenant-1",
        "admin-1",
        result.motion_base.motion_base_id,
    )

    assert {item.phase for item in failed} == {
        RenditionPhase.FAILED,
        RenditionPhase.QUEUED,
    }
    failed_job = next(item for item in failed if item.phase is RenditionPhase.FAILED)
    assert failed_job.failure_retryable is True
    assert failed_job.attempt_count == 1
    assert {item.profile for item in generated} == {
        RenditionProfile.MOBILE_FULLSCREEN,
        RenditionProfile.DESKTOP_FULLSCREEN,
    }
    assert all(item.phase is RenditionPhase.READY_FOR_REVIEW for item in generated)
    assert all(item.artifact_id for item in generated)
    assert sorted(item.attempt_count for item in generated) == [1, 2]
    assert await artifacts.read(result.motion_base.source_master_artifact_id) == data
    with pytest.raises(CandidateConflict, match="approved rendition"):
        await registry.select_motion_base(
            "tenant-1",
            "admin-1",
            "shuchang",
            result.motion_base.motion_base_id,
        )

    mobile = next(item for item in generated if item.profile == RenditionProfile.MOBILE_FULLSCREEN)
    approved, ready_motion_base = await registry.approve_rendition(
        "tenant-1",
        "admin-1",
        mobile.rendition_id,
        loop=LoopWindow(start_ms=100, end_ms=900, crossfade_ms=100),
    )
    retried, _ = await registry.approve_rendition(
        "tenant-1",
        "admin-1",
        mobile.rendition_id,
        loop=LoopWindow(start_ms=100, end_ms=900, crossfade_ms=100),
    )

    assert approved.phase is RenditionPhase.APPROVED
    assert approved.loop == LoopWindow(start_ms=100, end_ms=900, crossfade_ms=100)
    assert retried == approved
    assert ready_motion_base.phase is MotionBasePhase.READY
    assert result.selected is False
    assert await registry.get_selection("tenant-1", "admin-1", "shuchang") is None

    selection = await registry.select_motion_base(
        "tenant-1",
        "admin-1",
        "shuchang",
        ready_motion_base.motion_base_id,
    )
    assert selection.motion_base_id == ready_motion_base.motion_base_id
    assert await registry.get_selection("tenant-1", "admin-1", "shuchang") == selection
    assert (
        await registry.select_motion_base(
            "tenant-1",
            "admin-1",
            "shuchang",
            ready_motion_base.motion_base_id,
        )
    ).revision == selection.revision
    with pytest.raises(KeyError):
        await registry.select_motion_base(
            "tenant-1",
            "admin-1",
            "another-identity",
            ready_motion_base.motion_base_id,
        )

    desktop = next(
        item for item in generated if item.profile == RenditionProfile.DESKTOP_FULLSCREEN
    )
    with pytest.raises(ValueError, match="duration"):
        await registry.approve_rendition(
            "tenant-1",
            "admin-1",
            desktop.rendition_id,
            loop=LoopWindow(start_ms=0, end_ms=5000, crossfade_ms=100),
        )
