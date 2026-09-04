from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import timedelta

import pytest

from server.agent_session.driver_protocol import utc_now
from server.artifacts.in_memory import InMemoryArtifactStore, InMemoryS3ObjectClient
from server.artifacts.protocol import (
    ArtifactAccessScope,
    ArtifactConflict,
    ArtifactCreateRequest,
    ArtifactNotAvailable,
    ArtifactPhase,
    BlobReceipt,
)
from server.artifacts.s3_client import Boto3S3ObjectClient


def request_for(data: bytes = b"voice-data") -> ArtifactCreateRequest:
    return ArtifactCreateRequest(
        tenant_id="tenant-1",
        owner_id="user-1",
        source_kind="agent_task",
        source_id="worker-1",
        logical_name="result.bin",
        media_type="application/octet-stream",
        classification="internal",
        idempotency_key="artifact-request-1",
        expected_size=len(data),
        expected_sha256=hashlib.sha256(data).hexdigest(),
    )


@pytest.mark.asyncio
async def test_artifact_is_invisible_until_verified_available() -> None:
    data = b"voice-data"
    store = InMemoryArtifactStore(artifact_id_factory=lambda: "artifact-1")
    staging = await store.create_staging(request_for(data))

    with pytest.raises(ArtifactNotAvailable):
        await store.read(staging.artifact_id)

    uploaded = await store.upload(staging.artifact_id, data)
    assert uploaded.phase is ArtifactPhase.STAGING
    available = await store.finalize(staging.artifact_id)

    assert available.phase is ArtifactPhase.AVAILABLE
    assert await store.read(staging.artifact_id) == data


@pytest.mark.asyncio
async def test_artifact_idempotency_conflict_and_digest_mismatch_fail_closed() -> None:
    store = InMemoryArtifactStore(artifact_id_factory=lambda: "artifact-1")
    request = request_for()
    first = await store.create_staging(request)
    same = await store.create_staging(request)

    assert same == first
    with pytest.raises(ArtifactConflict):
        await store.create_staging(replace(request, logical_name="different.bin"))
    with pytest.raises(ArtifactConflict):
        await store.upload(first.artifact_id, b"wrong")


@pytest.mark.asyncio
async def test_artifact_rejects_invalid_object_store_receipt() -> None:
    class InvalidReceiptClient(InMemoryS3ObjectClient):
        protected_key = "artifacts/protected"

        async def put(
            self, object_key: str, data: bytes, *, media_type: str
        ) -> BlobReceipt:
            await super().put(self.protected_key, b"protected", media_type=media_type)
            receipt = await super().put(object_key, data, media_type=media_type)
            return replace(receipt, object_key=self.protected_key)

    store = InMemoryArtifactStore(
        objects=InvalidReceiptClient(), artifact_id_factory=lambda: "artifact-1"
    )
    record = await store.create_staging(request_for())

    with pytest.raises(ArtifactConflict, match="invalid upload receipt"):
        await store.upload(record.artifact_id, b"voice-data")
    assert await store._objects.get(InvalidReceiptClient.protected_key) == b"protected"


@pytest.mark.asyncio
async def test_concurrent_uploads_cannot_overwrite_the_winning_blob() -> None:
    store = InMemoryArtifactStore(artifact_id_factory=lambda: "artifact-1")
    request = replace(request_for(), expected_size=None, expected_sha256=None)
    record = await store.create_staging(request)

    outcomes = await asyncio.gather(
        store.upload(record.artifact_id, b"first"),
        store.upload(record.artifact_id, b"second"),
        return_exceptions=True,
    )
    winners = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]

    assert len(winners) == 1
    await store.finalize(record.artifact_id)
    assert await store.read(record.artifact_id) in {b"first", b"second"}


@pytest.mark.asyncio
async def test_retention_blocks_delete_then_delete_is_idempotent() -> None:
    data = b"voice-data"
    store = InMemoryArtifactStore(artifact_id_factory=lambda: "artifact-1")
    record = await store.create_staging(
        replace(request_for(data), retention_until=utc_now() + timedelta(hours=1))
    )
    await store.upload(record.artifact_id, data)
    await store.finalize(record.artifact_id)

    with pytest.raises(ArtifactConflict):
        await store.delete(record.artifact_id)

    deletable_store = InMemoryArtifactStore(
        artifact_id_factory=lambda: "artifact-deletable"
    )
    deletable = await deletable_store.create_staging(request_for(data))
    await deletable_store.upload(deletable.artifact_id, data)
    await deletable_store.finalize(deletable.artifact_id)
    deleted = await deletable_store.delete(deletable.artifact_id)
    deleted_again = await deletable_store.delete(deletable.artifact_id)

    assert deleted.phase is ArtifactPhase.DELETED
    assert deleted_again == deleted


@pytest.mark.asyncio
async def test_unbound_output_can_be_cleaned_up_but_pinned_output_cannot() -> None:
    store = InMemoryArtifactStore(artifact_id_factory=lambda: "artifact-1")
    scope = ArtifactAccessScope("tenant-1", "user-1")
    record = await store.create_staging(request_for())
    await store.upload(record.artifact_id, b"voice-data")
    await store.finalize(record.artifact_id)

    pinned = await store.pin_for(scope, record.artifact_id)

    assert pinned.request.immutable is True
    with pytest.raises(ArtifactConflict, match="immutable"):
        await store.delete_for(scope, record.artifact_id)


@pytest.mark.asyncio
async def test_concurrent_losing_upload_removes_its_unreferenced_object() -> None:
    class YieldingClient(InMemoryS3ObjectClient):
        async def put(
            self, object_key: str, data: bytes, *, media_type: str
        ) -> BlobReceipt:
            receipt = await super().put(object_key, data, media_type=media_type)
            await asyncio.sleep(0)
            return receipt

        @property
        def object_keys(self) -> set[str]:
            return set(self._objects)

    objects = YieldingClient()
    store = InMemoryArtifactStore(
        objects=objects,
        artifact_id_factory=lambda: "artifact-1",
    )
    record = await store.create_staging(
        replace(request_for(), expected_size=None, expected_sha256=None)
    )

    outcomes = await asyncio.gather(
        store.upload(record.artifact_id, b"first"),
        store.upload(record.artifact_id, b"second"),
        return_exceptions=True,
    )
    winner = next(outcome for outcome in outcomes if not isinstance(outcome, Exception))

    assert winner.receipt is not None
    assert objects.object_keys == {winner.receipt.object_key}


@pytest.mark.asyncio
async def test_invalid_concurrent_receipt_cannot_delete_the_valid_upload() -> None:
    class MixedReceiptClient(InMemoryS3ObjectClient):
        def __init__(self) -> None:
            super().__init__()
            self._arrivals = 0
            self._both_arrived = asyncio.Event()

        async def put(
            self, object_key: str, data: bytes, *, media_type: str
        ) -> BlobReceipt:
            receipt = await super().put(object_key, data, media_type=media_type)
            self._arrivals += 1
            attempt = self._arrivals
            if attempt == 2:
                self._both_arrived.set()
            await self._both_arrived.wait()
            if attempt == 1:
                return replace(receipt, size=receipt.size + 1)
            return receipt

    objects = MixedReceiptClient()
    store = InMemoryArtifactStore(
        objects=objects,
        artifact_id_factory=lambda: "artifact-1",
    )
    record = await store.create_staging(request_for())

    outcomes = await asyncio.gather(
        store.upload(record.artifact_id, b"voice-data"),
        store.upload(record.artifact_id, b"voice-data"),
        return_exceptions=True,
    )
    winner = next(outcome for outcome in outcomes if not isinstance(outcome, Exception))

    assert winner.receipt is not None
    assert await objects.head(winner.receipt.object_key) == winner.receipt


def test_artifact_digest_requires_canonical_lowercase_hex() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(request_for(), expected_sha256="G" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(request_for(), expected_sha256="A" * 64)


@pytest.mark.asyncio
@pytest.mark.parametrize("object_key", ["", "../escape", "a/../escape", "a//b", "a\\b"])
async def test_s3_adapter_rejects_ambiguous_object_keys(object_key: str) -> None:
    client = Boto3S3ObjectClient(object(), bucket="artifacts")

    with pytest.raises(ValueError, match="object_key"):
        await client.put(object_key, b"data", media_type="application/octet-stream")
