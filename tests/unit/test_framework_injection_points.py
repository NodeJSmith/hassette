"""Unit tests for framework injection points added for AppTestHarness.

Tests targeted changes to core framework classes:
1. context.set_global_hassette() returns Token[Hassette] | None
2. App api_factory constructor parameter controls which Api subclass is created
3. HassetteHarness.seed_state() acquires write lock with timeout and inserts state
4. TaskBucket exception recorder list — install/uninstall/LIFO semantics
"""

import asyncio
import contextlib
from contextvars import ContextVar, Token
from pathlib import Path
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
from hassette.task_bucket.task_bucket import TaskBucket
from hassette.test_utils.harness import TIMEOUTS, HassetteHarness

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
# Tests: App api_factory constructor parameter
# ---------------------------------------------------------------------------


class TestAppApiFactory:
    """App api_factory constructor parameter controls which resource class is used for api."""

    def test_default_uses_api_class(self) -> None:
        """When api_factory is not passed, App.__init__ creates an Api instance."""

        class _TestConfig(AppConfig):
            model_config: ClassVar[dict[str, str]] = {"env_prefix": "test_wp01_default_"}

        class _TestApp(App[_TestConfig]):
            app_config_cls = _TestConfig
            app_manifest = Mock()  # pyright: ignore[reportAttributeAccessIssue]

        hassette = _make_mock_hassette()
        config = _TestConfig(instance_name="test")

        original_add_child = Resource.add_child

        created_classes: list[type] = []

        def spy_add_child(self, cls, *args, **kwargs):  # pyright: ignore[reportUnknownParameterType]
            created_classes.append(cls)
            return original_add_child(self, cls, *args, **kwargs)

        with patch.object(Resource, "add_child", spy_add_child):
            _TestApp(hassette, app_config=config, index=0)

        assert Api in created_classes, f"Expected Api to be created, got: {created_classes}"

    def test_custom_factory_is_used(self) -> None:
        """When api_factory is passed, App.__init__ uses it instead of Api."""

        class _TestConfig(AppConfig):
            model_config: ClassVar[dict[str, str]] = {"env_prefix": "test_wp01_custom_"}

        class _FakeApi(Resource):
            """Test double for Api."""

            async def on_initialize(self) -> None:
                self.mark_ready(reason="FakeApi initialized")

        class _TestApp(App[_TestConfig]):
            app_config_cls = _TestConfig
            app_manifest = Mock()  # pyright: ignore[reportAttributeAccessIssue]

        hassette = _make_mock_hassette()
        config = _TestConfig(instance_name="test")

        original_add_child = Resource.add_child
        created_classes: list[type] = []

        def spy_add_child(self, cls, *args, **kwargs):  # pyright: ignore[reportUnknownParameterType]
            created_classes.append(cls)
            return original_add_child(self, cls, *args, **kwargs)

        with patch.object(Resource, "add_child", spy_add_child):
            app = _TestApp(hassette, app_config=config, index=0, api_factory=_FakeApi)

        assert _FakeApi in created_classes, f"Expected _FakeApi, got: {created_classes}"
        assert Api not in created_classes, "Api should not be created when api_factory is passed"
        assert isinstance(app.api, _FakeApi)


# ---------------------------------------------------------------------------
# Tests: HassetteHarness.seed_state
# ---------------------------------------------------------------------------


class TestHarnessSeedState:
    """HassetteHarness.seed_state() writes to the StateProxy cache under the lock."""

    def _make_harness_with_proxy(self, tmp_path: Path) -> tuple[HassetteHarness, StateProxy]:
        """Build a HassetteHarness with a minimal StateProxy (no full lifecycle)."""
        from hassette.test_utils.config import make_test_config

        config = make_test_config(data_dir=tmp_path)
        harness = HassetteHarness(config, skip_global_set=True)

        # Install a minimal StateProxy directly on the mock hassette
        proxy = object.__new__(StateProxy)
        proxy.states = {}  # pyright: ignore[reportAttributeAccessIssue]
        proxy.lock = FairAsyncRLock()  # pyright: ignore[reportAttributeAccessIssue]
        proxy.hassette = harness.hassette  # pyright: ignore[reportAttributeAccessIssue]
        harness.hassette._state_proxy = proxy

        return harness, proxy

    async def test_harness_seed_state_writes_to_proxy(self, tmp_path: Path) -> None:
        """seed_state inserts the state dict into StateProxy.states."""
        harness, proxy = self._make_harness_with_proxy(tmp_path)

        state_dict = {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {"brightness": 255},
            "last_updated": "1970-01-01T00:00:00+00:00",
            "last_changed": "1970-01-01T00:00:00+00:00",
            "context": {"id": "test"},
        }

        await harness.seed_state("light.kitchen", state_dict)

        assert "light.kitchen" in proxy.states  # pyright: ignore[reportAttributeAccessIssue]
        assert proxy.states["light.kitchen"] is state_dict  # pyright: ignore[reportAttributeAccessIssue]

    async def test_harness_seed_state_overwrites_existing(self, tmp_path: Path) -> None:
        """seed_state replaces any existing entry for the entity."""
        harness, proxy = self._make_harness_with_proxy(tmp_path)

        old_dict = {"entity_id": "light.kitchen", "state": "off", "attributes": {}}
        new_dict = {"entity_id": "light.kitchen", "state": "on", "attributes": {}}

        proxy.states["light.kitchen"] = old_dict  # pyright: ignore[reportAttributeAccessIssue]
        await harness.seed_state("light.kitchen", new_dict)

        assert proxy.states["light.kitchen"] is new_dict  # pyright: ignore[reportAttributeAccessIssue]

    async def test_harness_seed_state_acquires_lock(self, tmp_path: Path) -> None:
        """seed_state acquires the write lock before writing."""
        harness, proxy = self._make_harness_with_proxy(tmp_path)

        lock_acquired = False
        original_lock = proxy.lock  # pyright: ignore[reportAttributeAccessIssue]

        class _SpyLock:
            """Wrapper that records whether the lock was acquired."""

            async def acquire(self) -> bool:
                nonlocal lock_acquired
                lock_acquired = True
                return await original_lock.acquire()

            def release(self) -> None:
                original_lock.release()

        proxy.lock = _SpyLock()  # pyright: ignore[reportAttributeAccessIssue]

        state_dict = {"entity_id": "sensor.temp", "state": "25", "attributes": {}}
        await harness.seed_state("sensor.temp", state_dict)

        assert lock_acquired, "seed_state must acquire the write lock"

    async def test_harness_seed_state_timeout_on_locked_proxy(self, tmp_path: Path) -> None:
        """seed_state raises TimeoutError when lock cannot be acquired within timeout."""
        harness, proxy = self._make_harness_with_proxy(tmp_path)

        lock_held = asyncio.Event()
        release_gate = asyncio.Event()

        async def _hold_lock() -> None:
            async with proxy.lock:  # pyright: ignore[reportAttributeAccessIssue]
                lock_held.set()
                with contextlib.suppress(asyncio.CancelledError):
                    await release_gate.wait()

        task = asyncio.create_task(_hold_lock())
        await lock_held.wait()

        state_dict = {"entity_id": "sensor.temp", "state": "25", "attributes": {}}

        try:
            with (
                patch.object(TIMEOUTS, "STATE_SEED_LOCK", 0.05),
                pytest.raises(TimeoutError, match="seed_state"),
            ):
                await harness.seed_state("sensor.temp", state_dict)
        finally:
            release_gate.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def test_harness_seed_state_does_not_call_mark_ready(self, tmp_path: Path) -> None:
        """seed_state must NOT call mark_ready() — lifecycle is separate from seeding."""
        harness, proxy = self._make_harness_with_proxy(tmp_path)

        mark_ready_called = False

        def _spy_mark_ready(**_kwargs: object) -> None:
            nonlocal mark_ready_called
            mark_ready_called = True

        proxy.mark_ready = _spy_mark_ready  # pyright: ignore[reportAttributeAccessIssue]

        state_dict = {"entity_id": "sensor.temp", "state": "25", "attributes": {}}
        await harness.seed_state("sensor.temp", state_dict)

        assert not mark_ready_called, "seed_state must not call mark_ready()"


# ---------------------------------------------------------------------------
# now() import invariant
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests: hermetic config closure
# ---------------------------------------------------------------------------


class TestHermeticConfigClosure:
    """_make_hermetic_config() closure-based approach — race-free, cache-retained."""

    def test_hermetic_config_produces_validated_instance(self) -> None:
        """_make_hermetic_config returns a validated AppConfig instance for valid input."""
        from hassette.app.app_config import AppConfig
        from hassette.test_utils.app_harness import _make_hermetic_config

        class _Cfg(AppConfig):
            pass

        class _App:
            pass

        result = _make_hermetic_config(_App, _Cfg, {"instance_name": "test"})
        assert isinstance(result, _Cfg)
        assert result.instance_name == "test"

    def test_hermetic_config_raises_for_invalid(self) -> None:
        """_make_hermetic_config raises AppConfigurationError when validation fails."""
        from hassette.app.app_config import AppConfig
        from hassette.test_utils.app_harness import AppConfigurationError, _make_hermetic_config

        class _RequiredCfg(AppConfig):
            must_be_present: str

        class _App:
            pass

        with pytest.raises(AppConfigurationError) as exc_info:
            _make_hermetic_config(_App, _RequiredCfg, {"instance_name": "test"})

        assert exc_info.value.original_error is not None

    def test_hermetic_cache_is_retained(self) -> None:
        """_HERMETIC_CONFIG_CACHE returns the same subclass on repeated calls for the same config cls."""
        from hassette.app.app_config import AppConfig
        from hassette.test_utils.app_harness import _HERMETIC_CONFIG_CACHE, _make_hermetic_config

        class _CacheCfg(AppConfig):
            pass

        class _App:
            pass

        # Clear cache entry for this class to start fresh
        _HERMETIC_CONFIG_CACHE.pop(_CacheCfg, None)

        _make_hermetic_config(_App, _CacheCfg, {"instance_name": "a"})
        first_entry = _HERMETIC_CONFIG_CACHE.get(_CacheCfg)
        assert first_entry is not None, "Cache must contain an entry after first call"

        first_subclass = first_entry[0]

        _make_hermetic_config(_App, _CacheCfg, {"instance_name": "b"})
        second_entry = _HERMETIC_CONFIG_CACHE.get(_CacheCfg)
        assert second_entry is not None

        second_subclass = second_entry[0]

        assert first_subclass is second_subclass, (
            "Cache must return the same subclass on repeated calls to prevent subclass accumulation"
        )

    def test_hermetic_config_different_dicts_per_call(self) -> None:
        """Repeated calls with different config dicts each produce the correct validated instance."""
        from hassette.app.app_config import AppConfig
        from hassette.test_utils.app_harness import _make_hermetic_config

        class _MultiCfg(AppConfig):
            instance_name: str = "default"

        class _App:
            pass

        r1 = _make_hermetic_config(_App, _MultiCfg, {"instance_name": "first"})
        r2 = _make_hermetic_config(_App, _MultiCfg, {"instance_name": "second"})

        assert r1.instance_name == "first"
        assert r2.instance_name == "second"


# ---------------------------------------------------------------------------
# Tests: TaskBucket exception recorder list
# ---------------------------------------------------------------------------


def _make_task_bucket() -> TaskBucket:
    """Build a TaskBucket with a minimal Hassette mock — bypasses __init__ to avoid Resource wiring."""
    import weakref

    hassette = Mock()
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.log_level = "DEBUG"
    hassette.config.dev_mode = False
    hassette._loop_thread_id = None

    bucket = TaskBucket.__new__(TaskBucket)
    bucket._tasks = weakref.WeakSet()
    bucket._exception_recorders = []
    bucket.hassette = hassette
    bucket.logger = Mock()
    # _unique_name is read by the unique_name property; set directly to avoid parent lookup
    bucket._unique_name = "test_bucket"
    return bucket


class TestTaskBucketExceptionRecorderList:
    """TaskBucket supports multiple concurrent exception recorders (list, LIFO-safe)."""

    def test_install_single_recorder(self) -> None:
        """Installing one recorder results in it being in the list."""
        bucket = _make_task_bucket()
        recorder = Mock()

        bucket.install_exception_recorder(recorder)

        assert recorder in bucket._exception_recorders

    def test_install_multiple_recorders(self) -> None:
        """Multiple recorders can be installed; all appear in the list."""
        bucket = _make_task_bucket()
        r1 = Mock()
        r2 = Mock()

        bucket.install_exception_recorder(r1)
        bucket.install_exception_recorder(r2)

        assert r1 in bucket._exception_recorders
        assert r2 in bucket._exception_recorders

    def test_uninstall_removes_recorder(self) -> None:
        """uninstall_exception_recorder removes the specified recorder."""
        bucket = _make_task_bucket()
        r1 = Mock()

        bucket.install_exception_recorder(r1)
        bucket.uninstall_exception_recorder(r1)

        assert r1 not in bucket._exception_recorders

    def test_uninstall_missing_recorder_noop(self) -> None:
        """Uninstalling a recorder that was never installed is a no-op, not an error."""
        bucket = _make_task_bucket()
        r1 = Mock()  # never installed

        # Should not raise
        bucket.uninstall_exception_recorder(r1)

        assert bucket._exception_recorders == []

    def test_multiple_exception_recorders_lifo(self) -> None:
        """LIFO install/uninstall: last-installed recorder is first removed."""
        bucket = _make_task_bucket()
        r1 = Mock()
        r2 = Mock()

        bucket.install_exception_recorder(r1)
        bucket.install_exception_recorder(r2)

        # Uninstall r2 first (LIFO order)
        bucket.uninstall_exception_recorder(r2)
        assert r2 not in bucket._exception_recorders
        assert r1 in bucket._exception_recorders

        # Then uninstall r1
        bucket.uninstall_exception_recorder(r1)
        assert bucket._exception_recorders == []

    def test_uninstall_idempotent_after_already_uninstalled(self) -> None:
        """Calling uninstall twice for the same recorder is idempotent."""
        bucket = _make_task_bucket()
        r1 = Mock()

        bucket.install_exception_recorder(r1)
        bucket.uninstall_exception_recorder(r1)
        # Second uninstall must not raise
        bucket.uninstall_exception_recorder(r1)

        assert bucket._exception_recorders == []

    async def test_all_recorders_called_on_task_exception(self) -> None:
        """All installed recorders are called when a task raises an exception."""
        calls_r1: list[tuple] = []
        calls_r2: list[tuple] = []

        def r1(task, exc):
            calls_r1.append((task, exc))

        def r2(task, exc):
            calls_r2.append((task, exc))

        bucket = _make_task_bucket()
        bucket.install_exception_recorder(r1)
        bucket.install_exception_recorder(r2)

        err = ValueError("boom")

        async def _boom():
            raise err

        task = asyncio.create_task(_boom())
        bucket.add(task)

        with contextlib.suppress(TimeoutError, ValueError, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)

        await asyncio.sleep(0)  # let done callbacks fire

        assert len(calls_r1) == 1, "r1 must be called once"
        assert len(calls_r2) == 1, "r2 must be called once"
        assert calls_r1[0][1] is err
        assert calls_r2[0][1] is err


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
