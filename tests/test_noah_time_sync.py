from datetime import datetime
from types import SimpleNamespace

from grobro.ha.cleanup import (
    _clean_discovery_payload,
    _seconds_until_next_time_sync,
    _sync_noah_clocks,
)


def test_next_time_sync_targets_midnight_or_noon():
    morning = datetime(2026, 9, 5, 8, 30, 0)
    assert _seconds_until_next_time_sync(morning) == 3.5 * 60 * 60

    evening = datetime(2026, 9, 5, 20, 30, 0)
    assert _seconds_until_next_time_sync(evening) == 3.5 * 60 * 60


def test_legacy_noah_sync_alias_uses_family_wide_supported_clock_sync():
    calls = []
    client = SimpleNamespace(
        _config_cache={
            "0PVP50ZR175T00E8": object(),
            "QMN000BZP4N991ML": object(),
            "0HVRTEST": object(),
            "RAQTEST": object(),
        },
        on_config_command=lambda dev, reg, val: calls.append((dev, reg, val)),
    )

    synced = _sync_noah_clocks(client, datetime(2026, 9, 5, 12, 0, 0))

    assert synced == 3
    assert {dev for dev, _, _ in calls} == {
        "0PVP50ZR175T00E8",
        "QMN000BZP4N991ML",
        "0HVRTEST",
    }
    assert all(reg == 31 for _, reg, _ in calls)
    assert all(val == "2026-09-05 12:00:00" for _, _, val in calls)


def test_manual_sync_time_button_is_removed_from_discovery():
    device_id = "0PVPTEST"
    client = SimpleNamespace(_config_cache={})
    data = {
        "cmps": {
            f"grobro_{device_id}_sync_time": {
                "platform": "button",
                "name": "Sync Time",
            },
            f"grobro_{device_id}_serial": {
                "platform": "sensor",
                "name": "Device SN",
            },
        }
    }

    cleaned = _clean_discovery_payload(client, device_id, data)

    assert f"grobro_{device_id}_sync_time" not in cleaned["cmps"]
    assert f"grobro_{device_id}_serial" in cleaned["cmps"]
