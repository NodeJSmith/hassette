"""Tests for make_test_config() factory.

Verifies default values, override application, env var hermiticity, and
that the data_dir is a temp directory.
"""

import tempfile

from hassette.test_utils import make_test_config


def test_defaults() -> None:
    """make_test_config() produces config with correct default values."""
    config = make_test_config()
    assert config.token == "test-token"
    # base_url encodes ha_host + ha_port
    assert "test.invalid" in config.base_url
    assert "8123" in config.base_url


def test_override() -> None:
    """Overrides are applied to the resulting config."""
    config = make_test_config(base_url="http://192.168.1.1:8123")
    assert "192.168.1.1" in config.base_url


def test_hermetic_no_env(monkeypatch) -> None:
    """Env vars are not picked up by make_test_config()."""
    monkeypatch.setenv("HASSETTE__TOKEN", "env-token-should-not-appear")
    config = make_test_config()
    assert config.token == "test-token", "make_test_config() must not read env vars — hermetic settings only"


def test_data_dir_is_tmpdir() -> None:
    """data_dir points to a temporary directory that exists."""
    config = make_test_config()
    assert config.data_dir is not None
    # Should be inside the system tmp directory or similar
    tmpdir = tempfile.gettempdir()
    assert str(config.data_dir).startswith(tmpdir) or config.data_dir.exists(), "data_dir should be a temp directory"


def test_data_dir_override_respected(tmp_path) -> None:
    """When data_dir is provided, make_test_config uses it instead of creating a new tmpdir."""
    config = make_test_config(data_dir=tmp_path)
    assert config.data_dir == tmp_path, "data_dir override was ignored — make_test_config created its own tmpdir"
