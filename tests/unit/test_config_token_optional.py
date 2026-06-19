"""Tests for HassetteConfig with optional token field.

Covers the new None-guard behaviors only. Non-None token behavior
(auth_headers, truncated_token) is covered by TestAuthHeaders in test_config.py.
"""

from hassette.config.config import HassetteConfig
from hassette.test_utils.config import make_test_config


def test_token_none_instantiates_without_error(tmp_path) -> None:
    config = make_test_config(data_dir=tmp_path, token=None)
    assert config.token is None


def test_auth_headers_returns_empty_dict_when_token_is_none(tmp_path) -> None:
    config = make_test_config(data_dir=tmp_path, token=None)
    assert config.auth_headers == {}


def test_truncated_token_returns_not_set_when_token_is_none(tmp_path) -> None:
    config = make_test_config(data_dir=tmp_path, token=None)
    assert config.truncated_token == "<not set>"


def test_hassette_token_env_var_is_loaded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HASSETTE__TOKEN", "env-token-value")

    class _EnvConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "toml_file": None,
            "env_file": None,
        }

    config = _EnvConfig(data_dir=tmp_path)
    assert config.token == "env-token-value"


def test_ha_token_env_var_is_loaded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HA_TOKEN", "ha-token-value")

    class _EnvConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "toml_file": None,
            "env_file": None,
        }

    config = _EnvConfig(data_dir=tmp_path)
    assert config.token == "ha-token-value"
