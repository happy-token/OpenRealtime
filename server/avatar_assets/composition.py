"""Environment composition for the durable Motion Base asset service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from server.artifacts import build_s3_object_client_from_env
from server.avatar_assets.acceptance import MotionBaseAcceptanceModule
from server.avatar_assets.http_api import AvatarAssetHttpApi
from server.avatar_assets.media_probe import FfprobeMediaProbe
from server.avatar_assets.rendition_module import MotionBaseRenditionModule
from server.avatar_assets.renditions import FfmpegRenditionEngine
from server.avatar_assets.service import AvatarAssetScope, AvatarAssetService
from server.persistence.postgres import PostgresArtifactStore, PostgresMotionBaseRegistry
from server.persistence.postgres.schema import apply_migrations, validate_schema_name


@dataclass(slots=True)
class AvatarAssetRuntime:
    api: AvatarAssetHttpApi
    pool: Any

    async def close(self) -> None:
        await self.pool.close()


async def build_avatar_asset_runtime_from_env(
    environ: Mapping[str, str] | None = None,
) -> AvatarAssetRuntime | None:
    values = os.environ if environ is None else environ
    if values.get("AVATAR_LOCAL_TEST_MODE", "").strip().lower() != "true":
        return None
    environment = values.get("VOICEAGENT_ENV", "development").strip().lower()
    if environment == "production":
        raise ValueError("AVATAR_LOCAL_TEST_MODE is forbidden in production")
    dsn = (
        values.get("AVATAR_ASSET_POSTGRES_DSN")
        or values.get("VOICEAGENT_POSTGRES_DSN")
        or "postgresql:///postgres?host=/tmp"
    )
    schema = validate_schema_name(
        values.get("AVATAR_ASSET_POSTGRES_SCHEMA", "voiceagent").strip()
    )
    try:
        import asyncpg
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Avatar assets require the 'postgres' optional dependency"
        ) from error
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        async with pool.acquire() as connection:
            await apply_migrations(connection, schema=schema)
        objects = build_s3_object_client_from_env(values)
        artifacts = PostgresArtifactStore(pool, objects=objects, schema=schema)
        registry = PostgresMotionBaseRegistry(pool, schema=schema)
        media_probe = FfprobeMediaProbe()
        acceptance = MotionBaseAcceptanceModule(
            registry=registry,
            artifacts=artifacts,
            media_probe=media_probe,
        )
        renditions = MotionBaseRenditionModule(
            registry=registry,
            artifacts=artifacts,
            engine=FfmpegRenditionEngine(),
        )
        service = AvatarAssetService(
            scope=AvatarAssetScope(
                tenant_id=values.get("VOICEAGENT_TENANT_ID", "local"),
                owner_id=values.get("VOICEAGENT_USER_ID", "local-user"),
                reviewer_id=values.get("VOICEAGENT_USER_ID", "local-user"),
            ),
            artifacts=artifacts,
            registry=registry,
            acceptance=acceptance,
            renditions=renditions,
            media_probe=media_probe,
        )
        return AvatarAssetRuntime(AvatarAssetHttpApi(service), pool)
    except Exception:
        await pool.close()
        raise
