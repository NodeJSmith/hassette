from pathlib import Path

import dotenv

from hassette.config.core_config import HassetteConfig


def test_overrides_are_used(env_file_path: Path, test_config: HassetteConfig) -> None:
    """
    Test that the overrides in the HassetteConfig are used correctly.
    """

    expected_token = dotenv.get_key(env_file_path, "hassette__token")

    assert test_config.ws_url == "ws://127.0.0.1:8123/api/websocket", (
        f"Expected ws://127.0.0.1:8123/api/websocket, got {test_config.ws_url}"
    )
    assert test_config.token.get_secret_value() == expected_token, (
        f"Expected token to be {expected_token}, got {test_config.token.get_secret_value()}"
    )


def test_env_overrides_are_used(test_config_class, monkeypatch):
    """
    Test that environment variable overrides are used correctly.
    """
    monkeypatch.setenv("hassette__app_dir", "/custom/apps")
    config = test_config_class()
    assert config.app_dir == Path("/custom/apps"), f"Expected /custom/apps, got {config.app_dir}"
