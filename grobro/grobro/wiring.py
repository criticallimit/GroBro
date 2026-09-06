"""Client wiring for the GroBro Home Assistant bridge.

Keep callback connections in one place so the executable entrypoint remains
small and upstream client changes are easier to reconcile.
"""


def wire_clients(ha_client, grobro_client) -> None:
    """Connect GroBro and Home Assistant client callbacks bidirectionally."""
    # grobro -> ha
    grobro_client.on_input_register = ha_client.publish_input_register
    grobro_client.on_holding_register_input = ha_client.publish_holding_register_input
    grobro_client.on_config = ha_client.set_config
    grobro_client.on_config_read_response = ha_client.handle_config_read_response

    # ha -> grobro
    ha_client.on_command = grobro_client.send_command
    ha_client.on_config_read = grobro_client.send_config_read_message
    ha_client.on_config_command = (
        lambda dev, reg, val: grobro_client.send_config_message(dev, reg, val)
    )
