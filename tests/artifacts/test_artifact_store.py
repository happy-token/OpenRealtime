from __future__ import annotations

import asyncio
import hashlib
import threading
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

        async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
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

    deletable_store = InMemoryArtifactStore(artifact_id_factory=lambda: "artifact-deletable")
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
        async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
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

        async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
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


@pytest.mark.asyncio
async def test_recording_retention_expires_and_preserves_pinned_and_unrelated(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    now = utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    store = InMemoryArtifactStore()
    records = []
    for key, kind in [
        ("expired", "voice_session_recording"),
        ("pinned", "voice_session_recording"),
        ("other", "agent_task"),
    ]:
        record = await store.create_staging(
            replace(
                request_for(),
                source_kind=kind,
                idempotency_key=key,
                retention_until=now + timedelta(days=7),
            )
        )
        await store.upload(record.artifact_id, b"voice-data")
        records.append(await store.finalize(record.artifact_id))
    await store.pin_for(ArtifactAccessScope("tenant-1", "user-1"), records[1].artifact_id)
    assert (await store.reconcile_cleanup_ledger())["artifacts_cleaned"] == 0
    now += timedelta(days=7)
    assert (await store.reconcile_cleanup_ledger(limit=1))["artifacts_cleaned"] == 1
    assert (await store.get_record(records[0].artifact_id)).phase is ArtifactPhase.DELETED
    for record in records[1:]:
        assert await store.read(record.artifact_id) == b"voice-data"
    assert (await store.reconcile_cleanup_ledger())["artifacts_cleaned"] == 0


@pytest.mark.asyncio
async def test_recording_expiry_delete_failure_remains_retryable(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    class FailOnce(InMemoryS3ObjectClient):
        failed = False

        async def delete(self, object_key: str) -> None:
            if not self.failed:
                self.failed = True
                raise OSError("object deletion offline")
            await super().delete(object_key)

    now = utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    store = InMemoryArtifactStore(objects=FailOnce())
    record = await store.create_staging(
        replace(
            request_for(),
            source_kind="voice_session_recording",
            retention_until=now + timedelta(days=7),
        )
    )
    await store.upload(record.artifact_id, b"voice-data")
    await store.finalize(record.artifact_id)
    now += timedelta(days=7)
    assert (await store.reconcile_cleanup_ledger())["artifacts_cleaned"] == 0
    failed = await store.get_record(record.artifact_id)
    assert failed.phase is ArtifactPhase.DELETING
    assert failed.failure_reason == "object deletion offline"
    assert (await store.reconcile_cleanup_ledger())["artifacts_cleaned"] == 1
    assert (await store.get_record(record.artifact_id)).failure_reason is None


@pytest.mark.parametrize("limit", [0, -1, True, 1001])
@pytest.mark.asyncio
async def test_recording_cleanup_limit_is_bounded(limit) -> None:
    with pytest.raises(ValueError):
        await InMemoryArtifactStore().reconcile_cleanup_ledger(limit=limit)


def test_recording_without_expiry_is_rejected() -> None:
    with pytest.raises(ValueError, match="retention"):
        replace(request_for(), source_kind="voice_session_recording")


@pytest.mark.asyncio
async def test_recording_delete_claim_rejects_late_pin(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    class PausedDelete(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.resume = asyncio.Event()

        async def delete(self, object_key):
            self.entered.set()
            await self.resume.wait()
            await super().delete(object_key)

    now = module.utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    objects = PausedDelete()
    store = InMemoryArtifactStore(objects=objects)
    record = await store.create_staging(
        replace(
            request_for(),
            source_kind="voice_session_recording",
            retention_until=now + timedelta(days=7),
        )
    )
    await store.upload(record.artifact_id, b"voice-data")
    await store.finalize(record.artifact_id)
    now += timedelta(days=7)
    cleanup = asyncio.create_task(store.reconcile_cleanup_ledger())
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        with pytest.raises(ArtifactNotAvailable):
            await store.pin_for(ArtifactAccessScope("tenant-1", "user-1"), record.artifact_id)
        assert (await store.get_record(record.artifact_id)).phase is ArtifactPhase.DELETING
    finally:
        objects.resume.set()
        result = await asyncio.wait_for(cleanup, 1)
    assert result["artifacts_cleaned"] == 1
    assert (await store.get_record(record.artifact_id)).phase is ArtifactPhase.DELETED


@pytest.mark.asyncio
async def test_expiry_delete_is_not_resurrected_by_late_failed_finalization(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    class PausedHead(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.resume = asyncio.Event()

        async def head(self, object_key):
            self.entered.set()
            await self.resume.wait()
            return await super().head(object_key)

    now = module.utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    objects = PausedHead()
    store = InMemoryArtifactStore(objects=objects)
    record = await store.create_staging(
        replace(
            request_for(),
            source_kind="voice_session_recording",
            retention_until=now + timedelta(days=7),
        )
    )
    await store.upload(record.artifact_id, b"voice-data")
    finalize = asyncio.create_task(store.finalize(record.artifact_id))
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        now += timedelta(days=7)
        assert (await store.reconcile_cleanup_ledger())["artifacts_cleaned"] == 1
    finally:
        objects.resume.set()
    with pytest.raises(ArtifactConflict, match="changed"):
        await finalize
    assert (await store.get_record(record.artifact_id)).phase is ArtifactPhase.DELETED


@pytest.mark.asyncio
async def test_recording_late_put_cleanup_is_retryable(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    class LatePut(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.resume = asyncio.Event()
            self.failed = False

        async def put(self, object_key, data, *, media_type):
            self.entered.set()
            await self.resume.wait()
            return await super().put(object_key, data, media_type=media_type)

        async def delete(self, object_key):
            if object_key in self._objects and not self.failed:
                self.failed = True
                raise OSError("late blob cleanup offline")
            await super().delete(object_key)

    now = module.utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    objects = LatePut()
    store = InMemoryArtifactStore(objects=objects)
    record = await store.create_staging(
        replace(
            request_for(),
            source_kind="voice_session_recording",
            retention_until=now + timedelta(days=7),
        )
    )
    upload = asyncio.create_task(store.upload(record.artifact_id, b"voice-data"))
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        now += timedelta(days=7)
        await store.reconcile_cleanup_ledger()
    finally:
        objects.resume.set()
    with pytest.raises((ArtifactConflict, OSError)):
        await upload
    assert len(objects._objects) == 1
    await store.reconcile_cleanup_ledger()
    assert objects._objects == {}
    assert (await store.get_record(record.artifact_id)).phase is ArtifactPhase.DELETED


@pytest.mark.asyncio
async def test_cancelled_sdk_upload_keeps_actual_worker_owned_until_exit(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    class SDK:
        def __init__(self):
            self.entered = threading.Event()
            self.resume = threading.Event()
            self.finished = threading.Event()
            self.objects = {}

        def put_object(self, **kwargs):
            self.entered.set()
            self.resume.wait(2)
            self.objects[kwargs["Key"]] = kwargs["Body"]
            self.finished.set()
            return {}

        def delete_object(self, **kwargs):
            self.objects.pop(kwargs["Key"], None)
            return {}

    now = module.utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    sdk = SDK()
    store = InMemoryArtifactStore(objects=Boto3S3ObjectClient(sdk, bucket="test"))
    record = await store.create_staging(
        replace(
            request_for(),
            source_kind="voice_session_recording",
            retention_until=now + timedelta(days=7),
        )
    )
    upload = asyncio.create_task(store.upload(record.artifact_id, b"voice-data"))
    try:
        assert await asyncio.to_thread(sdk.entered.wait, 1)
        upload.cancel()
        with pytest.raises(asyncio.CancelledError):
            await upload
        now += timedelta(days=7)
        first = await store.reconcile_cleanup_ledger()
        assert first["artifacts_cleaned"] == 0
        assert (await store.get_record(record.artifact_id)).phase is ArtifactPhase.DELETING
    finally:
        sdk.resume.set()
    assert await asyncio.to_thread(sdk.finished.wait, 1)
    await asyncio.gather(*store._upload_owner.tasks, return_exceptions=True)
    await store.reconcile_cleanup_ledger()
    assert sdk.objects == {}
    assert (await store.get_record(record.artifact_id)).phase is ArtifactPhase.DELETED
    assert not store._upload_owner.tasks


@pytest.mark.asyncio
async def test_failed_oldest_recording_does_not_starve_another_expired_recording(
    monkeypatch,
) -> None:
    import server.artifacts.in_memory as module

    class SelectiveFailure(InMemoryS3ObjectClient):
        bad_key = None

        async def delete(self, object_key):
            if object_key == self.bad_key:
                raise OSError("permanent deletion failure")
            await super().delete(object_key)

    now = module.utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    objects = SelectiveFailure()
    store = InMemoryArtifactStore(objects=objects)
    records = []
    for key in ["bad", "good"]:
        record = await store.create_staging(
            replace(
                request_for(),
                source_kind="voice_session_recording",
                idempotency_key=key,
                retention_until=now + timedelta(days=7),
            )
        )
        await store.upload(record.artifact_id, b"voice-data")
        records.append(await store.finalize(record.artifact_id))
        now += timedelta(seconds=1)
    objects.bad_key = records[0].receipt.object_key
    now += timedelta(days=7)
    assert (await store.reconcile_cleanup_ledger(limit=1))["artifacts_cleaned"] == 0
    assert (await store.reconcile_cleanup_ledger(limit=1))["artifacts_cleaned"] == 1
    assert (await store.get_record(records[1].artifact_id)).phase is ArtifactPhase.DELETED
    assert (await store.get_record(records[0].artifact_id)).phase is ArtifactPhase.DELETING


@pytest.mark.asyncio
async def test_cancelled_uploads_keep_capacity_until_actual_exit() -> None:
    class PausedPut(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.count = 0
            self.all_entered = asyncio.Event()
            self.resume = asyncio.Event()

        async def put(self, object_key, data, *, media_type):
            self.count += 1
            if self.count == 64:
                self.all_entered.set()
            await self.resume.wait()
            return await super().put(object_key, data, media_type=media_type)

    objects = PausedPut()
    store = InMemoryArtifactStore(objects=objects)
    record = await store.create_staging(request_for())
    callers = [
        asyncio.create_task(store.upload(record.artifact_id, b"voice-data")) for _ in range(64)
    ]
    try:
        await asyncio.wait_for(objects.all_entered.wait(), 1)
        for caller in callers:
            caller.cancel()
        await asyncio.gather(*callers, return_exceptions=True)
        assert len(store._upload_owner.tasks) == 64
        with pytest.raises(ArtifactConflict, match="capacity"):
            await store.upload(record.artifact_id, b"voice-data")
    finally:
        objects.resume.set()
        await asyncio.gather(*callers, return_exceptions=True)
        await asyncio.gather(*store._upload_owner.tasks, return_exceptions=True)
    assert not store._upload_owner.tasks
    assert len(objects._objects) == 1


@pytest.mark.asyncio
async def test_pin_after_recording_scan_does_not_record_a_false_failure(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    class PausedFirstDelete(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.resume = asyncio.Event()
            self.first = True

        async def delete(self, object_key):
            if self.first:
                self.first = False
                self.entered.set()
                await self.resume.wait()
            await super().delete(object_key)

    now = module.utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    objects = PausedFirstDelete()
    store = InMemoryArtifactStore(objects=objects)
    records = []
    for key in ["first", "second"]:
        record = await store.create_staging(
            replace(
                request_for(),
                source_kind="voice_session_recording",
                idempotency_key=key,
                retention_until=now + timedelta(days=7),
            )
        )
        await store.upload(record.artifact_id, b"voice-data")
        records.append(await store.finalize(record.artifact_id))
        now += timedelta(seconds=1)
    now += timedelta(days=7)
    cleanup = asyncio.create_task(store.reconcile_cleanup_ledger())
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        await store.pin_for(ArtifactAccessScope("tenant-1", "user-1"), records[1].artifact_id)
    finally:
        objects.resume.set()
        await cleanup
    pinned = await store.get_record(records[1].artifact_id)
    assert pinned.request.immutable
    assert pinned.failure_reason is None
    assert await store.read(records[1].artifact_id) == b"voice-data"


@pytest.mark.asyncio
async def test_failed_orphan_does_not_starve_other_late_upload_cleanup(monkeypatch) -> None:
    import server.artifacts.in_memory as module

    class LatePuts(InMemoryS3ObjectClient):
        def __init__(self):
            super().__init__()
            self.count = 0
            self.bad_key = None
            self.failed_once = set()
            self.entered = asyncio.Event()
            self.resume = asyncio.Event()

        async def put(self, object_key, data, *, media_type):
            self.count += 1
            if self.count == 1:
                self.bad_key = object_key
            if self.count == 2:
                self.entered.set()
            await self.resume.wait()
            return await super().put(object_key, data, media_type=media_type)

        async def delete(self, object_key):
            if object_key == self.bad_key:
                raise OSError("permanent orphan deletion failure")
            if object_key in self._objects and object_key not in self.failed_once:
                self.failed_once.add(object_key)
                raise OSError("temporary orphan deletion failure")
            await super().delete(object_key)

    now = module.utc_now()
    monkeypatch.setattr(module, "utc_now", lambda: now)
    objects = LatePuts()
    store = InMemoryArtifactStore(objects=objects)
    records = []
    for key in ["bad", "good"]:
        records.append(
            await store.create_staging(
                replace(
                    request_for(),
                    source_kind="voice_session_recording",
                    idempotency_key=key,
                    retention_until=now + timedelta(days=7),
                )
            )
        )
        now += timedelta(seconds=1)
    callers = [
        asyncio.create_task(store.upload(record.artifact_id, b"voice-data")) for record in records
    ]
    try:
        await asyncio.wait_for(objects.entered.wait(), 1)
        now += timedelta(days=7)
        await store.reconcile_cleanup_ledger()
    finally:
        objects.resume.set()
        await asyncio.gather(*callers, return_exceptions=True)
    assert len(objects._objects) == 2
    assert (await store.reconcile_cleanup_ledger(limit=1))["upload_attempts_cleaned"] == 0
    assert (await store.reconcile_cleanup_ledger(limit=1))["upload_attempts_cleaned"] == 1
    assert len(objects._objects) == 1
    assert (await store.get_record(records[1].artifact_id)).phase is ArtifactPhase.DELETED
