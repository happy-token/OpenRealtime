"""Trusted Persona prompt files linked to a selected Avatar.

Persona remains independent from the Avatar aggregate.  This module resolves
an explicit Avatar-to-Persona link and projects the Persona's role files into
the Brain system prompt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


PERSONA_PROMPT_FILENAMES = ("AGENTS.md", "SOUL.md", "IDENTITY.md")
REQUIRED_PERSONA_FILENAMES = frozenset(("SOUL.md", "IDENTITY.md"))
MAX_PERSONA_FILE_CHARS = 8_000
MAX_PERSONA_PROMPT_CHARS = 16_000
_AVATAR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
_PERSONA_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


@dataclass(frozen=True)
class AvatarPersonaLink:
    persona_id: str
    avatar_display_name: str


class AvatarPersonaPromptCatalog:
    """Resolve one selected Avatar into one bounded, trusted Persona prompt."""

    def __init__(self, *, persona_root: Path, links_path: Path) -> None:
        self._persona_root = persona_root
        self._links_path = links_path

    def system_prompt_for_avatar(self, avatar_id: str, base_prompt: str) -> str:
        resolved = self.resolve(avatar_id)
        if not resolved:
            return base_prompt
        _, context = resolved
        return f"{base_prompt}\n\n{context}"

    def resolve(self, avatar_id: str) -> tuple[str, str] | None:
        """Load and validate the complete Persona selected by an Avatar."""

        link = self._link_for_avatar(avatar_id)
        if not link:
            return None
        return self.resolve_persona(link.persona_id, link.avatar_display_name)

    def resolve_persona(
        self,
        persona_id: str,
        display_name: str | None = None,
    ) -> tuple[str, str] | None:
        """Load one trusted Persona by ID for Avatar and conversation roles."""

        if not _PERSONA_ID.fullmatch(persona_id):
            raise ValueError("Persona ID is invalid")
        role_name = display_name.strip() if display_name is not None else None
        if role_name is not None and (
            not role_name or len(role_name) > 80 or "\n" in role_name or "\r" in role_name
        ):
            raise ValueError("Role display name is invalid")
        persona_dir = self._persona_root / persona_id
        files: list[tuple[str, str]] = []
        total_chars = 0
        for filename in PERSONA_PROMPT_FILENAMES:
            path = persona_dir / filename
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8").strip()
            if len(content) > MAX_PERSONA_FILE_CHARS:
                raise ValueError(f"Persona file is too large: {filename}")
            total_chars += len(content)
            if total_chars > MAX_PERSONA_PROMPT_CHARS:
                raise ValueError("Persona prompt is too large")
            files.append((filename, content))
        if not files:
            return None
        missing_required = REQUIRED_PERSONA_FILENAMES.difference(
            filename for filename, _ in files
        )
        if missing_required:
            raise ValueError(
                f"Persona is missing required files: {', '.join(sorted(missing_required))}"
            )
        rendered = "\n\n".join(
            f"## {filename}\n\n{content}" for filename, content in files if content
        )
        if not rendered:
            return None
        identity_context = (
            "# Role Context\n"
            f"The selected role's display name is {role_name}. "
            "Use this name when introducing yourself; the Persona remains a reusable style asset.\n\n"
            if role_name is not None else ""
        )
        context = (
            f"{identity_context}# Persona Context\n"
            "The following trusted Persona files are linked to the selected Avatar.\n\n"
            f"{rendered}"
        )
        return persona_id, context

    def _link_for_avatar(self, avatar_id: str) -> AvatarPersonaLink | None:
        if not _AVATAR_ID.fullmatch(avatar_id):
            raise ValueError("Avatar ID is invalid")
        try:
            payload = json.loads(self._links_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(payload, dict) or payload.get("version") != 2:
            raise ValueError("Avatar Persona link catalog version is invalid")
        links = payload.get("links")
        if not isinstance(links, dict):
            raise ValueError("Avatar Persona links are invalid")
        raw_link = links.get(avatar_id)
        if raw_link is None:
            return None
        if not isinstance(raw_link, dict):
            raise ValueError("Avatar Persona link is invalid")
        persona_id = raw_link.get("personaId")
        avatar_display_name = raw_link.get("avatarDisplayName")
        if not isinstance(persona_id, str) or not _PERSONA_ID.fullmatch(persona_id):
            raise ValueError("Persona ID is invalid")
        if (
            not isinstance(avatar_display_name, str)
            or not avatar_display_name.strip()
            or len(avatar_display_name) > 80
            or "\n" in avatar_display_name
            or "\r" in avatar_display_name
        ):
            raise ValueError("Avatar display name is invalid")
        return AvatarPersonaLink(
            persona_id=persona_id,
            avatar_display_name=avatar_display_name.strip(),
        )


class SessionAvatarPersona:
    """Mutable session selection with one prompt projection interface."""

    def __init__(self, catalog: AvatarPersonaPromptCatalog) -> None:
        self._catalog = catalog
        self._avatar_id: str | None = None
        self._persona_context: str | None = None

    def select_avatar(self, avatar_id: str | None) -> str | None:
        return self.select(avatar_id=avatar_id)

    def select(
        self,
        *,
        avatar_id: str | None = None,
        persona_id: str | None = None,
    ) -> str | None:
        self._avatar_id = None
        self._persona_context = None
        if persona_id is not None:
            resolved = self._catalog.resolve_persona(persona_id)
        elif avatar_id is not None:
            resolved = self._catalog.resolve(avatar_id)
        else:
            return None
        if resolved is None:
            return None
        selected_persona_id, context = resolved
        self._avatar_id = avatar_id or f"persona:{selected_persona_id}"
        self._persona_context = context
        return selected_persona_id

    def apply(self, base_prompt: str) -> str:
        if self._avatar_id is None or self._persona_context is None:
            return base_prompt
        return f"{base_prompt}\n\n{self._persona_context}"
