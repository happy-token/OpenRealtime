"""Private write proof issued only after the public application admin gate."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import time


def verify_preservation_proof(session_id: str, body: bytes, timestamp: str, signature: str) -> bool:
    encoded = os.environ.get("VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY", "")
    try:
        root = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if (
            len(root) != 32
            or base64.urlsafe_b64encode(root).decode().rstrip("=") != encoded.rstrip("=")
            or not re.fullmatch(r"[1-9][0-9]{0,11}", timestamp)
            or abs(time.time() - int(timestamp)) > 60
            or not re.fullmatch(r"[a-f0-9]{64}", signature)
        ):
            return False
        key = hmac.new(
            root, b"openrealtime/session-recording-preservation/key/v1", hashlib.sha256
        ).digest()
        message = (
            b"session-recording-preservation-v1\x00"
            + timestamp.encode()
            + b"\x00"
            + session_id.encode()
            + b"\x00"
            + body
        )
        return hmac.compare_digest(signature, hmac.new(key, message, hashlib.sha256).hexdigest())
    except (ValueError, binascii.Error):
        return False
