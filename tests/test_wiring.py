from grobro.grobro.wiring import wire_clients


class _HAClient:
    def publish_input_register(self, value):
        return value

    def publish_holding_register_input(self, value):
        return value

    def set_config(self, value):
        return value

    def handle_config_read_response(self, value):
        return value


class _GroBroClient:
    def send_command(self, value):
        return value

    def send_config_read_message(self, value):
        return value

    def send_config_message(self, dev, reg, val):
        return (dev, reg, val)


def test_wire_clients_connects_both_directions():
    ha_client = _HAClient()
    grobro_client = _GroBroClient()

    wire_clients(ha_client, grobro_client)

    assert grobro_client.on_input_register == ha_client.publish_input_register
    assert (
        grobro_client.on_holding_register_input
        == ha_client.publish_holding_register_input
    )
    assert grobro_client.on_config == ha_client.set_config
    assert (
        grobro_client.on_config_read_response
        == ha_client.handle_config_read_response
    )
    assert ha_client.on_command == grobro_client.send_command
    assert ha_client.on_config_read == grobro_client.send_config_read_message
    assert ha_client.on_config_command("dev", 257, 400) == ("dev", 257, 400)
