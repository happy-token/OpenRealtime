"""Small session interface shared by typed cascaded capabilities."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

CommandT_contra = TypeVar("CommandT_contra", contravariant=True)
EventT_co = TypeVar("EventT_co", covariant=True)


class CapabilitySession(Protocol[CommandT_contra, EventT_co]):
    async def send(self, command: CommandT_contra) -> None: ...

    def events(self) -> AsyncIterator[EventT_co]: ...

    async def close(self) -> None: ...
