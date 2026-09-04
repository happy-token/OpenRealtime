"""Text projection for acoustic echo captured during assistant playback."""

from __future__ import annotations


def _normalized_with_raw_ends(text: str) -> tuple[str, tuple[int, ...]]:
    normalized: list[str] = []
    raw_ends: list[int] = []
    for index, character in enumerate(text):
        if not character.isalnum():
            continue
        folded = character.casefold()
        normalized.extend(folded)
        raw_ends.extend([index + 1] * len(folded))
    return "".join(normalized), tuple(raw_ends)


def project_assistant_echo(
    transcript: str,
    assistant_text: str,
    *,
    minimum_match_chars: int = 6,
) -> str | None:
    """Remove a playback-echo prefix; return ``None`` for echo-only text.

    ASR commonly misses the first few assistant syllables, so matching accepts
    a sufficiently long suffix of the assistant utterance at the beginning of
    the captured transcript. Unrelated user speech is returned unchanged.
    """

    candidate, raw_ends = _normalized_with_raw_ends(transcript)
    assistant, _ = _normalized_with_raw_ends(assistant_text)
    if len(candidate) < minimum_match_chars or len(assistant) < minimum_match_chars:
        return transcript

    if candidate in assistant:
        return None

    for start in range(len(assistant) - minimum_match_chars + 1):
        suffix = assistant[start:]
        if len(suffix) < minimum_match_chars or not candidate.startswith(suffix):
            continue
        raw_end = raw_ends[len(suffix) - 1]
        remainder = transcript[raw_end:].lstrip(" ，。！？、,.!?：:；;-")
        return remainder or None
    return transcript
