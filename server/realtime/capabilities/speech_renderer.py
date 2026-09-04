"""Spoken-content resolution and deterministic display-text rendering."""

from __future__ import annotations

import re
from typing import Protocol

from server.conversation_journal import TextContent
from server.realtime.protocol.content import AssistantContent, SpokenContent


class SpeechRenderer(Protocol):
    async def render(self, content: AssistantContent) -> SpokenContent: ...


async def resolve_spoken_content(
    content: AssistantContent,
    *,
    renderer: SpeechRenderer,
) -> SpokenContent:
    """Use caller-authored speech verbatim; render only when it is absent."""

    if content.spoken is not None:
        return content.spoken
    return await renderer.render(content)


class DeterministicSpeechRenderer:
    """Formatting-only renderer; it never summarizes or calls a model."""

    async def render(self, content: AssistantContent) -> SpokenContent:
        if content.display is not None:
            text = _markdown_to_plain_text(content.display.markdown)
        else:
            text = "\n".join(
                part.text for part in content.semantic if isinstance(part, TextContent)
            ).strip()
        if not text:
            raise ValueError("assistant content has no deterministic spoken projection")
        return SpokenContent(text=text)


def _markdown_to_plain_text(markdown: str) -> str:
    text = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", markdown)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"```(?:[^\n]*)\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"(`{1,2}|\*{1,2}|_{1,2}|~~)(.+?)\1", r"\2", text)
    lines = (line.strip() for line in text.splitlines())
    return " ".join(line for line in lines if line)
