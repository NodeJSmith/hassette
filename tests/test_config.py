from pathlib import Path

import dotenv

from hassette.config.core_config import HassetteConfig


def test_overrides_are_used(env_file_path: Path, test_config: HassetteConfig) -> None:
    """
    Test that the overrides in the HassetteConfig are used correctly.
    """

    expected_token = dotenv.get_key(env_file_path, "hassette__hass__token")

    assert test_config.hass.ws_url == "ws://127.0.0.1:8123/api/websocket"
    assert test_config.hass.token.get_secret_value() == expected_token

    assert len(test_config.apps) > 0, "Expected at least one app configuration to be loaded"
    assert "my_app" in test_config.apps, "Expected 'my_app' to be in the loaded app configurations"
