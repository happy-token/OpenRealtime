from __future__ import annotations

import asyncio
import hashlib

import pytest

from server.artifacts import InMemoryArtifactStore, InMemoryS3ObjectClient
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactConflict,
    ArtifactCreateRequest,
)
from server.avatar_assets import (
    AcceptanceChecks,
    AcceptanceRequest,
    CandidateCreateRequest,
    CandidateSourceKind,
    InMemoryMotionBaseRegistry,
    MediaFacts,
    MotionBaseAcceptanceModule,
)


class _StaticMediaProbe:
    async def probe(self, data: bytes, media_type: str) -> MediaFacts:
        del media_type
        return MediaFacts(
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            duration_ms=3120,
            width=720,
            height=1280,
            frame_rate_numerator=25,
            frame_rate_denominator=1,
            video_codec="h264",
            has_audio=False,
        )


def _module(
    registry: InMemoryMotionBaseRegistry,
    artifacts: InMemoryArtifactStore,
) -> MotionBaseAcceptanceModule:
    return MotionBaseAcceptanceModule(
        registry=registry,
        artifacts=artifacts,
        media_probe=_StaticMediaProbe(),
    )


async def _available_candidate_artifact(
    store: InMemoryArtifactStore,
    *,
    media_type: str = "video/mp4",
) -> str:
    data = b"immutable-source-video"
    staging = await store.create_staging(
        ArtifactCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            source_kind="upload",
            source_id="browser-upload-1",
            logical_name="source.mp4",
            media_type=media_type,
            classification="internal",
            idempotency_key="candidate-artifact-1",
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )
    )
    await store.upload(staging.artifact_id, data)
    return (await store.finalize(staging.artifact_id)).artifact_id


@pytest.mark.asyncio
async def test_registering_provider_success_creates_only_a_candidate() -> None:
    artifacts = InMemoryArtifactStore()
    registry = InMemoryMotionBaseRegistry()
    module = _module(registry, artifacts)
    artifact_id = await _available_candidate_artifact(artifacts)

    candidate = await module.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="browser-upload-1",
            artifact_id=artifact_id,
            logical_name="Shuchang natural idle",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-1",
            media=MediaFacts(
                size_bytes=22,
                sha256=hashlib.sha256(b"immutable-source-video").hexdigest(),
                duration_ms=3120,
                width=720,
                height=1280,
                frame_rate_numerator=25,
                frame_rate_denominator=1,
                video_codec="h264",
                has_audio=False,
            ),
        )
    )

    assert candidate.phase.value == "candidate"
    assert await module.list_motion_bases("tenant-1", "admin-1", "shuchang") == ()


@pytest.mark.asyncio
async def test_acceptance_copies_an_immutable_master_without_selecting_it() -> None:
    artifacts = InMemoryArtifactStore()
    registry = InMemoryMotionBaseRegistry()
    module = _module(registry, artifacts)
    artifact_id = await _available_candidate_artifact(artifacts)
    candidate = await module.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="browser-upload-1",
            artifact_id=artifact_id,
            logical_name="Shuchang natural idle",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-1",
            media=MediaFacts(
                size_bytes=22,
                sha256=hashlib.sha256(b"immutable-source-video").hexdigest(),
                duration_ms=3120,
                width=720,
                height=1280,
                frame_rate_numerator=25,
                frame_rate_denominator=1,
                video_codec="h264",
                has_audio=False,
            ),
        )
    )

    accepted = await module.accept(
        AcceptanceRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            candidate_id=candidate.candidate_id,
            reviewer_id="admin-1",
            idempotency_key="acceptance-1",
            checks=AcceptanceChecks(
                identity_match=True,
                single_person=True,
                closed_mouth=True,
                fixed_camera=True,
                no_gestures=True,
                rights_confirmed=True,
            ),
        )
    )

    assert accepted.motion_base.source_master_artifact_id != artifact_id
    assert (
        await artifacts.read(accepted.motion_base.source_master_artifact_id)
        == b"immutable-source-video"
    )
    assert accepted.selected is False
    with pytest.raises(ArtifactConflict, match="immutable"):
        await artifacts.delete_for(
            ArtifactAccessScope("tenant-1", "admin-1"),
            accepted.motion_base.source_master_artifact_id,
        )
    assert await module.list_motion_bases("tenant-1", "admin-1", "shuchang") == (
        accepted.motion_base,
    )


@pytest.mark.asyncio
async def test_acceptance_rejects_an_incomplete_human_review() -> None:
    artifacts = InMemoryArtifactStore()
    module = _module(InMemoryMotionBaseRegistry(), artifacts)
    artifact_id = await _available_candidate_artifact(artifacts)
    candidate = await module.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="browser-upload-1",
            artifact_id=artifact_id,
            logical_name="Shuchang natural idle",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-1",
            media=MediaFacts(
                size_bytes=22,
                sha256=hashlib.sha256(b"immutable-source-video").hexdigest(),
                duration_ms=3120,
                width=720,
                height=1280,
                frame_rate_numerator=25,
                frame_rate_denominator=1,
                video_codec="h264",
                has_audio=False,
            ),
        )
    )

    with pytest.raises(ValueError, match="every Motion Base Acceptance check"):
        await module.accept(
            AcceptanceRequest(
                tenant_id="tenant-1",
                owner_id="admin-1",
                candidate_id=candidate.candidate_id,
                reviewer_id="admin-1",
                idempotency_key="acceptance-1",
                checks=AcceptanceChecks(
                    identity_match=True,
                    single_person=True,
                    closed_mouth=False,
                    fixed_camera=True,
                    no_gestures=True,
                    rights_confirmed=True,
                ),
            )
        )

    assert await module.list_motion_bases("tenant-1", "admin-1", "shuchang") == ()


@pytest.mark.asyncio
async def test_source_master_preserves_the_verified_candidate_media_type() -> None:
    artifacts = InMemoryArtifactStore()
    module = _module(InMemoryMotionBaseRegistry(), artifacts)
    artifact_id = await _available_candidate_artifact(
        artifacts,
        media_type="video/webm",
    )
    candidate = await module.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="browser-upload-1",
            artifact_id=artifact_id,
            logical_name="source.webm",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-1",
            media=MediaFacts(
                size_bytes=1,
                sha256="0" * 64,
                duration_ms=1,
                width=1,
                height=1,
                frame_rate_numerator=1,
                frame_rate_denominator=1,
                video_codec="untrusted-browser-value",
                has_audio=False,
            ),
        )
    )
    accepted = await module.accept(
        AcceptanceRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            candidate_id=candidate.candidate_id,
            reviewer_id="admin-1",
            idempotency_key="acceptance-1",
            checks=AcceptanceChecks(True, True, True, True, True, True),
        )
    )

    source_master = await artifacts.get_record(accepted.motion_base.source_master_artifact_id)

    assert candidate.request.media.video_codec == "h264"
    assert source_master is not None
    assert source_master.request.media_type == "video/webm"


@pytest.mark.asyncio
async def test_concurrent_acceptance_is_strongly_idempotent() -> None:
    artifacts = InMemoryArtifactStore()
    module = _module(InMemoryMotionBaseRegistry(), artifacts)
    artifact_id = await _available_candidate_artifact(artifacts)
    candidate = await module.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="browser-upload-1",
            artifact_id=artifact_id,
            logical_name="Shuchang natural idle",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-1",
            media=MediaFacts(
                size_bytes=22,
                sha256=hashlib.sha256(b"immutable-source-video").hexdigest(),
                duration_ms=3120,
                width=720,
                height=1280,
                frame_rate_numerator=25,
                frame_rate_denominator=1,
                video_codec="h264",
                has_audio=False,
            ),
        )
    )
    request = AcceptanceRequest(
        tenant_id="tenant-1",
        owner_id="admin-1",
        candidate_id=candidate.candidate_id,
        reviewer_id="admin-1",
        idempotency_key="acceptance-1",
        checks=AcceptanceChecks(
            identity_match=True,
            single_person=True,
            closed_mouth=True,
            fixed_camera=True,
            no_gestures=True,
            rights_confirmed=True,
        ),
    )

    results = await asyncio.gather(*(module.accept(request) for _ in range(20)))

    assert len({result.acceptance_id for result in results}) == 1
    assert len({result.motion_base.motion_base_id for result in results}) == 1
    assert len({result.motion_base.source_master_artifact_id for result in results}) == 1


@pytest.mark.asyncio
async def test_retryable_acceptance_failure_is_persisted_and_recovered() -> None:
    class FailingOnceObjects(InMemoryS3ObjectClient):
        armed = False

        async def put(self, object_key: str, data: bytes, *, media_type: str):
            if self.armed:
                self.armed = False
                raise RuntimeError("temporary object-store outage")
            return await super().put(object_key, data, media_type=media_type)

    objects = FailingOnceObjects()
    artifacts = InMemoryArtifactStore(objects=objects)
    registry = InMemoryMotionBaseRegistry(
        acceptance_id_factory=lambda: "acceptance-1",
    )
    module = _module(registry, artifacts)
    artifact_id = await _available_candidate_artifact(artifacts)
    candidate = await module.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="browser-upload-1",
            artifact_id=artifact_id,
            logical_name="source.mp4",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-1",
            media=MediaFacts(
                22,
                hashlib.sha256(b"immutable-source-video").hexdigest(),
                1,
                1,
                1,
                1,
                1,
                "ignored",
                False,
            ),
        )
    )
    request = AcceptanceRequest(
        tenant_id="tenant-1",
        owner_id="admin-1",
        candidate_id=candidate.candidate_id,
        reviewer_id="admin-1",
        idempotency_key="acceptance-1",
        checks=AcceptanceChecks(True, True, True, True, True, True),
    )
    objects.armed = True

    with pytest.raises(RuntimeError, match="temporary object-store outage"):
        await module.accept(request)
    failed = await registry.get_acceptance("tenant-1", "admin-1", "acceptance-1")
    recovered = await module.accept(request)
    completed = await registry.get_acceptance("tenant-1", "admin-1", "acceptance-1")

    assert failed is not None
    assert failed.phase.value == "failed"
    assert failed.failure_retryable is True
    assert completed is not None
    assert completed.phase.value == "accepted"
    assert completed.attempt_count == 2
    assert recovered.motion_base.candidate_id == candidate.candidate_id
