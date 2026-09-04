"""Persisted digital-human motion-asset domain."""

from server.avatar_assets.acceptance import MotionBaseAcceptanceModule
from server.avatar_assets.http_api import AvatarAssetHttpApi, AvatarAssetHttpResponse
from server.avatar_assets.media_probe import FfprobeMediaProbe, MediaProbe
from server.avatar_assets.models import (
    AcceptanceChecks,
    AcceptanceClaim,
    AcceptancePhase,
    AcceptanceRecord,
    AcceptanceRequest,
    AcceptanceResult,
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
    WorkInProgress,
)
from server.avatar_assets.registry import InMemoryMotionBaseRegistry, MotionBaseRegistry
from server.avatar_assets.rendition_module import MotionBaseRenditionModule
from server.avatar_assets.renditions import FfmpegRenditionEngine, RenditionProfile
from server.avatar_assets.service import AvatarAssetScope, AvatarAssetService

__all__ = [
    "AcceptanceChecks",
    "AcceptanceClaim",
    "AcceptancePhase",
    "AcceptanceRecord",
    "AcceptanceRequest",
    "AcceptanceResult",
    "AvatarAssetHttpApi",
    "AvatarAssetHttpResponse",
    "AvatarAssetScope",
    "AvatarAssetService",
    "CandidateConflict",
    "CandidateCreateRequest",
    "CandidateSourceKind",
    "FfmpegRenditionEngine",
    "FfprobeMediaProbe",
    "InMemoryMotionBaseRegistry",
    "LoopWindow",
    "MediaFacts",
    "MediaProbe",
    "MotionBaseAcceptanceModule",
    "MotionBaseCandidate",
    "MotionBaseCandidatePhase",
    "MotionBasePhase",
    "MotionBaseRegistry",
    "MotionBaseRendition",
    "MotionBaseRenditionModule",
    "MotionBaseSelection",
    "MotionBaseVideo",
    "RenditionClaim",
    "RenditionPhase",
    "RenditionProfile",
    "WorkInProgress",
]
