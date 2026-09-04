"""Environment composition for the S3-compatible object-store adapter."""

from __future__ import annotations

import os
from collections.abc import Mapping

from server.artifacts.s3_client import Boto3S3ObjectClient


def build_s3_object_client_from_env(
    environ: Mapping[str, str] | None = None,
) -> Boto3S3ObjectClient:
    values = os.environ if environ is None else environ
    required = {
        "S3_ENDPOINT_URL": values.get("S3_ENDPOINT_URL", "").strip(),
        "S3_BUCKET": values.get("S3_BUCKET", "").strip(),
        "S3_AK": values.get("S3_AK", "").strip(),
        "S3_SK": values.get("S3_SK", "").strip(),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise ValueError("S3-compatible object store requires: " + ", ".join(missing))
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "S3-compatible object storage requires the 'object-store' optional dependency"
        ) from error
    client = boto3.client(
        "s3",
        endpoint_url=required["S3_ENDPOINT_URL"],
        aws_access_key_id=required["S3_AK"],
        aws_secret_access_key=required["S3_SK"],
        region_name=values.get("S3_REGION", "auto").strip() or "auto",
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    return Boto3S3ObjectClient(
        client,
        bucket=required["S3_BUCKET"],
        prefix=values.get("S3_PREFIX", "openrealtime/").strip() or "openrealtime/",
    )
