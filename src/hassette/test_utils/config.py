"""Hermetic config factory for hassette test suites.

Exposes :func:`make_test_config` for end users who need a minimal
``HassetteConfig`` without TOML files or env vars.
"""

import tempfile
from typing import Any

from pydantic_settings.sources import InitSettingsSource

from hassette.config.config import HassetteConfig


def make_test_config(**overrides: Any) -> HassetteConfig:
    """Create a minimal :class:`~hassette.config.config.HassetteConfig` for testing.

    No TOML file, no env file, no CLI args — only the provided overrides are
    read. All Pydantic validation still runs.

    Defaults:
        - ``token``: ``"test-token"``
        - ``base_url``: ``"http://test.invalid:8123"`` (unreachable by design)
        - ``data_dir``: ``tempfile.mkdtemp()`` (a fresh temp directory — see warning below)
        - ``disable_state_proxy_polling``: ``True``
        - ``autodetect_apps``: ``False``
        - ``run_web_api``: ``False``
        - ``run_app_precheck``: ``False``

    Overrides are merged on top of these defaults before validation.

    Warning:
        When ``data_dir`` is not provided, a temporary directory is created via
        :func:`tempfile.mkdtemp` and is **not cleaned up automatically**. The
        caller is responsible for cleanup. In pytest, pass ``tmp_path`` from the
        built-in ``tmp_path`` fixture to avoid accumulating leftover directories::

            def test_something(tmp_path):
                config = make_test_config(data_dir=tmp_path)

        :class:`AppTestHarness` handles cleanup automatically when managing its
        own config; this warning applies only to direct callers of
        :func:`make_test_config`.

    Args:
        **overrides: Any ``HassetteConfig`` field values to override.

    Returns:
        A validated :class:`~hassette.config.config.HassetteConfig` instance.

    Example::

        config = make_test_config()
        config = make_test_config(base_url="http://192.168.1.1:8123")
        config = make_test_config(data_dir=tmp_path)  # pytest tmp_path — auto-cleaned
    """
    defaults: dict[str, Any] = {
        "token": "test-token",
        "base_url": "http://test.invalid:8123",
        "data_dir": tempfile.mkdtemp(prefix="hassette_test_"),
        "disable_state_proxy_polling": True,
        "autodetect_apps": False,
        "run_web_api": False,
        "run_app_precheck": False,
    }
    merged = {**defaults, **overrides}

    class _HermeticHassetteConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": None,
            "env_file": None,
        }

        @classmethod
        def settings_customise_sources(cls, settings_cls, **_kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
            return (InitSettingsSource(settings_cls, init_kwargs=merged),)

    return _HermeticHassetteConfig()
