"""VisionSource: an optional signal source attaching vision content to Turn
Content.

See CONTEXT.md — Turn Content. Vision is content on the Turn Content bundle,
never a Turn Policy input signal — the result is attached to
TurnContent.vision_text and never gates any Turn Policy transition or blocks
a turn. Unregistered (default) behavior contributes no vision content at
all.
"""

from __future__ import annotations

from typing import Protocol


class VisionSource(Protocol):
    async def describe(self, *, generation: int) -> str | None: ...


class NoVisionSource:
    async def describe(self, *, generation: int) -> str | None:
        return None
