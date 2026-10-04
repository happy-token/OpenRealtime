"""User-scoped settings shared with the web control plane; read for every new call."""

from __future__ import annotations

import json
import logging
import os
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class ToolPermissionMode(StrEnum):
    FULL = "full"
    BALANCED = "balanced"
    CONFIRM = "confirm"


def tool_permission_mode(
    owner_id: str, role_id: str | None = None, *, root: Path | None = None
) -> ToolPermissionMode:
    directory = root or Path(
        os.environ.get("VOICEAGENT_TOOL_PERMISSIONS_DIR", ".openrealtime/tool-permissions")
    )
    try:
        payload = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or not isinstance(payload.get("records"), list)
        ):
            raise ValueError("invalid tool permissions catalog")
        owners: set[str] = set()
        for entry in payload["records"]:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("owner_id"), str)
                or not entry["owner_id"]
                or entry["owner_id"] in owners
            ):
                raise ValueError("invalid tool permission owner")
            owners.add(entry["owner_id"])
            ToolPermissionMode(entry["mode"])
            if not isinstance(entry.get("role_overrides"), dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in entry["role_overrides"].items()
            ):
                raise ValueError("invalid tool permission overrides")
            for value in entry["role_overrides"].values():
                ToolPermissionMode(value)
        matches = [
            record
            for record in payload["records"]
            if isinstance(record, dict) and record.get("owner_id") == owner_id
        ]
        if len(matches) > 1:
            raise ValueError("duplicate tool permissions owner")
        if not matches:
            return ToolPermissionMode.FULL
        record = matches[0]
        overrides = record.get("role_overrides")
        if not isinstance(overrides, dict):
            raise TypeError("invalid role permission overrides")
        mode = ToolPermissionMode(record["mode"])
        if role_id is not None and role_id in overrides:
            mode = ToolPermissionMode(overrides[role_id])
        return mode
    except FileNotFoundError:
        return ToolPermissionMode.FULL
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning(
            "Tool permission settings unavailable; requiring confirmation", exc_info=True
        )
        return ToolPermissionMode.CONFIRM
