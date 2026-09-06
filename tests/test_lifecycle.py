import pytest

from grobro.grobro.lifecycle import run_clients


class _Client:
    def __init__(self, events, name):
        self.events = events
        self.name = name

    def start(self):
        self.events.append(f"{self.name}:start")

    def stop(self):
        self.events.append(f"{self.name}:stop")


class _SignalHandler:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error

    def wait(self):
        self.events.append("wait")
        if self.error is not None:
            raise self.error


def test_run_clients_preserves_start_wait_stop_order():
    events = []
    ha_client = _Client(events, "ha")
    grobro_client = _Client(events, "grobro")

    run_clients(ha_client, grobro_client, _SignalHandler(events))

    assert events == [
        "ha:start",
        "grobro:start",
        "wait",
        "ha:stop",
        "grobro:stop",
    ]


def test_run_clients_stops_both_when_wait_raises():
    events = []
    ha_client = _Client(events, "ha")
    grobro_client = _Client(events, "grobro")

    with pytest.raises(RuntimeError, match="boom"):
        run_clients(
            ha_client,
            grobro_client,
            _SignalHandler(events, RuntimeError("boom")),
        )

    assert events[-2:] == ["ha:stop", "grobro:stop"]
