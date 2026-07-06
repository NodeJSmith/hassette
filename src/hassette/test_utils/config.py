"""Hermetic config factory for hassette test suites.

Exposes :func:`make_test_config` for end users who need a minimal
``HassetteConfig`` without TOML files or env vars.
"""

import threading
from pathlib import Path
from typing import Any

from pydantic_settings.sources import InitSettingsSource

from hassette.config.config import HassetteConfig

TEST_TOKEN = "test-token"
TEST_BASE_URL = "http://test.invalid:8123"
TEST_WS_URL = "ws://test.invalid:8123/api/websocket"
TEST_SOURCE_LOCATION = "test.py:1"

DEFAULT_TEST_APP_KEY = "test_app"
TEST_EPOCH_A = 1_234_567_890.0
TEST_EPOCH_B = 1_700_000_000.0

# Cached (hermetic_subclass, init_kwargs_ref) pair — avoids creating a new class per
# make_test_config call, which would accumulate permanently in __subclasses__()
# and Pydantic's internal model cache.
# Same closure-ref pattern as get_hermetic_subclass in app_harness.py (per-AppConfig variant).
hermetic_hassette_config_pair: tuple[type[HassetteConfig], list[dict[str, Any]]] | None = None

# Protects both the lazy-init check-and-create in get_hermetic_hassette_config_cls()
# and the cell[0] = merged → cls() sequence in make_test_config() against OS-thread races.
# Async tests run on a single thread so asyncio cooperative multitasking cannot interleave,
# but session-scoped fixtures (e.g. _migrated_db_template) may call make_test_config() from
# threads created by pytest-xdist workers.
_config_lock: threading.Lock = threading.Lock()


def get_hermetic_hassette_config_cls() -> tuple[type[HassetteConfig], list[dict[str, Any]]]:
    """Return a cached (hermetic subclass, cell) pair for HassetteConfig.

    The cell is a mutable single-element list captured by the subclass closure.
    Set ``cell[0] = merged`` before calling the subclass constructor to inject
    a specific config dict — no ClassVar write needed.

    The hermetic subclass uses ``extra="forbid"`` so stale flat field names
    (that should now be nested) fail loudly instead of being silently absorbed.

    Callers must hold ``_config_lock`` before calling this function.
    """
    global hermetic_hassette_config_pair
    if hermetic_hassette_config_pair is not None:
        return hermetic_hassette_config_pair

    # Mutable single-element container that the closure reads from.
    cell: list[dict[str, Any]] = [{}]

    class _Cls(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "toml_file": None,
            "env_file": None,
            "extra": "forbid",
        }

        @classmethod
        def settings_customise_sources(cls, settings_cls: type, **_kwargs: Any) -> tuple[InitSettingsSource]:  # pyright: ignore[reportIncompatibleMethodOverride]
            return (InitSettingsSource(settings_cls, init_kwargs=cell[0]),)

    hermetic_hassette_config_pair = (_Cls, cell)
    return hermetic_hassette_config_pair


def make_test_config(*, data_dir: Path | str, **overrides: Any) -> HassetteConfig:
    """Create a minimal :class:`~hassette.config.config.HassetteConfig` for testing.

    No TOML file, no env file, no CLI args — only the provided overrides are
    read. All Pydantic validation still runs.

    Defaults:
        - ``token``: ``"test-token"`` (stored as ``SecretStr``; read via
          ``config.token.get_secret_value()``)
        - ``base_url``: ``"http://test.invalid:8123"`` (unreachable by design)
        - ``disable_state_proxy_polling``: ``True``
        - ``apps``: ``{"autodetect": False}``
        - ``web_api``: ``{"run": False}``
        - ``run_app_precheck``: ``False``

    Overrides are merged on top of these defaults before validation. Nested
    group overrides can be passed as dicts or model instances::

        make_test_config(data_dir=tmp_path, database={"retention_days": 14})
        make_test_config(data_dir=tmp_path, database=DatabaseConfig(retention_days=14))

    Args:
        data_dir: Directory for Hassette data (caches, etc.). In pytest, pass
            ``tmp_path`` from the built-in ``tmp_path`` fixture::

                def test_something(tmp_path):
                    config = make_test_config(data_dir=tmp_path)

        **overrides: Any ``HassetteConfig`` field values to override. Nested
            group fields may be passed as dicts or model instances.

    Returns:
        A validated :class:`~hassette.config.config.HassetteConfig` instance.

    Example::

        config = make_test_config(data_dir=tmp_path)
        config = make_test_config(data_dir=tmp_path, base_url="http://192.168.1.1:8123")
        config = make_test_config(data_dir=tmp_path, database={"retention_days": 14})
    """
    defaults: dict[str, Any] = {
        "token": TEST_TOKEN,
        "base_url": TEST_BASE_URL,
        "data_dir": data_dir,
        "disable_state_proxy_polling": True,
        "apps": {"autodetect": False},
        "web_api": {"run": False},
        "run_app_precheck": False,
    }
    merged = {**defaults, **overrides}

    with _config_lock:
        cls, cell = get_hermetic_hassette_config_cls()
        cell[0] = merged
        return cls()
