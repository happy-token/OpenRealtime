from server.device_fleet.in_memory_fleet import InMemoryDeviceFleet
from server.device_fleet.protocol import DeviceRecord


async def test_activate_with_valid_code_registers_device():
    fleet = InMemoryDeviceFleet()

    result = await fleet.activate("device-1", "abc123")

    assert result.ok is True
    assert result.error is None
    assert await fleet.list_devices() == [DeviceRecord(device_id="device-1", activated=True)]


async def test_activate_with_empty_code_fails_and_device_not_listed():
    fleet = InMemoryDeviceFleet()

    result = await fleet.activate("device-1", "")

    assert result.ok is False
    assert result.error is not None
    assert await fleet.list_devices() == []


async def test_check_firmware_with_no_configured_latest_version_reports_no_update():
    fleet = InMemoryDeviceFleet()

    result = await fleet.check_firmware("device-1", "1.0.0")

    assert result.update_available is False
    assert result.latest_version is None
    assert result.download_url is None


async def test_check_firmware_when_current_matches_latest_reports_no_update():
    fleet = InMemoryDeviceFleet(latest_firmware_version="1.2.0")

    result = await fleet.check_firmware("device-1", "1.2.0")

    assert result.update_available is False


async def test_check_firmware_when_current_is_older_reports_update_available():
    fleet = InMemoryDeviceFleet(latest_firmware_version="1.2.0", download_url="https://example.com/fw.bin")

    result = await fleet.check_firmware("device-1", "1.0.0")

    assert result.update_available is True
    assert result.latest_version == "1.2.0"
    assert result.download_url == "https://example.com/fw.bin"


async def test_list_devices_on_fresh_fleet_is_empty():
    fleet = InMemoryDeviceFleet()

    assert await fleet.list_devices() == []


async def test_list_devices_reflects_multiple_activations_in_order():
    fleet = InMemoryDeviceFleet()

    await fleet.activate("device-1", "code-1")
    await fleet.activate("device-2", "code-2")

    devices = await fleet.list_devices()
    assert [d.device_id for d in devices] == ["device-1", "device-2"]
    assert all(d.activated for d in devices)
