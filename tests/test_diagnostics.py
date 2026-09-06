from grobro.grobro import diagnostics


def test_install_optional_diagnostics_installs_both_observers(monkeypatch):
    calls = []

    monkeypatch.setattr(
        diagnostics,
        "install_register_debug_hook",
        lambda: calls.append("register"),
    )
    monkeypatch.setattr(
        diagnostics,
        "install_noah_traffic_debug_hook",
        lambda: calls.append("traffic"),
    )

    diagnostics.install_optional_diagnostics()

    assert calls == ["register", "traffic"]
