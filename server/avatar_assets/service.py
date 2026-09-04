"""Application service for the Motion Base asset workflow.

The browser never supplies authoritative media facts.  This service stores the
candidate bytes, delegates probing and acceptance to the domain modules, then
returns serialisable snapshots for the loopback control plane.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactCreateRequest,
    ArtifactPhase,
    ArtifactStore,
)
from server.avatar_assets.acceptance import MotionBaseAcceptanceModule
from server.avatar_assets.media_probe import MediaProbe
from server.avatar_assets.models import (
    AcceptanceChecks,
    AcceptanceRequest,
    CandidateCreateRequest,
    CandidateSourceKind,
    LoopWindow,
    MotionBaseCandidate,
    MotionBaseRendition,
    MotionBaseSelection,
    MotionBaseVideo,
)
from server.avatar_assets.registry import MotionBaseRegistry
from server.avatar_assets.rendition_module import MotionBaseRenditionModule

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MEDIA_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
_MAX_CANDIDATE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AvatarAssetScope:
    tenant_id: str
    owner_id: str
    reviewer_id: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.owner_id, self.reviewer_id):
            _validate_identifier(value, "scope identifier")


class AvatarAssetService:
    def __init__(
        self,
        *,
        scope: AvatarAssetScope,
        artifacts: ArtifactStore,
        registry: MotionBaseRegistry,
        acceptance: MotionBaseAcceptanceModule,
        renditions: MotionBaseRenditionModule,
        media_probe: MediaProbe,
    ) -> None:
        self.scope = scope
        self._artifacts = artifacts
        self._registry = registry
        self._acceptance = acceptance
        self._renditions = renditions
        self._media_probe = media_probe

    async def upload_candidate(
        self,
        *,
        avatar_id: str,
        source_kind: CandidateSourceKind,
        source_id: str,
        logical_name: str,
        media_type: str,
        rights_scope: str,
        idempotency_key: str,
        data: bytes,
    ) -> dict[str, Any]:
        _validate_identifier(avatar_id, "avatar_id")
        _validate_identifier(source_id, "source_id")
        _validate_identifier(idempotency_key, "idempotency_key")
        if media_type not in _MEDIA_TYPES:
            raise ValueError("unsupported candidate video media type")
        if not data or len(data) > _MAX_CANDIDATE_BYTES:
            raise ValueError("candidate video must contain 1 byte to 50 MiB")
        clean_name = Path(logical_name).name.strip()
        if not clean_name or len(clean_name) > 200:
            raise ValueError("logical_name must contain 1 to 200 characters")
        if rights_scope != "internal_evaluation":
            raise ValueError("only internal_evaluation rights are enabled")

        observed = await self._media_probe.probe(data, media_type)
        scope = ArtifactAccessScope(self.scope.tenant_id, self.scope.owner_id)
        artifact = await self._artifacts.create_staging(
            ArtifactCreateRequest(
                tenant_id=self.scope.tenant_id,
                owner_id=self.scope.owner_id,
                source_kind="motion_base_candidate",
                source_id=source_id,
                logical_name=clean_name,
                media_type=media_type,
                classification="internal",
                idempotency_key=f"candidate-artifact:{idempotency_key}",
                expected_size=observed.size_bytes,
                expected_sha256=observed.sha256,
            )
        )
        candidate_request = CandidateCreateRequest(
            tenant_id=self.scope.tenant_id,
            owner_id=self.scope.owner_id,
            visual_identity_id=avatar_id,
            source_kind=source_kind,
            source_id=source_id,
            artifact_id=artifact.artifact_id,
            logical_name=clean_name,
            rights_scope=rights_scope,
            idempotency_key=f"candidate:{idempotency_key}",
            media=observed,
        )
        registration_attempted = False
        try:
            if artifact.phase is ArtifactPhase.STAGING:
                artifact = await self._artifacts.upload(artifact.artifact_id, data)
                artifact = await self._artifacts.finalize(artifact.artifact_id)
            if artifact.phase is not ArtifactPhase.AVAILABLE:
                raise RuntimeError("candidate artifact did not become available")
            registration_attempted = True
            candidate = await self._acceptance.register_candidate(candidate_request)
            return _candidate_payload(candidate)
        except Exception as error:
            safe_to_delete = not registration_attempted
            if registration_attempted:
                try:
                    recovered = await self._registry.find_candidate_by_idempotency(
                        self.scope.tenant_id,
                        self.scope.owner_id,
                        candidate_request.idempotency_key,
                    )
                except Exception as recovery_error:  # noqa: BLE001 - ambiguous commit
                    error.add_note(
                        "failed to resolve ambiguous candidate registration: "
                        f"{recovery_error}"
                    )
                    safe_to_delete = False
                else:
                    if recovered is not None and recovered.request == candidate_request:
                        return _candidate_payload(recovered)
                    safe_to_delete = (
                        recovered is None
                        or recovered.request.artifact_id != artifact.artifact_id
                    )
            if safe_to_delete and not artifact.request.immutable:
                try:
                    await self._artifacts.delete_for(scope, artifact.artifact_id)
                except Exception as cleanup_error:  # noqa: BLE001 - preserve root error
                    error.add_note(f"failed to clean candidate artifact: {cleanup_error}")
            raise

    async def accept_candidate(
        self,
        candidate_id: str,
        *,
        checks: AcceptanceChecks,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _validate_identifier(candidate_id, "candidate_id")
        _validate_identifier(idempotency_key, "idempotency_key")
        accepted = await self._acceptance.accept(
            AcceptanceRequest(
                tenant_id=self.scope.tenant_id,
                owner_id=self.scope.owner_id,
                candidate_id=candidate_id,
                reviewer_id=self.scope.reviewer_id,
                idempotency_key=f"acceptance:{idempotency_key}",
                checks=checks,
            )
        )
        renditions = await self._renditions.generate_all(
            self.scope.tenant_id,
            self.scope.owner_id,
            accepted.motion_base.motion_base_id,
        )
        return await self._motion_base_payload(accepted.motion_base, renditions)

    async def list_avatar_actions(self, avatar_id: str | None = None) -> dict[str, Any]:
        if avatar_id is not None:
            _validate_identifier(avatar_id, "avatar_id")
        motion_bases = await self._registry.list_motion_bases(
            self.scope.tenant_id,
            self.scope.owner_id,
            avatar_id,
        )
        selection = None if avatar_id is None else await self._registry.get_selection(
            self.scope.tenant_id,
            self.scope.owner_id,
            avatar_id,
        )
        return {
            "actions": [
                await self._motion_base_payload(motion_base) for motion_base in motion_bases
            ],
            "selection": _selection_payload(selection) if selection is not None else None,
        }

    async def approve_rendition(
        self,
        rendition_id: str,
        *,
        loop: LoopWindow,
    ) -> dict[str, Any]:
        _validate_identifier(rendition_id, "rendition_id")
        _, motion_base = await self._registry.approve_rendition(
            self.scope.tenant_id,
            self.scope.owner_id,
            rendition_id,
            loop=loop,
        )
        return await self._motion_base_payload(motion_base)

    async def select_avatar_action(
        self,
        avatar_id: str,
        avatar_action_id: str,
    ) -> dict[str, Any]:
        _validate_identifier(avatar_id, "avatar_id")
        _validate_identifier(avatar_action_id, "avatar_action_id")
        selection = await self._registry.select_motion_base(
            self.scope.tenant_id,
            self.scope.owner_id,
            avatar_id,
            avatar_action_id,
        )
        return _selection_payload(selection)

    async def read_artifact(self, artifact_id: str) -> tuple[bytes, str]:
        _validate_identifier(artifact_id, "artifact_id")
        scope = ArtifactAccessScope(self.scope.tenant_id, self.scope.owner_id)
        record = await self._artifacts.get_record_for(scope, artifact_id)
        if record is None or record.phase is not ArtifactPhase.AVAILABLE:
            raise KeyError(artifact_id)
        return await self._artifacts.read_for(scope, artifact_id), record.request.media_type

    async def _motion_base_payload(
        self,
        motion_base: MotionBaseVideo,
        renditions: tuple[MotionBaseRendition, ...] | None = None,
    ) -> dict[str, Any]:
        if renditions is None:
            renditions = await self._registry.list_renditions(
                self.scope.tenant_id,
                self.scope.owner_id,
                motion_base.motion_base_id,
            )
        return {
            "avatar_action_id": motion_base.motion_base_id,
            "avatar_id": motion_base.visual_identity_id,
            "candidate_id": motion_base.candidate_id,
            "source_master_artifact_id": motion_base.source_master_artifact_id,
            "phase": motion_base.phase.value,
            "created_at": motion_base.created_at.isoformat(),
            "source_media": asdict(motion_base.source_media),
            "renditions": [_rendition_payload(item) for item in renditions],
        }


def _candidate_payload(candidate: MotionBaseCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "avatar_id": candidate.request.visual_identity_id,
        "artifact_id": candidate.request.artifact_id,
        "source_kind": candidate.request.source_kind.value,
        "source_id": candidate.request.source_id,
        "logical_name": candidate.request.logical_name,
        "rights_scope": candidate.request.rights_scope,
        "phase": candidate.phase.value,
        "revision": candidate.revision,
        "created_at": candidate.created_at.isoformat(),
        "media": asdict(candidate.request.media),
    }


def _rendition_payload(rendition: MotionBaseRendition) -> dict[str, Any]:
    return {
        "rendition_id": rendition.rendition_id,
        "profile": rendition.profile,
        "phase": rendition.phase.value,
        "artifact_id": rendition.artifact_id,
        "media": asdict(rendition.media) if rendition.media is not None else None,
        "fit_mode": rendition.fit_mode,
        "loop": asdict(rendition.loop) if rendition.loop is not None else None,
        "failure_reason": rendition.failure_reason,
    }


def _selection_payload(selection: MotionBaseSelection) -> dict[str, Any]:
    return {
        "avatar_id": selection.visual_identity_id,
        "avatar_action_id": selection.motion_base_id,
        "revision": selection.revision,
        "selected_at": selection.selected_at.isoformat(),
    }


def _validate_identifier(value: str, field: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} is invalid")
