from grobro.ha.device_inventory import (
    clear_device_inventory,
    get_device_inventory,
    observe_device,
)


def setup_function():
    clear_device_inventory()


def teardown_function():
    clear_device_inventory()


def test_inventory_reports_known_device_families():
    observe_device("0PVPTEST000001")
    observe_device("QMNTEST0000001")
    observe_device("0HVRTEST000001")

    inventory = get_device_inventory()

    assert [(item["display_name"], item["device_id"]) for item in inventory] == [
        ("NEO", "QMNTEST0000001"),
        ("NEXA", "0HVRTEST000001"),
        ("NOAH", "0PVPTEST000001"),
    ]


def test_inventory_updates_existing_device_without_duplicate():
    observe_device("0PVPTEST000001")
    first = get_device_inventory()[0]

    observe_device("0PVPTEST000001")
    inventory = get_device_inventory()

    assert len(inventory) == 1
    assert inventory[0] == first
    assert inventory[0]["display_name"] == "NOAH"


def test_inventory_keeps_unknown_family_visible():
    observe_device("UNKNOWN123")

    inventory = get_device_inventory()

    assert inventory[0]["display_name"] == "UNKNOWN"
    assert inventory[0]["family"] == "unknown"
