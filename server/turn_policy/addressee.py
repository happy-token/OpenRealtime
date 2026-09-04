"""AddresseeClassifier: the plugin interface gating τ1 and τ11.

See CONTEXT.md — AddresseeClassifier, and ADR-0004. Unregistered (default)
behavior treats all speech as addressed to the assistant — the conservative
default, since falsely ignoring real commands is worse than an unnecessary
LISTEN transition or a missed third-party filter.
"""

from __future__ import annotations

from typing import Protocol


class AddresseeClassifier(Protocol):
    async def is_addressed(self, *, generation: int) -> bool: ...


class DefaultAddresseeClassifier:
    async def is_addressed(self, *, generation: int) -> bool:
        return True
