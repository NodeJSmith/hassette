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

# Bearer token used across the web-API auth test suites (integration + e2e) to build a
# `create_fastapi_app(..., auth_token=...)` instance and mint matching session cookies.
# Distinct from TEST_TOKEN above, which is the HA connection token used by make_test_config.
WEB_API_TEST_TOKEN = "test-token-value"

# Matches the `session_ttl` override the web-API auth tests apply to `config.web_api` before
# minting or verifying session cookies.
TEST_SESSION_TTL = 3600

DEFAULT_TEST_APP_KEY = "test_app"
TEST_EPOCH_A = 1_234_567_890.0
TEST_EPOCH_B = 1_700_000_000.0
TEST_ISO_TIMESTAMP = "2024-01-01T00:00:00.000000"
"""ISO-format counterpart to TEST_EPOCH_* for DB rows whose timestamp columns are TEXT
(e.g. app_manifests.created_at/updated_at) rather than epoch floats."""

LATEST_MIGRATION_VERSION = 12
"""PRAGMA user_version after a fresh DB is migrated to head. Bump alongside adding a new
numbered file to migrations_sql/."""

# Shutdown budget for a directly-constructed SyncExecutor's `shutdown_pool(timeout=...)`
# at test teardown. Generous relative to test workloads so it never masks a real hang.
TEST_SYNC_EXECUTOR_SHUTDOWN_TIMEOUT_SECONDS = 5.0

# Shared by hassette.test_utils.reset and hassette.test_utils.harness (Timeouts.WAIT_FOR_READY)
# for waiting on StateProxy initial state capability during test setup/reset. Lives here rather
# than in either of those two modules because harness.py imports reset.py at load time, so a
# constant defined in either one and imported by the other would form a circular import.
WAIT_FOR_READY_TIMEOUT_SECONDS = 5.0

# Matches the production default (WebSocketConfig.total_timeout_seconds). Tests use this
# instead of a tight override to avoid the config-driven real-clock timeout race
# documented in CLAUDE.md.
TEST_TOTAL_TIMEOUT_SECONDS = 30

# Early-drop retry tuning shared by tests/integration/test_websocket_service.py and
# tests/unit/core/test_ws_connection_state.py. Small backoff values keep the retry loop fast
# and deterministic in CI. Tests that need a different value for the specific behavior under
# test (e.g. proving retry-budget exhaustion) pass a literal instead of reusing these.
TEST_EARLY_DROP_MAX_RETRIES = 5
TEST_EARLY_DROP_STABLE_WINDOW_SECONDS = 30.0
TEST_EARLY_DROP_BACKOFF_INITIAL_SECONDS = 0.001
TEST_EARLY_DROP_BACKOFF_MAX_SECONDS = 0.01

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
