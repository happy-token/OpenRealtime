"""Resolve a role's optional model ID from trusted catalogs for one voice user."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

_ROLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,119}$")


def role_model_id(user_id: str, role_id: str | None, *, shared_root: Path | None = None,
                  personal_root: Path | None = None) -> str | None:
    role = role_record(user_id, role_id, shared_root=shared_root, personal_root=personal_root)
    model_id = role.get("model_id") if role else None
    return model_id if isinstance(model_id, str) and _MODEL_ID.fullmatch(model_id) else None


def role_tool_ids(user_id: str, role_id: str | None, *, shared_root: Path | None = None,
                  personal_root: Path | None = None) -> set[str]:
    role = role_record(user_id, role_id, shared_root=shared_root, personal_root=personal_root)
    values = role.get("tool_ids") if role else None
    return {value for value in values if isinstance(value, str)} if isinstance(values, list) else set()


def role_record(user_id: str, role_id: str | None, *, shared_root: Path | None = None,
                personal_root: Path | None = None) -> dict | None:
    if not role_id or not _ROLE_ID.fullmatch(role_id):
        return None
    if role_id.startswith("hosted-avatar-"):
        root = Path(os.environ.get("HOSTED_AVATAR_SETTINGS_DIR") or ".openrealtime/hosted-avatar-settings")
        try:
            records = json.loads((root / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(records, list):
            return None
        avatar_id = role_id.removeprefix("hosted-avatar-")
        record = next((item for item in records if isinstance(item, dict)
                       and item.get("owner_id") == user_id and item.get("avatar_id") == avatar_id), None)
        return {"role_id": role_id, **record} if record else None
    if role_id.startswith("role-personal-"):
        if "#" not in user_id:
            return None
        issuer, subject = user_id.split("#", 1)
        digest = hashlib.sha256(f"{issuer}\0{subject}".encode()).hexdigest()
        root = personal_root or Path(os.environ.get("OPENREALTIME_PERSONAL_MOTION_PATH") or ".openrealtime/personal-motion")
        file = root / digest / "roles" / "catalog.json"
    else:
        root = shared_root or Path(os.environ.get("ROLE_CATALOG_DIR") or ".openrealtime/role-catalog")
        file = root / "roles.json"
    try:
        roles = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(roles, list):
        return None
    return next((value for value in roles if isinstance(value, dict)
                 and value.get("role_id") == role_id and not value.get("deleted_at")), None)
