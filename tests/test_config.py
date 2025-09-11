from pathlib import Path

import dotenv

from hassette.config.core_config import HassetteConfig


def test_overrides_are_used(env_file_path: Path, test_config: HassetteConfig) -> None:
    """
    Test that the overrides in the HassetteConfig are used correctly.
    """

    expected_token = dotenv.get_key(env_file_path, "hassette_token")

    assert test_config.ws_url == "ws://127.0.0.1:8123/api/websocket"
    assert test_config.token.get_secret_value() == expected_token
