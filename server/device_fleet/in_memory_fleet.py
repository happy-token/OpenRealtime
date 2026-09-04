"""Deterministic reference implementation of the Device Fleet contract.

InMemoryDeviceFleet is the "EchoLlmClient of Device Fleet" — a no-network,
single-process, test/demo-controllable stand-in, not a real backend
integration. No persistence and no real OTA delivery: firmware-update
availability is answered from a version string configured at construction
time, never fetched from anywhere.
"""

from __future__ import annotations

from server.device_fleet.protocol import ActivationResult, DeviceRecord, FirmwareCheckResult


class InMemoryDeviceFleet:
    def __init__(
        self, *, latest_firmware_version: str | None = None, download_url: str | None = None
    ) -> None:
        self._latest_firmware_version = latest_firmware_version
        self._download_url = download_url
        self._activated_device_ids: list[str] = []

    async def activate(self, device_id: str, activation_code: str) -> ActivationResult:
        if not activation_code:
            return ActivationResult(ok=False, error="missing activation code")
        self._activated_device_ids.append(device_id)
        return ActivationResult(ok=True)

    async def check_firmware(self, device_id: str, current_version: str) -> FirmwareCheckResult:
        if self._latest_firmware_version is None or current_version == self._latest_firmware_version:
            return FirmwareCheckResult(update_available=False)
        return FirmwareCheckResult(
            update_available=True,
            latest_version=self._latest_firmware_version,
            download_url=self._download_url,
        )

    async def list_devices(self) -> list[DeviceRecord]:
        return [DeviceRecord(device_id=device_id, activated=True) for device_id in self._activated_device_ids]
