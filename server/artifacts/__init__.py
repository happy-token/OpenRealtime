"""Large-object storage boundary for audio and Agent artifacts."""

from server.artifacts.boto3_factory import build_s3_object_client_from_env
from server.artifacts.in_memory import InMemoryArtifactStore, InMemoryS3ObjectClient
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactCreateRequest,
    ArtifactPhase,
    ArtifactRecord,
    ArtifactStore,
    BlobReceipt,
    S3ObjectClient,
)
from server.artifacts.s3_client import Boto3S3ObjectClient

__all__ = [
    "ArtifactAccessScope",
    "ArtifactCreateRequest",
    "ArtifactPhase",
    "ArtifactRecord",
    "ArtifactStore",
    "BlobReceipt",
    "Boto3S3ObjectClient",
    "InMemoryArtifactStore",
    "InMemoryS3ObjectClient",
    "S3ObjectClient",
    "build_s3_object_client_from_env",
]
