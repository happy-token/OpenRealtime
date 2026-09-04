from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.artifacts import InMemoryArtifactStore
from server.artifacts.protocol import ArtifactAccessScope, ArtifactPhase
from server.avatar_assets import (
    AcceptanceChecks,
    AvatarAssetHttpApi,
    AvatarAssetScope,
    AvatarAssetService,
    CandidateSourceKind,
    InMemoryMotionBaseRegistry,
    LoopWindow,
    MediaFacts,
    MotionBaseAcceptanceModule,
    MotionBaseRenditionModule,
    RenditionProfile,
)


class DeterministicProbe:
    async def probe(self, data: bytes, media_type: str) -> MediaFacts:
        assert media_type == "video/mp4"
        return MediaFacts(
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            duration_ms=3_120,
            width=720,
            height=1_280,
            frame_rate_numerator=25,
            frame_rate_denominator=1,
            video_codec="h264",
            has_audio=False,
        )


class DeterministicRenditionEngine:
    async def render(
        self,
        source: Path,
        output: Path,
        profile: RenditionProfile,
    ) -> MediaFacts:
        assert source.read_bytes() == b"candidate-video"
        data = f"rendition:{profile.value}".encode()
        output.write_bytes(data)
        width, height = profile.dimensions
        return MediaFacts(
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            duration_ms=3_120,
            width=width,
            height=height,
            frame_rate_numerator=25,
            frame_rate_denominator=1,
            video_codec="h264",
            has_audio=False,
        )


class CommitThenDisconnectAcceptance(MotionBaseAcceptanceModule):
    async def register_candidate(self, request):
        candidate = await super().register_candidate(request)
        self.committed_candidate = candidate
        raise ConnectionError("candidate commit response was lost")


def _service() -> AvatarAssetService:
    artifacts = InMemoryArtifactStore()
    registry = InMemoryMotionBaseRegistry()
    probe = DeterministicProbe()
    acceptance = MotionBaseAcceptanceModule(
        registry=registry,
        artifacts=artifacts,
        media_probe=probe,
    )
    return AvatarAssetService(
        scope=AvatarAssetScope("local", "local-user", "local-user"),
        artifacts=artifacts,
        registry=registry,
        acceptance=acceptance,
        renditions=MotionBaseRenditionModule(
            registry=registry,
            artifacts=artifacts,
            engine=DeterministicRenditionEngine(),  # type: ignore[arg-type]
        ),
        media_probe=probe,
    )


async def test_upload_accept_approve_and_select_remain_separate() -> None:
    service = _service()
    candidate = await service.upload_candidate(
        avatar_id="shuchang",
        source_kind=CandidateSourceKind.UPLOAD,
        source_id="upload-1",
        logical_name="idle.mp4",
        media_type="video/mp4",
        rights_scope="internal_evaluation",
        idempotency_key="upload-1",
        data=b"candidate-video",
    )
    assert candidate["phase"] == "candidate"
    assert candidate["media"]["duration_ms"] == 3_120

    motion_base = await service.accept_candidate(
        candidate["candidate_id"],
        checks=AcceptanceChecks(True, True, True, True, True, True),
        idempotency_key="review-1",
    )
    assert motion_base["phase"] == "preparing"
    assert {item["profile"] for item in motion_base["renditions"]} == {
        "desktop_fullscreen",
        "mobile_fullscreen",
    }
    assert {item["phase"] for item in motion_base["renditions"]} == {
        "ready_for_review"
    }

    before_review = await service.list_avatar_actions("shuchang")
    assert before_review["selection"] is None
    mobile = next(
        item
        for item in motion_base["renditions"]
        if item["profile"] == "mobile_fullscreen"
    )
    approved = await service.approve_rendition(
        mobile["rendition_id"],
        loop=LoopWindow(0, 3_000, 100),
    )
    assert approved["phase"] == "ready"
    assert (await service.list_avatar_actions("shuchang"))["selection"] is None
    global_catalog = await service.list_avatar_actions()
    assert [item["avatar_action_id"] for item in global_catalog["actions"]] == [
        approved["avatar_action_id"]
    ]
    assert global_catalog["selection"] is None

    selection = await service.select_avatar_action(
        "shuchang", approved["avatar_action_id"]
    )
    assert selection["avatar_action_id"] == approved["avatar_action_id"]
    assert selection["revision"] == 1

    rendition_bytes, media_type = await service.read_artifact(mobile["artifact_id"])
    assert rendition_bytes == b"rendition:mobile_fullscreen"
    assert media_type == "video/mp4"


async def test_http_adapter_lists_the_global_avatar_action_library() -> None:
    api = AvatarAssetHttpApi(_service())

    response = await api.handle(
        "GET",
        "/avatar-assets/actions",
        "",
        {},
        b"",
    )

    assert response.status == 200
    assert json.loads(response.body) == {"actions": [], "selection": None}


async def test_http_adapter_serves_artifact_byte_ranges_for_video_playback() -> None:
    api = AvatarAssetHttpApi(_service())
    upload = await api.handle(
        "POST",
        "/avatar-assets/candidates/upload",
        "avatar_id=shuchang&source_kind=upload&source_id=range-video"
        "&logical_name=idle.mp4&rights_scope=internal_evaluation"
        "&idempotency_key=range-video",
        {"content-type": "video/mp4"},
        b"candidate-video",
    )
    artifact_id = json.loads(upload.body)["artifact_id"]

    response = await api.handle(
        "GET",
        f"/avatar-assets/artifacts/{artifact_id}",
        "",
        {"range": "bytes=2-5"},
        b"",
    )

    assert response.status == 206
    assert response.body == b"ndid"
    assert response.headers == {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600, immutable",
        "Content-Range": "bytes 2-5/15",
        "X-Content-Type-Options": "nosniff",
    }


async def test_http_adapter_rejects_incomplete_human_acceptance() -> None:
    api = AvatarAssetHttpApi(_service())
    upload = await api.handle(
        "POST",
        "/avatar-assets/candidates/upload",
        "avatar_id=shuchang&source_kind=upload&source_id=upload-2"
        "&logical_name=idle.mp4&rights_scope=internal_evaluation"
        "&idempotency_key=upload-2",
        {"content-type": "video/mp4"},
        b"candidate-video",
    )
    candidate = json.loads(upload.body)
    response = await api.handle(
        "POST",
        f"/avatar-assets/candidates/{candidate['candidate_id']}/accept",
        "",
        {"content-type": "application/json"},
        json.dumps(
            {
                "idempotency_key": "review-2",
                "checks": {
                    "identity_match": True,
                    "single_person": True,
                    "closed_mouth": False,
                    "fixed_camera": True,
                    "no_gestures": True,
                    "rights_confirmed": True,
                },
            }
        ).encode(),
    )
    assert response.status == 400
    assert b"every Motion Base Acceptance check must pass" in response.body


async def test_upload_recovers_candidate_when_commit_response_is_lost() -> None:
    artifacts = InMemoryArtifactStore(artifact_id_factory=lambda: "artifact-1")
    registry = InMemoryMotionBaseRegistry(candidate_id_factory=lambda: "candidate-1")
    probe = DeterministicProbe()
    acceptance = CommitThenDisconnectAcceptance(
        registry=registry,
        artifacts=artifacts,
        media_probe=probe,
    )
    service = AvatarAssetService(
        scope=AvatarAssetScope("local", "local-user", "local-user"),
        artifacts=artifacts,
        registry=registry,
        acceptance=acceptance,
        renditions=MotionBaseRenditionModule(
            registry=registry,
            artifacts=artifacts,
            engine=DeterministicRenditionEngine(),  # type: ignore[arg-type]
        ),
        media_probe=probe,
    )

    candidate = await service.upload_candidate(
        avatar_id="shuchang",
        source_kind=CandidateSourceKind.UPLOAD,
        source_id="upload-ambiguous",
        logical_name="idle.mp4",
        media_type="video/mp4",
        rights_scope="internal_evaluation",
        idempotency_key="upload-ambiguous",
        data=b"candidate-video",
    )

    assert candidate["candidate_id"] == "candidate-1"
    record = await artifacts.get_record_for(
        ArtifactAccessScope("local", "local-user"),
        "artifact-1",
    )
    assert record is not None
    assert record.phase is ArtifactPhase.AVAILABLE
