from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio

from server.artifacts import InMemoryS3ObjectClient
from server.artifacts.protocol import ArtifactAccessScope, ArtifactCreateRequest
from server.avatar_assets import (
    AcceptanceChecks,
    AcceptanceRequest,
    CandidateConflict,
    CandidateCreateRequest,
    CandidateSourceKind,
    FfmpegRenditionEngine,
    LoopWindow,
    MediaFacts,
    MotionBaseAcceptanceModule,
    MotionBasePhase,
    MotionBaseRenditionModule,
    RenditionPhase,
    RenditionProfile,
)
from server.persistence.postgres import (
    PostgresArtifactStore,
    PostgresMotionBaseRegistry,
    apply_migrations,
)
from server.persistence.postgres.schema import render_migrations

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 for PostgreSQL tests",
)


@pytest_asyncio.fixture
async def postgres() -> tuple[object, str]:
    asyncpg = pytest.importorskip("asyncpg")
    dsn = os.getenv("VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=12)
    schema = f"voiceagent_avatar_test_{uuid.uuid4().hex}"
    async with pool.acquire() as connection:
        await apply_migrations(connection, schema=schema)
    try:
        yield pool, schema
    finally:
        async with pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await pool.close()


@pytest.mark.asyncio
async def test_acceptance_survives_process_rebuild_and_concurrent_retry(
    postgres,
    tmp_path: Path,
) -> None:
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    artifacts = PostgresArtifactStore(pool, objects=objects, schema=schema)
    data = _video_bytes(tmp_path / "accepted-source.mp4")
    staging = await artifacts.create_staging(
        ArtifactCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            source_kind="upload",
            source_id="browser-upload-1",
            logical_name="source.mp4",
            media_type="video/mp4",
            classification="internal",
            idempotency_key="candidate-artifact-1",
            expected_size=len(data),
            expected_sha256=hashlib.sha256(data).hexdigest(),
        )
    )
    await artifacts.upload(staging.artifact_id, data)
    artifact_id = (await artifacts.finalize(staging.artifact_id)).artifact_id
    first_process = MotionBaseAcceptanceModule(
        registry=PostgresMotionBaseRegistry(pool, schema=schema),
        artifacts=artifacts,
    )
    candidate = await first_process.register_candidate(
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
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
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
    rebuilt_registry = PostgresMotionBaseRegistry(pool, schema=schema)
    recovered_candidate = await rebuilt_registry.find_candidate_by_idempotency(
        "tenant-1",
        "admin-1",
        "candidate-1",
    )
    assert recovered_candidate == candidate
    assert (
        await rebuilt_registry.find_candidate_by_idempotency(
            "tenant-1",
            "other-owner",
            "candidate-1",
        )
        is None
    )
    request = AcceptanceRequest(
        tenant_id="tenant-1",
        owner_id="admin-1",
        candidate_id=candidate.candidate_id,
        reviewer_id="admin-1",
        idempotency_key="acceptance-1",
        checks=AcceptanceChecks(True, True, True, True, True, True),
    )

    results = await asyncio.gather(*(first_process.accept(request) for _ in range(20)))
    rebuilt = MotionBaseAcceptanceModule(
        registry=PostgresMotionBaseRegistry(pool, schema=schema),
        artifacts=PostgresArtifactStore(pool, objects=objects, schema=schema),
    )
    recovered = await rebuilt.list_motion_bases("tenant-1", "admin-1", "shuchang")

    assert len({result.motion_base.motion_base_id for result in results}) == 1
    assert recovered == (results[0].motion_base,)
    assert await artifacts.read(recovered[0].source_master_artifact_id) == data


def _video_bytes(path: Path) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=#8b3f46:s=720x1280:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


@pytest.mark.asyncio
async def test_rendition_jobs_survive_registry_rebuild(postgres, tmp_path: Path) -> None:
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    artifacts = PostgresArtifactStore(pool, objects=objects, schema=schema)
    data = _video_bytes(tmp_path / "source.mp4")
    digest = hashlib.sha256(data).hexdigest()
    staging = await artifacts.create_staging(
        ArtifactCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            source_kind="upload",
            source_id="upload-rendition-1",
            logical_name="source.mp4",
            media_type="video/mp4",
            classification="internal",
            idempotency_key="rendition-source-artifact",
            expected_size=len(data),
            expected_sha256=digest,
        )
    )
    await artifacts.upload(staging.artifact_id, data)
    source = await artifacts.finalize(staging.artifact_id)
    registry = PostgresMotionBaseRegistry(pool, schema=schema)
    acceptance = MotionBaseAcceptanceModule(registry=registry, artifacts=artifacts)
    candidate = await acceptance.register_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            visual_identity_id="shuchang",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="upload-rendition-1",
            artifact_id=source.artifact_id,
            logical_name="Shuchang neutral",
            rights_scope="internal_evaluation",
            idempotency_key="rendition-candidate",
            media=MediaFacts(
                size_bytes=len(data),
                sha256=digest,
                duration_ms=1000,
                width=720,
                height=1280,
                frame_rate_numerator=30,
                frame_rate_denominator=1,
                video_codec="h264",
                has_audio=False,
            ),
        )
    )
    accepted = await acceptance.accept(
        AcceptanceRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            candidate_id=candidate.candidate_id,
            reviewer_id="admin-1",
            idempotency_key="rendition-acceptance",
            checks=AcceptanceChecks(True, True, True, True, True, True),
        )
    )
    module = MotionBaseRenditionModule(
        registry=registry,
        artifacts=artifacts,
        engine=FfmpegRenditionEngine(),
    )
    queued = await registry.create_renditions(
        "tenant-1",
        "admin-1",
        accepted.motion_base.motion_base_id,
    )
    mobile = next(item for item in queued if item.profile == RenditionProfile.MOBILE_FULLSCREEN)
    invalid_media = replace(
        accepted.motion_base.source_media,
        width=640,
        height=960,
        frame_rate_numerator=25,
        frame_rate_denominator=1,
        has_audio=False,
        audio_codec=None,
    )
    invalid = await artifacts.create_staging(
        ArtifactCreateRequest(
            tenant_id="tenant-1",
            owner_id="admin-1",
            source_kind="motion_base_rendition",
            source_id=mobile.rendition_id,
            logical_name="invalid-mobile.mp4",
            media_type="video/mp4",
            classification="internal",
            idempotency_key="invalid-mobile-rendition",
            expected_size=len(data),
            expected_sha256=digest,
        )
    )
    await artifacts.upload(invalid.artifact_id, data)
    await artifacts.finalize(invalid.artifact_id)
    with pytest.raises(ValueError, match="dimensions"):
        await registry.complete_rendition(
            "tenant-1",
            "admin-1",
            mobile.rendition_id,
            artifact_id=invalid.artifact_id,
            media=invalid_media,
        )
    await artifacts.delete_for(
        ArtifactAccessScope("tenant-1", "admin-1"),
        invalid.artifact_id,
    )

    generated = await module.generate_all(
        "tenant-1",
        "admin-1",
        accepted.motion_base.motion_base_id,
    )
    rebuilt = PostgresMotionBaseRegistry(pool, schema=schema)
    recovered = await rebuilt.list_renditions(
        "tenant-1",
        "admin-1",
        accepted.motion_base.motion_base_id,
    )

    assert {item.profile for item in generated} == {
        RenditionProfile.MOBILE_FULLSCREEN,
        RenditionProfile.DESKTOP_FULLSCREEN,
    }
    assert generated == recovered
    assert all(item.phase is RenditionPhase.READY_FOR_REVIEW for item in recovered)

    mobile = next(item for item in recovered if item.profile == RenditionProfile.MOBILE_FULLSCREEN)
    approved, available = await rebuilt.approve_rendition(
        "tenant-1",
        "admin-1",
        mobile.rendition_id,
        loop=LoopWindow(start_ms=100, end_ms=900, crossfade_ms=100),
    )
    restarted = PostgresMotionBaseRegistry(pool, schema=schema)

    assert approved.loop == LoopWindow(start_ms=100, end_ms=900, crossfade_ms=100)
    assert available.phase is MotionBasePhase.READY
    assert (
        await restarted.get_motion_base(
            "tenant-1",
            "admin-1",
            accepted.motion_base.motion_base_id,
        )
    ) == available
    assert await restarted.get_selection("tenant-1", "admin-1", "shuchang") is None
    selected_results = await asyncio.gather(
        *(
            PostgresMotionBaseRegistry(pool, schema=schema).select_motion_base(
                "tenant-1",
                "admin-1",
                "shuchang",
                available.motion_base_id,
            )
            for _ in range(20)
        )
    )
    selected = selected_results[0]
    assert {item.revision for item in selected_results} == {1}
    assert (
        await PostgresMotionBaseRegistry(pool, schema=schema).get_selection(
            "tenant-1",
            "admin-1",
            "shuchang",
        )
    ) == selected


@pytest.mark.asyncio
async def test_acceptance_cannot_bind_another_tenants_artifact(postgres) -> None:
    pool, schema = postgres
    objects = InMemoryS3ObjectClient()
    artifacts = PostgresArtifactStore(pool, objects=objects, schema=schema)
    registry = PostgresMotionBaseRegistry(pool, schema=schema)
    data = b"same-verified-bytes"
    digest = hashlib.sha256(data).hexdigest()

    candidate_artifact = await artifacts.create_staging(
        ArtifactCreateRequest(
            tenant_id="tenant-a",
            owner_id="admin-a",
            source_kind="upload",
            source_id="upload-a",
            logical_name="source.mp4",
            media_type="video/mp4",
            classification="internal",
            idempotency_key="candidate-a-artifact",
            expected_size=len(data),
            expected_sha256=digest,
        )
    )
    await artifacts.upload(candidate_artifact.artifact_id, data)
    await artifacts.finalize(candidate_artifact.artifact_id)
    candidate = await registry.create_candidate(
        CandidateCreateRequest(
            tenant_id="tenant-a",
            owner_id="admin-a",
            visual_identity_id="identity-a",
            source_kind=CandidateSourceKind.UPLOAD,
            source_id="upload-a",
            artifact_id=candidate_artifact.artifact_id,
            logical_name="source.mp4",
            rights_scope="internal_evaluation",
            idempotency_key="candidate-a",
            media=MediaFacts(
                size_bytes=len(data),
                sha256=digest,
                duration_ms=1000,
                width=720,
                height=1280,
                frame_rate_numerator=25,
                frame_rate_denominator=1,
                video_codec="h264",
                has_audio=False,
            ),
        )
    )
    acceptance = await registry.claim_acceptance(
        AcceptanceRequest(
            tenant_id="tenant-a",
            owner_id="admin-a",
            candidate_id=candidate.candidate_id,
            reviewer_id="admin-a",
            idempotency_key="accept-a",
            checks=AcceptanceChecks(True, True, True, True, True, True),
        )
    )
    foreign = await artifacts.create_staging(
        ArtifactCreateRequest(
            tenant_id="tenant-b",
            owner_id="admin-b",
            source_kind="motion_base_source_master",
            source_id=candidate.candidate_id,
            logical_name="foreign.mp4",
            media_type="video/mp4",
            classification="internal",
            idempotency_key="foreign-source-master",
            expected_size=len(data),
            expected_sha256=digest,
        )
    )
    await artifacts.upload(foreign.artifact_id, data)
    await artifacts.finalize(foreign.artifact_id)

    with pytest.raises(CandidateConflict, match="outside the acceptance scope"):
        await registry.complete_acceptance(
            "tenant-a",
            "admin-a",
            acceptance.record.acceptance_id,
            source_master_artifact_id=foreign.artifact_id,
            lease_token=acceptance.record.lease_token,
        )


@pytest.mark.asyncio
async def test_recovery_migrations_backfill_legacy_inflight_jobs() -> None:
    asyncpg = pytest.importorskip("asyncpg")
    dsn = os.getenv("VOICEAGENT_POSTGRES_TEST_DSN", "postgresql:///postgres?host=/tmp")
    connection = await asyncpg.connect(dsn)
    schema = f"voiceagent_avatar_upgrade_{uuid.uuid4().hex}"
    migrations = render_migrations(schema)
    try:
        for migration in migrations[:13]:
            await connection.execute(migration)
        digest = "0" * 64
        await connection.execute(
            f"""
            INSERT INTO "{schema}".artifacts (
                artifact_id, tenant_id, owner_id, source_kind, source_id,
                logical_name, media_type, classification, idempotency_key,
                request_digest, expected_size, expected_sha256, phase, revision,
                object_key, object_size, object_sha256, created_at, updated_at
            ) VALUES
                ('a1', 't', 'o', 'upload', 'u1', 'a.mp4', 'video/mp4', 'internal',
                 'a1', $1, 1, $1, 'available', 1, 'a1-key', 1, $1, now(), now()),
                ('a2', 't', 'o', 'motion_base_source_master', 'c2', 'b.mp4',
                 'video/mp4', 'internal', 'a2', $1, 1, $1, 'available', 1,
                 'a2-key', 1, $1, now(), now())
            """,
            digest,
        )
        await connection.execute(
            f"""
            INSERT INTO "{schema}".motion_base_candidates (
                candidate_id, tenant_id, owner_id, visual_identity_id, source_kind,
                source_id, artifact_id, logical_name, rights_scope, idempotency_key,
                request_digest, size_bytes, sha256, duration_ms, width, height,
                frame_rate_numerator, frame_rate_denominator, video_codec, has_audio,
                phase, revision, created_at, updated_at
            ) VALUES
                ('c1', 't', 'o', 'v', 'upload', 'u1', 'a1', 'a', 'internal', 'c1',
                 $1, 1, $1, 1000, 720, 1280, 25, 1, 'h264', false,
                 'accepting', 1, now(), now()),
                ('c2', 't', 'o', 'v', 'upload', 'u2', 'a1', 'b', 'internal', 'c2',
                 $1, 1, $1, 1000, 720, 1280, 25, 1, 'h264', false,
                 'accepted', 1, now(), now())
            """,
            digest,
        )
        await connection.execute(
            f"""
            INSERT INTO "{schema}".motion_base_acceptances (
                acceptance_id, tenant_id, owner_id, candidate_id, reviewer_id,
                idempotency_key, request_digest, identity_match, single_person,
                closed_mouth, fixed_camera, no_gestures, rights_confirmed,
                phase, revision, created_at, updated_at
            ) VALUES ('acc1', 't', 'o', 'c1', 'o', 'acc1', $1,
                true, true, true, true, true, true, 'accepting', 1, now(), now())
            """,
            digest,
        )

        await connection.execute(migrations[13])
        acceptance = await connection.fetchrow(
            f"SELECT * FROM \"{schema}\".motion_base_acceptances WHERE acceptance_id = 'acc1'"
        )
        assert acceptance["phase"] == "failed"
        assert acceptance["failure_retryable"] is True
        assert acceptance["attempt_count"] == 1

        await connection.execute(
            f"""
            INSERT INTO "{schema}".motion_base_acceptances (
                acceptance_id, tenant_id, owner_id, candidate_id, reviewer_id,
                idempotency_key, request_digest, identity_match, single_person,
                closed_mouth, fixed_camera, no_gestures, rights_confirmed,
                phase, source_master_artifact_id, revision, created_at, updated_at
            ) VALUES ('acc2', 't', 'o', 'c2', 'o', 'acc2', $1,
                true, true, true, true, true, true, 'accepted', 'a2', 1, now(), now());
            """,
            digest,
        )
        await connection.execute(
            f"""
            INSERT INTO "{schema}".motion_base_videos (
                motion_base_id, tenant_id, owner_id, visual_identity_id, candidate_id,
                acceptance_id, source_master_artifact_id, size_bytes, sha256,
                duration_ms, width, height, frame_rate_numerator,
                frame_rate_denominator, video_codec, has_audio, created_at
            ) VALUES ('mb2', 't', 'o', 'v', 'c2', 'acc2', 'a2', 1, $1,
                1000, 720, 1280, 25, 1, 'h264', false, now());
            """,
            digest,
        )
        await connection.execute(
            f"""
            UPDATE "{schema}".motion_base_acceptances
            SET motion_base_id = 'mb2' WHERE acceptance_id = 'acc2';
            """
        )
        await connection.execute(
            f"""
            INSERT INTO "{schema}".motion_base_renditions (
                rendition_id, tenant_id, owner_id, motion_base_id, profile, phase,
                fit_mode, revision, created_at, updated_at
            ) VALUES ('r1', 't', 'o', 'mb2', 'mobile_fullscreen', 'processing',
                'blur_pad', 1, now(), now());
            """
        )
        await connection.execute(migrations[14])
        rendition = await connection.fetchrow(
            f"SELECT * FROM \"{schema}\".motion_base_renditions WHERE rendition_id = 'r1'"
        )
        assert rendition["phase"] == "failed"
        assert rendition["failure_retryable"] is True
        assert rendition["attempt_count"] == 1
    finally:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
