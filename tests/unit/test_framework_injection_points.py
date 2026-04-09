"""Unit tests for framework injection points added for AppTestHarness.

Tests three targeted changes to core framework classes:
1. context.set_global_hassette() returns Token[Hassette] | None
2. App._api_factory ClassVar controls which Api subclass is created
3. StateProxy._test_seed_state() acquires write lock and inserts state
"""

from contextvars import ContextVar, Token
from typing import ClassVar
from unittest.mock import Mock, patch

import pytest
from fair_async_rlock import FairAsyncRLock

import hassette.context as ctx_module
from hassette.api import Api
from hassette.app.app import App, AppConfig
from hassette.context import (
    HASSETTE_INSTANCE as HASSETTE_INSTANCE,
)
from hassette.context import set_global_hassette
from hassette.core.state_proxy import StateProxy
from hassette.resources.base import Resource

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_mock_hassette(name: str = "mock_hassette") -> Mock:
    """Create a minimal mock Hassette instance."""
    m = Mock(name=name)
    m.config = Mock()
    m.config.apps_log_level = "DEBUG"
    m.config.log_level = "DEBUG"
    m.config.disable_state_proxy_polling = False
    m.config.state_proxy_poll_interval_seconds = 30
    m.config.app_shutdown_timeout_seconds = 5
    m.task_bucket = Mock()
    m.task_bucket.spawn = Mock()
    return m


class _MinimalAppConfig:
    """Minimal stand-in for AppConfig."""

    instance_name = "test"
    log_level = "DEBUG"


# ---------------------------------------------------------------------------
# Fixture: clean ContextVar state for set_global_hassette tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def clean_hassette_context():
    """Temporarily replace HASSETTE_INSTANCE with a fresh placeholder for tests.

    Since ContextVar has no way to "unset" once set, we use a module-level
    patch approach: monkeypatch hassette.context to use temporary ContextVars
    so tests run against a clean slate.
    """
    # Replace the module-level ContextVars with fresh ones
    _orig_instance = ctx_module.HASSETTE_INSTANCE
    _orig_location = ctx_module.HASSETTE_SET_LOCATION

    _fresh_instance: ContextVar = ContextVar("HASSETTE_INSTANCE")
    _fresh_location: ContextVar = ContextVar("HASSETTE_SET_LOCATION", default=None)

    ctx_module.HASSETTE_INSTANCE = _fresh_instance  # pyright: ignore[reportAttributeAccessIssue]
    ctx_module.HASSETTE_SET_LOCATION = _fresh_location  # pyright: ignore[reportAttributeAccessIssue]

    # Also patch the name imported in the test module itself
    import tests.unit.test_framework_injection_points as _this_module

    _orig_test_instance = _this_module.HASSETTE_INSTANCE
    _this_module.HASSETTE_INSTANCE = _fresh_instance  # pyright: ignore[reportAttributeAccessIssue]

    yield _fresh_instance

    # Restore originals
    ctx_module.HASSETTE_INSTANCE = _orig_instance  # pyright: ignore[reportAttributeAccessIssue]
    ctx_module.HASSETTE_SET_LOCATION = _orig_location  # pyright: ignore[reportAttributeAccessIssue]
    _this_module.HASSETTE_INSTANCE = _orig_test_instance  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------------------
# Tests: set_global_hassette returns Token
# ---------------------------------------------------------------------------


class TestSetGlobalHassetteReturnsToken:
    """set_global_hassette() returns a Token[Hassette] so callers can reset it."""

    def test_returns_token_on_first_set(self, clean_hassette_context) -> None:
        """Calling set_global_hassette with a new instance returns a Token."""
        hassette = _make_mock_hassette()
        fresh_instance = clean_hassette_context  # the fresh ContextVar

        result = set_global_hassette(hassette)

        assert result is not None
        assert isinstance(result, Token)

        # Clean up: reset the ContextVar using the returned token
        fresh_instance.reset(result)

    def test_returned_token_can_reset_contextvar(self, clean_hassette_context) -> None:
        """The returned token restores the ContextVar to its pre-set state."""
        hassette = _make_mock_hassette()
        fresh_instance = clean_hassette_context

        token = set_global_hassette(hassette)
        assert token is not None

        # After setting, the ContextVar holds hassette
        assert fresh_instance.get(None) is hassette

        # Resetting with the token clears the ContextVar
        fresh_instance.reset(token)
        assert fresh_instance.get(None) is None

    def test_same_instance_returns_none(self, clean_hassette_context) -> None:
        """When the same instance is already set, returns None (early-return path)."""
        hassette = _make_mock_hassette()
        fresh_instance = clean_hassette_context

        first_token = set_global_hassette(hassette)
        assert first_token is not None

        # Setting the same instance again returns None
        second_result = set_global_hassette(hassette)
        assert second_result is None

        # Clean up
        fresh_instance.reset(first_token)


# ---------------------------------------------------------------------------
# Tests: App._api_factory injection point
# ---------------------------------------------------------------------------


class TestAppApiFactory:
    """App._api_factory ClassVar controls which resource class is used for api."""

    def test_default_factory_is_none(self) -> None:
        """App._api_factory class attribute is None by default."""
        assert App._api_factory is None

    def test_default_uses_api_class(self) -> None:
        """When _api_factory is None, App.__init__ creates an Api instance."""

        class _TestConfig(AppConfig):
            model_config: ClassVar[dict[str, str]] = {"env_prefix": "test_wp01_default_"}

        class _TestApp(App[_TestConfig]):
            app_config_cls = _TestConfig
            app_manifest = Mock()  # pyright: ignore[reportAttributeAccessIssue]

        hassette = _make_mock_hassette()
        config = _TestConfig(instance_name="test")

        # Must patch add_child to avoid actually starting resources
        original_add_child = Resource.add_child

        created_classes: list[type] = []

        def spy_add_child(self, cls, *args, **kwargs):  # pyright: ignore[reportUnknownParameterType]
            created_classes.append(cls)
            return original_add_child(self, cls, *args, **kwargs)

        with patch.object(Resource, "add_child", spy_add_child):
            _TestApp(hassette, app_config=config, index=0)

        assert Api in created_classes, f"Expected Api to be created, got: {created_classes}"

    def test_custom_factory_is_used(self) -> None:
        """When _api_factory is set, App.__init__ uses it instead of Api."""

        class _TestConfig(AppConfig):
            model_config: ClassVar[dict[str, str]] = {"env_prefix": "test_wp01_custom_"}

        class _FakeApi(Resource):
            """Test double for Api."""

            async def on_initialize(self) -> None:
                self.mark_ready(reason="FakeApi initialized")

        class _TestApp(App[_TestConfig]):
            app_config_cls = _TestConfig
            app_manifest = Mock()  # pyright: ignore[reportAttributeAccessIssue]
            _api_factory = _FakeApi

        hassette = _make_mock_hassette()
        config = _TestConfig(instance_name="test")

        original_add_child = Resource.add_child
        created_classes: list[type] = []

        def spy_add_child(self, cls, *args, **kwargs):  # pyright: ignore[reportUnknownParameterType]
            created_classes.append(cls)
            return original_add_child(self, cls, *args, **kwargs)

        with patch.object(Resource, "add_child", spy_add_child):
            app = _TestApp(hassette, app_config=config, index=0)

        assert _FakeApi in created_classes, f"Expected _FakeApi, got: {created_classes}"
        assert Api not in created_classes, "Api should not be created when _api_factory is set"
        assert isinstance(app.api, _FakeApi)


# ---------------------------------------------------------------------------
# Tests: StateProxy._test_seed_state
# ---------------------------------------------------------------------------


class TestStateProxySeedState:
    """StateProxy._test_seed_state() writes to the state cache under the write lock."""

    def _make_state_proxy(self, *, test_mode: bool = True) -> StateProxy:
        """Build a StateProxy with a mock Hassette (no real initialization)."""
        proxy = object.__new__(StateProxy)
        # Initialize only the attributes we need (avoid calling __init__
        # which would add_child resources and trigger full lifecycle)
        proxy.states = {}  # pyright: ignore[reportAttributeAccessIssue]
        proxy.lock = FairAsyncRLock()  # pyright: ignore[reportAttributeAccessIssue]
        # _test_seed_state requires hassette._test_mode = True
        hassette_mock = Mock()
        hassette_mock._test_mode = test_mode
        proxy.hassette = hassette_mock  # pyright: ignore[reportAttributeAccessIssue]
        return proxy

    @pytest.mark.asyncio
    async def test_seed_state_writes_to_cache(self) -> None:
        """_test_seed_state inserts the state dict into self.states."""
        proxy = self._make_state_proxy()

        state_dict = {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {"brightness": 255},
            "last_updated": "1970-01-01T00:00:00+00:00",
            "last_changed": "1970-01-01T00:00:00+00:00",
            "context": {"id": "test"},
        }

        await proxy._test_seed_state("light.kitchen", state_dict)

        assert "light.kitchen" in proxy.states  # pyright: ignore[reportAttributeAccessIssue]
        assert proxy.states["light.kitchen"] is state_dict  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.asyncio
    async def test_seed_state_overwrites_existing(self) -> None:
        """_test_seed_state replaces any existing entry for the entity."""
        proxy = self._make_state_proxy()

        old_dict = {"entity_id": "light.kitchen", "state": "off", "attributes": {}}
        new_dict = {"entity_id": "light.kitchen", "state": "on", "attributes": {}}

        proxy.states["light.kitchen"] = old_dict  # pyright: ignore[reportAttributeAccessIssue]
        await proxy._test_seed_state("light.kitchen", new_dict)

        assert proxy.states["light.kitchen"] is new_dict  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.asyncio
    async def test_seed_state_acquires_lock(self) -> None:
        """_test_seed_state acquires the write lock before writing."""
        proxy = self._make_state_proxy()

        lock_acquired = False
        original_lock = proxy.lock  # pyright: ignore[reportAttributeAccessIssue]

        class _SpyLock:
            """Wrapper that records whether the lock was acquired."""

            async def __aenter__(self) -> "_SpyLock":
                nonlocal lock_acquired
                lock_acquired = True
                await original_lock.__aenter__()
                return self

            async def __aexit__(self, *args) -> None:  # pyright: ignore[reportUnknownParameterType]
                await original_lock.__aexit__(*args)

        proxy.lock = _SpyLock()  # pyright: ignore[reportAttributeAccessIssue]

        state_dict = {"entity_id": "sensor.temp", "state": "25", "attributes": {}}
        await proxy._test_seed_state("sensor.temp", state_dict)

        assert lock_acquired, "_test_seed_state must acquire the write lock"

    @pytest.mark.asyncio
    async def test_seed_state_does_not_call_mark_ready(self) -> None:
        """_test_seed_state must NOT call mark_ready() — lifecycle is separate from seeding."""
        proxy = self._make_state_proxy()

        # Track calls to mark_ready (should not be called)
        mark_ready_called = False

        def _spy_mark_ready(**_kwargs: object) -> None:
            nonlocal mark_ready_called
            mark_ready_called = True

        proxy.mark_ready = _spy_mark_ready  # pyright: ignore[reportAttributeAccessIssue]

        state_dict = {"entity_id": "sensor.temp", "state": "25", "attributes": {}}
        await proxy._test_seed_state("sensor.temp", state_dict)

        assert not mark_ready_called, "_test_seed_state must not call mark_ready()"

    @pytest.mark.asyncio
    async def test_seed_state_rejects_non_test_mode(self) -> None:
        """_test_seed_state raises RuntimeError when hassette._test_mode is not set."""
        proxy = self._make_state_proxy(test_mode=False)
        state_dict = {"entity_id": "sensor.temp", "state": "25", "attributes": {}}

        with pytest.raises(RuntimeError, match="must not be called outside of test context"):
            await proxy._test_seed_state("sensor.temp", state_dict)


# ---------------------------------------------------------------------------
# now() import invariant
# ---------------------------------------------------------------------------


class TestNowImportInvariant:
    """Ensure no module uses 'from hassette.utils.date_utils import now'.

    freeze_time patches ``hassette.utils.date_utils.now`` via module-attribute
    access. Direct imports (``from ... import now``) bind a local reference that
    the patch cannot reach, silently breaking time control.
    """

    def test_no_direct_now_import(self) -> None:
        """No source file in src/hassette/ may use 'from hassette.utils.date_utils import now'."""
        import re
        from pathlib import Path

        src_root = Path(__file__).resolve().parents[2] / "src" / "hassette"
        pattern = re.compile(r"from\s+hassette\.utils\.date_utils\s+import\s+.*\bnow\b")
        violations: list[str] = []

        for py_file in src_root.rglob("*.py"):
            text = py_file.read_text()
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    violations.append(f"{py_file.relative_to(src_root.parent.parent)}:{i}: {line.strip()}")

        assert not violations, (
            "Direct 'from hassette.utils.date_utils import now' breaks freeze_time patching. "
            "Use 'import hassette.utils.date_utils as date_utils' instead.\n" + "\n".join(violations)
        )
