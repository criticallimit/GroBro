import json
import urllib.request

from grobro.ha.battery_ingress import start_battery_ingress_server
from grobro.ha.battery_position import (
    AUTO_ASSIGNMENT,
    observe_battery_serials,
)


def test_ingress_api_lists_and_saves_battery_assignments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = type("Client", (), {})()
    observe_battery_serials(
        client,
        "0PVPTEST",
        {
            "bat2_ser_part_1": "SN00200000000001",
            "bat3_ser_part_1": "SN00300000000002",
        },
    )

    server = start_battery_ingress_server(0)
    host, port = server.server_address
    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base}/api/state", timeout=3) as response:
            state = json.load(response)

        assert state["devices"][0]["device_id"] == "0PVPTEST"
        assert [item["serial"] for item in state["devices"][0]["detected"]] == [
            "SN00200000000001",
            "SN00300000000002",
        ]

        payload = json.dumps(
            {
                "device_id": "0PVPTEST",
                "assignments": {
                    "2": "SN00300000000002",
                    "3": "SN00200000000001",
                    "4": AUTO_ASSIGNMENT,
                },
            }
        ).encode()
        request = urllib.request.Request(
            f"{base}/api/assignments",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)

        assert result == {"ok": True}

        with urllib.request.urlopen(f"{base}/api/state", timeout=3) as response:
            state = json.load(response)

        manual = state["devices"][0]["manual"]
        assert manual["2"] == "SN00300000000002"
        assert manual["3"] == "SN00200000000001"
        assert manual["4"] == AUTO_ASSIGNMENT
    finally:
        server.shutdown()
        server.server_close()


def test_ingress_rejects_duplicate_serial_assignments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = start_battery_ingress_server(0)
    _host, port = server.server_address
    try:
        payload = json.dumps(
            {
                "device_id": "0PVPTEST",
                "assignments": {
                    "2": "SN00200000000001",
                    "3": "SN00200000000001",
                    "4": AUTO_ASSIGNMENT,
                },
            }
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/assignments",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("duplicate serial assignment was accepted")
    finally:
        server.shutdown()
        server.server_close()
