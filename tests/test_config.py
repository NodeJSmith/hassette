from pathlib import Path

import dotenv

from hassette import Hassette, HassetteConfig


def test_overrides_are_used(env_file_path: Path, test_config: HassetteConfig) -> None:
    """Configuration values honour overrides from the test TOML and .env."""

    expected_token = dotenv.get_key(env_file_path, "hassette__token")

    # Create a Hassette instance to test URL functionality
    hassette = Hassette(test_config)

    assert hassette.ws_url == "ws://127.0.0.1:8123/api/websocket", (
        f"Expected ws://127.0.0.1:8123/api/websocket, got {hassette.ws_url}"
    )
    assert test_config.token == expected_token, f"Expected token to be {expected_token}, got {test_config.token}"


def test_env_overrides_are_used(test_config_class, monkeypatch, tmp_path):
    """Environment overrides win when constructing a HassetteConfig."""
    app_dir = tmp_path / "custom/apps"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("hassette__app_dir", str(app_dir))
    config_with_env_override = test_config_class()
    assert config_with_env_override.app_dir == app_dir, f"Expected {app_dir}, got {config_with_env_override.app_dir}"
