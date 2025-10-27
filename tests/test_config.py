from pathlib import Path

import dotenv

from hassette.config.core_config import HassetteConfig
from hassette.core.core import Hassette


def test_overrides_are_used(env_file_path: Path, test_config: HassetteConfig) -> None:
    """Configuration values honour overrides from the test TOML and .env."""

    expected_token = dotenv.get_key(env_file_path, "hassette__token")

    # Create a Hassette instance to test URL functionality
    hassette = Hassette(test_config)

    assert hassette.ws_url == "ws://127.0.0.1:8123/api/websocket", (
        f"Expected ws://127.0.0.1:8123/api/websocket, got {hassette.ws_url}"
    )
    assert test_config.token == expected_token, f"Expected token to be {expected_token}, got {test_config.token}"


def test_env_overrides_are_used(test_config_class, monkeypatch):
    """Environment overrides win when constructing a HassetteConfig."""
    monkeypatch.setenv("hassette__app_dir", "/custom/apps")
    config_with_env_override = test_config_class()
    assert config_with_env_override.app_dir == Path("/custom/apps"), (
        f"Expected /custom/apps, got {config_with_env_override.app_dir}"
    )
