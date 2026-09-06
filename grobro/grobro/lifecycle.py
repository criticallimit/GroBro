"""Lifecycle helpers for the GroBro Home Assistant bridge."""


def run_clients(ha_client, grobro_client, signal_handler) -> None:
    """Start both clients, wait for shutdown, and always stop both cleanly."""
    ha_client.start()
    grobro_client.start()

    try:
        signal_handler.wait()
    finally:
        ha_client.stop()
        grobro_client.stop()
