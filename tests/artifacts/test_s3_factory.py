from __future__ import annotations

import pytest

from server.artifacts.boto3_factory import build_s3_object_client_from_env


def test_s3_factory_requires_private_object_store_configuration() -> None:
    with pytest.raises(ValueError, match="S3_AK, S3_BUCKET, S3_ENDPOINT_URL, S3_SK"):
        build_s3_object_client_from_env({})
