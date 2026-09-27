from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from server.voice_session.public_admission import PublicVoiceTicketAuthenticator


@pytest.mark.asyncio
async def test_selected_instance_is_decrypted_and_bound_to_the_admitted_capability(monkeypatch) -> None:
    key = b"k" * 32
    monkeypatch.setenv("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(key).decode().rstrip("="))
    monkeypatch.setenv("VOICEAGENT_PUBLIC_ORIGIN", "https://app.test")
    monkeypatch.setenv("VOICEAGENT_POSTGRES_DSN", "postgresql://unused")
    instance_id = "c8135c1c-7989-4a04-aac8-a759ed98213b"
    version = "48ff0333-901c-493a-9766-54a7284cfbd2"
    iv = os.urandom(12)
    aad = json.dumps(["provider_instance", "personal", "issuer", "subject", instance_id],
                     separators=(",", ":")).encode()
    sealed = iv + AESGCM(key).encrypt(iv, b"instance-key", aad)
    admission = {
        "issuer": "issuer", "subject": "subject", "guest_id": None,
        "asr_provider": "doubao", "asr_source": "platform",
        "tts_provider": "doubao", "tts_source": "platform",
        "llm_provider": "openai", "llm_source": "personal",
        "credential_versions": {},
        "provider_instances": {"llm": {"id": instance_id, "scope": "personal", "version": version,
                                      "provider": "openai", "model": "gpt-test"}},
        "deadline_at": datetime.now(UTC),
    }
    instance = {
        "scope": "personal", "issuer": "issuer", "subject": "subject",
        "capability": "llm", "provider": "openai", "model": "gpt-test", "base_url": None,
        "sealed_key": sealed,
    }
    connection = AsyncMock()

    async def fetchrow(query, *args):
        if '"voice_admissions"' in query:
            return admission
        if '"provider_instances"' in query:
            assert args == (instance_id, version)
            return instance
        raise AssertionError(query)

    connection.fetchrow.side_effect = fetchrow
    monkeypatch.setattr("server.voice_session.public_admission.asyncpg.connect", AsyncMock(return_value=connection))
    identity = await PublicVoiceTicketAuthenticator().authenticate(
        {"Origin": "https://app.test"}, "/?admission=" + "x" * 43,
    )
    assert identity is not None
    assert identity.admission.instance_credentials == {"llm": "instance-key"}
    assert identity.admission.instance_models == {"llm": "gpt-test"}
    assert identity.admission.instance_ids == {"llm": instance_id}
    assert identity.admission.instance_versions == {"llm": version}


@pytest.mark.asyncio
async def test_cross_user_instance_binding_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("VOICEAGENT_PUBLIC_ORIGIN", "https://app.test")
    monkeypatch.setenv("VOICEAGENT_POSTGRES_DSN", "postgresql://unused")
    connection = AsyncMock()
    connection.fetchrow.side_effect = [
        {"issuer": "issuer", "subject": "subject", "guest_id": None,
         "asr_provider": "doubao", "asr_source": "platform",
         "tts_provider": "doubao", "tts_source": "platform",
         "llm_provider": "openai", "llm_source": "personal",
         "credential_versions": {},
         "provider_instances": {"llm": {"id": "c8135c1c-7989-4a04-aac8-a759ed98213b",
                                        "version": "48ff0333-901c-493a-9766-54a7284cfbd2"}},
         "deadline_at": None},
        {"scope": "personal", "issuer": "issuer", "subject": "someone-else",
         "capability": "llm", "provider": "openai", "model": "", "sealed_key": b""},
    ]
    monkeypatch.setattr("server.voice_session.public_admission.asyncpg.connect", AsyncMock(return_value=connection))
    identity = await PublicVoiceTicketAuthenticator().authenticate(
        {"Origin": "https://app.test"}, "/?admission=" + "x" * 43,
    )
    assert identity is None
