from __future__ import annotations

import os
import uuid

import pytest

from server.artifacts import build_s3_object_client_from_env

pytestmark = pytest.mark.skipif(
    os.getenv("VOICEAGENT_RUN_S3_INTEGRATION") != "1",
    reason="set VOICEAGENT_RUN_S3_INTEGRATION=1 for S3-compatible object-store tests",
)


@pytest.mark.asyncio
async def test_private_object_store_round_trip_is_verified_and_recoverable() -> None:
    objects = build_s3_object_client_from_env()
    object_key = f"avatar-assets/integration-check/{uuid.uuid4()}.bin"
    data = b"openrealtime-avatar-object-store-check-v1"
    try:
        receipt = await objects.put(object_key, data, media_type="application/octet-stream")
        observed = await objects.head(object_key)

        assert observed == receipt
        assert await objects.get(object_key) == data
    finally:
        await objects.delete(object_key)
    assert await objects.head(object_key) is None
