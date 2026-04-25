"""Hermetic config factory for hassette test suites.

Exposes :func:`make_test_config` for end users who need a minimal
``HassetteConfig`` without TOML files or env vars.
"""

from pathlib import Path
from typing import Any

from pydantic_settings.sources import InitSettingsSource

from hassette.config.config import HassetteConfig

# Cached (hermetic_subclass, cell) pair — avoids creating a new class per
# make_test_config call, which would accumulate permanently in __subclasses__()
# and Pydantic's internal model cache.
# The cell is a single-element list the closure reads from; updated before each
# instantiation so no ClassVar shared state is needed.
_HermeticHassetteConfigPair: tuple[type[HassetteConfig], list[dict[str, Any]]] | None = None


def _get_hermetic_hassette_config_cls() -> tuple[type[HassetteConfig], list[dict[str, Any]]]:
    """Return a cached (hermetic subclass, cell) pair for HassetteConfig.

    The cell is a mutable single-element list captured by the subclass closure.
    Set ``cell[0] = merged`` before calling the subclass constructor to inject
    a specific config dict — no ClassVar write needed.
    """
    global _HermeticHassetteConfigPair
    if _HermeticHassetteConfigPair is not None:
        return _HermeticHassetteConfigPair

    # Mutable single-element container that the closure reads from.
    cell: list[dict[str, Any]] = [{}]

    class _Cls(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": None,
            "env_file": None,
        }

        @classmethod
        def settings_customise_sources(cls, settings_cls, **_kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
            return (InitSettingsSource(settings_cls, init_kwargs=cell[0]),)

    _HermeticHassetteConfigPair = (_Cls, cell)
    return _HermeticHassetteConfigPair


def make_test_config(*, data_dir: Path | str, **overrides: Any) -> HassetteConfig:
    """Create a minimal :class:`~hassette.config.config.HassetteConfig` for testing.

    No TOML file, no env file, no CLI args — only the provided overrides are
    read. All Pydantic validation still runs.

    Defaults:
        - ``token``: ``"test-token"``
        - ``base_url``: ``"http://test.invalid:8123"`` (unreachable by design)
        - ``disable_state_proxy_polling``: ``True``
        - ``autodetect_apps``: ``False``
        - ``run_web_api``: ``False``
        - ``run_app_precheck``: ``False``

    Overrides are merged on top of these defaults before validation.

    Args:
        data_dir: Directory for Hassette data (caches, etc.). In pytest, pass
            ``tmp_path`` from the built-in ``tmp_path`` fixture::

                def test_something(tmp_path):
                    config = make_test_config(data_dir=tmp_path)

        **overrides: Any ``HassetteConfig`` field values to override.

    Returns:
        A validated :class:`~hassette.config.config.HassetteConfig` instance.

    Example::

        config = make_test_config(data_dir=tmp_path)
        config = make_test_config(data_dir=tmp_path, base_url="http://192.168.1.1:8123")
    """
    defaults: dict[str, Any] = {
        "token": "test-token",
        "base_url": "http://test.invalid:8123",
        "data_dir": data_dir,
        "disable_state_proxy_polling": True,
        "autodetect_apps": False,
        "run_web_api": False,
        "run_app_precheck": False,
    }
    merged = {**defaults, **overrides}

    cls, cell = _get_hermetic_hassette_config_cls()
    # Update the cell before instantiation; no await between here and cls()
    # so asyncio cooperative multitasking cannot interleave a concurrent caller.
    cell[0] = merged
    return cls()
