"""TransportAdapter: the pluggable wire-protocol contract.

A single protocol-agnostic interface behind which Raw WebSocket, LiveKit/RTC,
MQTT, or raw UDP implementations can be swapped. See CONTEXT.md — Transport
Adapter.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from server.voice_session.public_admission import VoiceAdmissionBinding

from server.transport.frames import InboundFrame, OutboundFrame


class TransportDisconnected(ConnectionError):
    """The currently attached physical transport can no longer send frames."""


@dataclass(frozen=True, slots=True)
class AuthenticatedTransportIdentity:
    """Identity asserted by a trusted transport authenticator, never Client Hello."""

    tenant_id: str
    user_id: str
    device_id: str
    admission: VoiceAdmissionBinding | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.tenant_id, self.user_id, self.device_id)
        ):
            raise ValueError("authenticated transport identity fields must be non-empty")


class TransportAdapter(Protocol):
    def receive(self) -> AsyncIterator[InboundFrame]: ...

    async def send(self, frame: OutboundFrame) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ObservedFrameSender(Protocol):
    """Optional live-send seam: no buffering, guard inside physical send lock.

    on_sent means the adapter write returned, never device playback. The
    caller freezes frame provenance before yielding; reattach cannot relabel it.
    """

    async def send_observed(
        self, frame: OutboundFrame, *, expected_output_epoch: str,
        can_send: Callable[[], bool], on_admitted: Callable[[], None] | None,
        on_sent: Callable[[], None] | None,
    ) -> bool: ...
