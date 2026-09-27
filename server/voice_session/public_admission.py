"""Verify short-lived public voice tickets and keep their PostgreSQL lease alive."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import asyncpg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from server.endpoint_session.in_memory_session import InMemoryEndpointSession
from server.transport.base import AuthenticatedTransportIdentity
from server.voice_session.protocol import VoiceSessionFailureFrame

logger = logging.getLogger(__name__)
_TICKET = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
_SCHEMA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _table(name: str) -> str:
    schema = os.environ.get("VOICEAGENT_POSTGRES_SCHEMA", "voiceagent")
    if not _SCHEMA.fullmatch(schema):
        raise ValueError("invalid PostgreSQL schema")
    return f'"{schema}"."{name}"'


def _dsn() -> str:
    value = os.environ.get("VOICEAGENT_POSTGRES_DSN")
    if not value:
        raise RuntimeError("public voice requires VOICEAGENT_POSTGRES_DSN")
    return value


def _encryption_key() -> bytes:
    encoded = os.environ.get("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", "")
    try:
        value = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise RuntimeError("invalid personal credential encryption key") from error
    if len(value) != 32 or base64.urlsafe_b64encode(value).decode().rstrip("=") != encoded.rstrip("="):
        raise RuntimeError("invalid personal credential encryption key")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class VoiceAdmissionBinding:
    ticket_hash: str
    user_id: str
    asr_provider: str
    asr_source: str
    tts_provider: str
    tts_source: str
    llm_provider: str
    llm_source: str
    credentials: dict[str, str]
    instance_credentials: dict[str, str]
    instance_models: dict[str, str]
    instance_base_urls: dict[str, str]
    instance_ids: dict[str, str]
    instance_versions: dict[str, str]
    deadline: datetime | None


class PublicVoiceTicketAuthenticator:
    async def authenticate(
        self, headers: Mapping[str, str], path: str = "/"
    ) -> AuthenticatedTransportIdentity | None:
        configured_origin = os.environ.get("VOICEAGENT_PUBLIC_ORIGIN")
        origin = next((value for key, value in headers.items() if key.lower() == "origin"), None)
        if not configured_origin or origin != configured_origin.rstrip("/"):
            return None
        ticket = parse_qs(urlsplit(path).query).get("admission", [None])[0]
        if not isinstance(ticket, str) or not _TICKET.fullmatch(ticket):
            return None
        token_hash = hashlib.sha256(ticket.encode()).hexdigest()
        try:
            connection = await asyncpg.connect(_dsn())
        except Exception:  # noqa: BLE001 - fail closed for every database connection failure
            logger.error("public voice ticket database is unavailable")
            return None
        try:
            row = await connection.fetchrow(
                f"SELECT * FROM {_table('voice_admissions')} WHERE ticket_hash = $1 "
                "AND ended_at IS NULL AND revoked_at IS NULL AND expires_at > now() "
                "AND (bound_session_id IS NOT NULL OR connect_by > now())",
                token_hash,
            )
            if row is None:
                return None
            versions = row["credential_versions"]
            if isinstance(versions, str):
                versions = json.loads(versions)
            credentials: dict[str, str] = {}
            if row["issuer"] is not None:
                for provider, version in versions.items():
                    key_row = await connection.fetchrow(
                        f"SELECT sealed_key FROM {_table('user_provider_credentials')} "
                        "WHERE issuer = $1 AND subject = $2 AND provider = $3 "
                        "AND key_version = $4::uuid",
                        row["issuer"], row["subject"], provider, version,
                    )
                    if key_row is None:
                        return None
                    sealed = bytes(key_row["sealed_key"])
                    associated = json.dumps(
                        [row["issuer"], row["subject"], provider],
                        separators=(",", ":"), ensure_ascii=False,
                    ).encode()
                    credentials[provider] = AESGCM(_encryption_key()).decrypt(
                        sealed[:12], sealed[12:], associated,
                    ).decode()
            instance_credentials: dict[str, str] = {}
            instance_models: dict[str, str] = {}
            instance_base_urls: dict[str, str] = {}
            instance_ids: dict[str, str] = {}
            instance_versions: dict[str, str] = {}
            instance_bindings = row["provider_instances"]
            if isinstance(instance_bindings, str):
                instance_bindings = json.loads(instance_bindings)
            if not isinstance(instance_bindings, dict):
                return None
            for capability, entry in instance_bindings.items():
                if capability not in {"asr", "tts", "llm"} or not isinstance(entry, dict):
                    return None
                instance_id = entry.get("id")
                version = entry.get("version")
                if not isinstance(instance_id, str) or not isinstance(version, str):
                    return None
                instance_row = await connection.fetchrow(
                    f"SELECT scope, issuer, subject, capability, provider, model, base_url, sealed_key "
                    f"FROM {_table('provider_instances')} "
                    "WHERE id = $1::uuid AND key_version = $2::uuid AND enabled",
                    instance_id, version,
                )
                if instance_row is None or instance_row["capability"] != capability \
                        or instance_row["provider"] != row[f"{capability}_provider"] \
                        or instance_row["scope"] != row[f"{capability}_source"]:
                    return None
                scope = instance_row["scope"]
                issuer = instance_row["issuer"]
                subject = instance_row["subject"]
                if scope == "personal" and (issuer != row["issuer"] or subject != row["subject"]):
                    return None
                if scope == "platform" and (issuer or subject):
                    return None
                associated = json.dumps(
                    ["provider_instance", scope, issuer, subject, instance_id],
                    separators=(",", ":"), ensure_ascii=False,
                ).encode()
                sealed = bytes(instance_row["sealed_key"])
                instance_credentials[capability] = AESGCM(_encryption_key()).decrypt(
                    sealed[:12], sealed[12:], associated,
                ).decode()
                instance_models[capability] = instance_row["model"]
                instance_base_urls[capability] = instance_row["base_url"]
                instance_ids[capability] = instance_id
                instance_versions[capability] = version
            user_id = (f"{row['issuer']}#{row['subject']}" if row["subject"] is not None
                       else f"guest:{row['guest_id']}")
            binding = VoiceAdmissionBinding(
                ticket_hash=token_hash,
                user_id=user_id,
                asr_provider=row["asr_provider"],
                asr_source=row["asr_source"],
                tts_provider=row["tts_provider"],
                tts_source=row["tts_source"],
                llm_provider=row["llm_provider"],
                llm_source=row["llm_source"],
                credentials=credentials,
                instance_credentials=instance_credentials,
                instance_models=instance_models,
                instance_base_urls=instance_base_urls,
                instance_ids=instance_ids,
                instance_versions=instance_versions,
                deadline=row["deadline_at"],
            )
            return AuthenticatedTransportIdentity(
                tenant_id="public", user_id=user_id, device_id="browser",
                admission=binding,
            )
        except Exception:
            logger.exception("public voice ticket verification failed")
            return None
        finally:
            await connection.close()


async def admit_fresh_public_session(
    session: InMemoryEndpointSession,
    identity: AuthenticatedTransportIdentity,
) -> bool:
    binding = identity.admission
    if binding is None:
        return False
    connection = await asyncpg.connect(_dsn())
    try:
        row = await connection.fetchrow(
            f"UPDATE {_table('voice_admissions')} SET bound_session_id = $2::uuid "
            "WHERE ticket_hash = $1 AND bound_session_id IS NULL "
            "AND connect_by > now() AND expires_at > now() "
            "AND ended_at IS NULL AND revoked_at IS NULL RETURNING ticket_hash",
            binding.ticket_hash, session.session_id,
        )
        if row is None:
            return False
    finally:
        await connection.close()
    asyncio.create_task(_monitor_public_session(session, binding))
    return True


async def _monitor_public_session(
    session: InMemoryEndpointSession,
    binding: VoiceAdmissionBinding,
) -> None:
    warned = False
    try:
        while True:
            closed = asyncio.create_task(session.wait_until_closed())
            try:
                await asyncio.wait_for(closed, timeout=2.0)
                return
            except TimeoutError:
                pass
            finally:
                closed.cancel()
            connection = await asyncpg.connect(_dsn())
            try:
                row = await connection.fetchrow(
                    f"SELECT revoked_at, expires_at FROM {_table('voice_admissions')} "
                    "WHERE ticket_hash = $1 AND ended_at IS NULL",
                    binding.ticket_hash,
                )
                if binding.deadline is None and row is not None:
                    await connection.execute(
                        f"UPDATE {_table('voice_admissions')} "
                        "SET expires_at = now() + interval '2 minutes' "
                        "WHERE ticket_hash = $1 AND revoked_at IS NULL AND ended_at IS NULL",
                        binding.ticket_hash,
                    )
            finally:
                await connection.close()
            if row is None or row["revoked_at"] is not None:
                await session.send(VoiceSessionFailureFrame(
                    code="authentication_failed", phase="active", retryable=False,
                    session_disposition="close",
                    safe_message="你的 API Key 已更换或清空，请重新开始语音会话。",
                ))
                await session.close()
                return
            if binding.deadline is not None:
                remaining = (binding.deadline - datetime.now(UTC)).total_seconds()
                if remaining <= 0:
                    await session.send(VoiceSessionFailureFrame(
                        code="session_limit_reached", phase="active", retryable=False,
                        session_disposition="close",
                        safe_message="本次平台语音体验已到时。对话记录已保留，可以重新开始。",
                    ))
                    await session.close()
                    return
                if remaining <= 30 and not warned:
                    warned = True
                    await session.send(VoiceSessionFailureFrame(
                        code="session_limit_approaching", phase="active", retryable=True,
                        session_disposition="keep_reconnecting",
                        safe_message="平台语音体验将在 30 秒内结束。",
                    ))
    except Exception:
        logger.exception("public voice admission monitor failed")
        await session.close()
    finally:
        try:
            connection = await asyncpg.connect(_dsn())
            try:
                await connection.execute(
                    f"UPDATE {_table('voice_admissions')} SET ended_at = now() "
                    "WHERE ticket_hash = $1 AND ended_at IS NULL",
                    binding.ticket_hash,
                )
            finally:
                await connection.close()
        except Exception:
            logger.exception("could not release public voice admission")
