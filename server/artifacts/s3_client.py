"""S3-compatible object client adapter.

The injected client may be boto3, MinIO-compatible, or another implementation
with the same object methods. SDK imports stay outside the domain layer.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from server.artifacts.protocol import BlobReceipt, S3ObjectClient


class Boto3S3ObjectClient(S3ObjectClient):
    def __init__(self, client: Any, *, bucket: str, prefix: str = "voiceagent/") -> None:
        if not bucket:
            raise ValueError("S3 bucket must be non-empty")
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        if self._prefix:
            self._validate_segments(self._prefix, field="prefix")

    async def put(self, object_key: str, data: bytes, *, media_type: str) -> BlobReceipt:
        key = self._key(object_key)
        digest = hashlib.sha256(data).hexdigest()
        response = await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
            Metadata={"sha256": digest},
        )
        return BlobReceipt(
            object_key=object_key,
            size=len(data),
            sha256=digest,
            etag=_clean_etag(response.get("ETag")),
            version_id=response.get("VersionId"),
        )

    async def head(self, object_key: str) -> BlobReceipt | None:
        key = self._key(object_key)
        try:
            response = await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except Exception as error:
            response = getattr(error, "response", {})
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        metadata = response.get("Metadata", {})
        digest = metadata.get("sha256")
        if not isinstance(digest, str) or not _is_sha256(digest):
            raise ValueError("S3 object is missing verified sha256 metadata")
        return BlobReceipt(
            object_key=object_key,
            size=int(response["ContentLength"]),
            sha256=digest,
            etag=_clean_etag(response.get("ETag")),
            version_id=response.get("VersionId"),
        )

    async def get(self, object_key: str) -> bytes:
        response = await asyncio.to_thread(
            self._client.get_object, Bucket=self._bucket, Key=self._key(object_key)
        )
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self._bucket,
            Key=self._key(object_key),
        )

    def _key(self, object_key: str) -> str:
        if not object_key or "\\" in object_key:
            raise ValueError("S3 object_key must be a non-empty slash-separated key")
        suffix = object_key.lstrip("/")
        self._validate_segments(suffix, field="object_key")
        return f"{self._prefix}/{suffix}" if self._prefix else suffix

    @staticmethod
    def _validate_segments(value: str, *, field: str) -> None:
        if "\\" in value or any(
            segment in {"", ".", ".."} for segment in value.split("/")
        ):
            raise ValueError(f"S3 {field} contains an invalid path segment")


def _clean_etag(value: object) -> str | None:
    return value.strip('"') if isinstance(value, str) else None


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
