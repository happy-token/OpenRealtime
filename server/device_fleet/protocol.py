"""Device Fleet: contract for device activation, firmware checks, and inventory.

See CONTEXT.md — Device Fleet, and ADR-0003. The wire protocol is a
Transport Adapter concern and device-side tool announcement is a Tool
Normalization concern (ADR-0001) — neither belongs here. This contract
covers only activation/firmware-check/inventory; see
device_fleet/in_memory_fleet.py for the framework's minimal reference
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ActivationResult:
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class FirmwareCheckResult:
    update_available: bool
    latest_version: str | None = None
    download_url: str | None = None


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    activated: bool


class DeviceFleet(Protocol):
    async def activate(self, device_id: str, activation_code: str) -> ActivationResult: ...
    async def check_firmware(self, device_id: str, current_version: str) -> FirmwareCheckResult: ...
    async def list_devices(self) -> list[DeviceRecord]: ...
