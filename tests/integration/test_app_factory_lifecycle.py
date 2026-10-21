"""Integration tests for AppFactory and AppLifecycleService."""

import contextvars
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hassette_wire import ResourceStatus

from hassette.config.classes import AppManifest
from hassette.core.app_factory import AppFactory
from hassette.core.app_lifecycle_common import AppAdmissionMode
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.exceptions import AppPrecheckFailedError, InvalidInheritanceError
from hassette.schemas.app_snapshots import AppInstanceInfo
from hassette.utils import app_utils
from tests.support.app_staging_helpers import clear_loaded_class_caches

if TYPE_CHECKING:
    from hassette import HassetteConfig
    from hassette.app.app import App, AppConfig
    from hassette.testing import HassetteHarness


TEST_APPS_PATH = Path(__file__).parent.parent / "data" / "apps"


def get_app(registry: AppRegistry, key: str, index: int = 0) -> "App[AppConfig]":
    app = registry.get(key, index)
    assert app is not None, f"expected app {key!r}[{index}] to be registered"
    return app


def get_failed_by_key(registry: AppRegistry, app_key: str) -> list[AppInstanceInfo]:
    """Get failed app instances for a specific app_key."""
    snapshot = registry.get_snapshot()
    return [info for info in snapshot.instances if info.error is not None and info.app_key == app_key]


@pytest.fixture
def app_registry() -> AppRegistry:
    """Create a fresh AppRegistry instance."""
    return AppRegistry()


@pytest.fixture
def app_factory(hassette_with_app_handler: "HassetteHarness", app_registry: AppRegistry) -> AppFactory:
    """Create an AppFactory with real Hassette instance."""
    return AppFactory(hassette_with_app_handler.hassette, app_registry)


@pytest.fixture
async def app_lifecycle(hassette_with_app_handler: "HassetteHarness", app_registry: AppRegistry) -> AppLifecycleService:
    """Create an AppLifecycleService with real Hassette instance."""
    lifecycle = AppLifecycleService(hassette_with_app_handler.hassette, parent=None, registry=app_registry)
    yield lifecycle
    await lifecycle.shutdown_all()


def make_manifest(  # factory-local: returns AppManifest, not AppManifestInfo
    app_key: str, filename: str, class_name: str, app_config: dict | list[dict] | None = None, enabled: bool = True
) -> AppManifest:
    """Helper to create AppManifest instances for testing."""
    config = app_config or {"instance_name": app_key}
    return AppManifest(
        app_key=app_key,
        filename=filename,
        class_name=class_name,
        app_dir=TEST_APPS_PATH,
        config=config,  # Use 'config' not 'app_config' to match validation_alias
        enabled=enabled,
        display_name=class_name,
        full_path=TEST_APPS_PATH / filename,
    )


def create_app(
    app_factory: AppFactory, app_registry: AppRegistry, manifest: AppManifest
) -> dict[int, "App[AppConfig]"]:
    """Register ``manifest``, create its instances, and return the running ones."""
    app_registry.set_manifests({manifest.app_key: manifest})
    app_factory.create_instances(manifest.app_key, manifest)
    return app_registry.get_running_apps(manifest.app_key)


async def bring_up_app(
    app_factory: AppFactory, app_lifecycle: AppLifecycleService, app_registry: AppRegistry, manifest: AppManifest
) -> dict[int, "App[AppConfig]"]:
    """Create ``manifest``'s instances and initialize them, returning the created instances."""
    instances = create_app(app_factory, app_registry, manifest)
    await app_lifecycle.initialize_instances(manifest.app_key, instances, manifest)
    return instances


@pytest.fixture
def failing_manifest() -> AppManifest:
    """Manifest for the app whose ``on_initialize()`` always raises."""
    return make_manifest("failing", "failing_init_app.py", "FailingInitApp")


@pytest.fixture
def multi_instance_manifest() -> AppManifest:
    """Single-instance manifest for ``MultiInstanceApp``."""
    return make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")


@pytest.fixture
async def running_multi_instance(
    app_factory: AppFactory,
    app_lifecycle: AppLifecycleService,
    app_registry: AppRegistry,
    multi_instance_manifest: AppManifest,
) -> dict[int, "App[AppConfig]"]:
    """``MultiInstanceApp`` created and initialized; returns its instances."""
    return await bring_up_app(app_factory, app_lifecycle, app_registry, multi_instance_manifest)


@pytest.fixture
async def initialized_failing(
    app_factory: AppFactory,
    app_lifecycle: AppLifecycleService,
    app_registry: AppRegistry,
    failing_manifest: AppManifest,
) -> dict[int, "App[AppConfig]"]:
    """``FailingInitApp`` created and put through its (failing) initialization; returns its instances."""
    return await bring_up_app(app_factory, app_lifecycle, app_registry, failing_manifest)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the class cache before each test."""
    clear_loaded_class_caches()
    yield
    clear_loaded_class_caches()


class TestAppFactoryIntegration:
    """Integration tests for AppFactory with real app classes."""

    def test_factory_loads_real_app_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Verify factory loads actual MyApp class from filesystem."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        create_app(app_factory, app_registry, manifest)

        assert "my_app" in app_registry
        app_instance = get_app(app_registry, "my_app", 0)
        assert app_instance.__class__.__name__ == "MyApp"

    def test_load_class_from_empty_context(self, app_factory: AppFactory):
        """A forced class load succeeds without the Hassette contextvars set (#2478).

        uvicorn runs each request in an empty ``contextvars.Context``, so a web-triggered reload
        reaches the loader with no ambient Hassette instance or config.
        """
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        app_class = contextvars.Context().run(app_factory.load_class, "my_app", manifest, force_reload=True)

        assert app_class is not None
        assert app_class.__name__ == "MyApp"

    def test_factory_creates_real_app_instance(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Verify created instance is actual App subclass with working methods."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        create_app(app_factory, app_registry, manifest)

        app_instance = get_app(app_registry, "my_app", 0)
        # Verify it has expected App attributes
        assert hasattr(app_instance, "bus")
        assert hasattr(app_instance, "scheduler")
        assert hasattr(app_instance, "api")
        assert hasattr(app_instance, "app_config")

    def test_factory_validates_config_with_pydantic(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Config validation works with real AppConfig subclass."""
        manifest = make_manifest(
            "my_app",
            "my_app.py",
            "MyApp",
            app_config={"instance_name": "test_instance", "test_entity": "light.kitchen"},
        )

        create_app(app_factory, app_registry, manifest)

        app_instance = get_app(app_registry, "my_app", 0)
        assert app_instance.app_config.test_entity == "light.kitchen"

    def test_factory_creates_multiple_instances(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Creates separate instances with different configs."""
        manifest = make_manifest(
            "multi_instance",
            "multi_instance_app.py",
            "MultiInstanceApp",
            app_config=[
                {"instance_name": "instance_0", "value": "first"},
                {"instance_name": "instance_1", "value": "second"},
            ],
        )

        create_app(app_factory, app_registry, manifest)

        assert len(app_registry.get_running_apps("multi_instance")) == 2
        assert app_registry.get("multi_instance", 0) is not None
        assert app_registry.get("multi_instance", 1) is not None

    def test_factory_instances_have_unique_configs(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Each instance has its own validated config."""
        manifest = make_manifest(
            "multi_instance",
            "multi_instance_app.py",
            "MultiInstanceApp",
            app_config=[
                {"instance_name": "instance_0", "value": "first"},
                {"instance_name": "instance_1", "value": "second"},
            ],
        )

        create_app(app_factory, app_registry, manifest)

        instance_0 = app_registry.get("multi_instance", 0)
        instance_1 = app_registry.get("multi_instance", 1)
        assert instance_0 is not None
        assert instance_1 is not None
        assert instance_0.app_config.value == "first"
        assert instance_1.app_config.value == "second"

    def test_factory_records_failure_for_invalid_module(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Records failure when module path is wrong."""
        manifest = make_manifest("invalid", "nonexistent_file.py", "SomeClass")

        create_app(app_factory, app_registry, manifest)

        assert "invalid" not in app_registry
        failed = get_failed_by_key(app_registry, "invalid")
        assert len(failed) == 1
        assert failed[0].index == 0

    def test_factory_records_failure_for_missing_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Records failure when class doesn't exist in module."""
        manifest = make_manifest("invalid", "my_app.py", "NonExistentClass")

        create_app(app_factory, app_registry, manifest)

        assert "invalid" not in app_registry
        failed = get_failed_by_key(app_registry, "invalid")
        assert len(failed) == 1

    def test_factory_records_failure_for_invalid_config(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Pydantic validation failure with real config class."""
        # MyAppUserConfig has test_entity as str, not a complex object
        manifest = make_manifest(
            "my_app",
            "my_app.py",
            "MyApp",
            app_config={"instance_name": "test", "test_entity": {"invalid": "type"}},
        )

        create_app(app_factory, app_registry, manifest)

        # Should fail validation
        assert "my_app" not in app_registry or len(app_registry.get_running_apps("my_app")) == 0
        failed = get_failed_by_key(app_registry, "my_app")
        assert len(failed) == 1

    def test_factory_caches_loaded_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Second call returns same class object."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        create_app(app_factory, app_registry, manifest)
        first_instance = get_app(app_registry, "my_app", 0)
        first_class = first_instance.__class__

        # Clear registry but keep class cache
        app_registry.unregister_app("my_app")

        app_factory.create_instances("my_app", manifest)
        second_instance = get_app(app_registry, "my_app", 0)
        second_class = second_instance.__class__

        assert first_class is second_class

    def test_factory_force_reload_reloads_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """force_reload=True reimports the module."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        create_app(app_factory, app_registry, manifest)
        first_instance = get_app(app_registry, "my_app", 0)
        first_class = first_instance.__class__

        # Clear registry
        app_registry.unregister_app("my_app")

        app_factory.create_instances("my_app", manifest, force_reload=True)
        second_instance = get_app(app_registry, "my_app", 0)
        second_class = second_instance.__class__

        # After force reload, it should be a different class object
        assert first_class is not second_class

    def test_factory_force_reload_recovers_previously_failed_class(
        self, app_factory: AppFactory, app_registry: AppRegistry
    ):
        """force_reload=True evicts a cached load failure so a fixed app loads again.

        Regression for #1005: a manual reload of a previously-failed app must re-import
        from disk rather than re-raising the cached failure.
        """
        manifest = make_manifest("my_app", "my_app.py", "MyApp")
        cache_key = app_utils.app_cache_key(manifest.full_path, manifest.class_name)

        # Simulate a prior failed load (e.g. a syntax error the user has since fixed).
        app_utils.FAILED_TO_LOAD_CLASSES[cache_key] = ImportError("boom")
        try:
            # Without force_reload the cached failure blocks loading — no instance is created.
            create_app(app_factory, app_registry, manifest)
            assert "my_app" not in app_registry
            assert cache_key in app_utils.FAILED_TO_LOAD_CLASSES

            # With force_reload the failure is evicted and the app loads from disk.
            app_factory.create_instances("my_app", manifest, force_reload=True)
            assert "my_app" in app_registry
            assert cache_key not in app_utils.FAILED_TO_LOAD_CLASSES
        finally:
            app_utils.FAILED_TO_LOAD_CLASSES.pop(cache_key, None)


class TestAppLifecycleServiceIntegration:
    """Integration tests for AppLifecycleService with real app instances."""

    @pytest.mark.usefixtures("running_multi_instance")
    async def test_lifecycle_initializes_real_app(self, app_registry: AppRegistry):
        """Calls real on_initialize() hook."""
        # Verify the app was initialized (status should be RUNNING after mark_ready)
        app_instance = get_app(app_registry, "multi_instance", 0)
        assert app_instance.status == ResourceStatus.RUNNING

    async def test_lifecycle_marks_app_ready(
        self,
        app_factory: AppFactory,
        app_lifecycle: AppLifecycleService,
        app_registry: AppRegistry,
        multi_instance_manifest: AppManifest,
    ):
        """App status transitions to RUNNING after init."""
        instances = create_app(app_factory, app_registry, multi_instance_manifest)

        # Before initialization
        app_instance = get_app(app_registry, "multi_instance", 0)
        assert app_instance.status != ResourceStatus.RUNNING

        await app_lifecycle.initialize_instances("multi_instance", instances, multi_instance_manifest)

        # After initialization
        assert app_instance.status == ResourceStatus.RUNNING

    async def test_lifecycle_initializes_multiple_instances(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleService, app_registry: AppRegistry
    ):
        """All instances in dict get initialized."""
        manifest = make_manifest(
            "multi_instance",
            "multi_instance_app.py",
            "MultiInstanceApp",
            app_config=[
                {"instance_name": "instance_0", "value": "first"},
                {"instance_name": "instance_1", "value": "second"},
            ],
        )
        await bring_up_app(app_factory, app_lifecycle, app_registry, manifest)

        # Both instances should be running
        instance_0 = app_registry.get("multi_instance", 0)
        instance_1 = app_registry.get("multi_instance", 1)
        assert instance_0 is not None
        assert instance_1 is not None
        assert instance_0.status == ResourceStatus.RUNNING
        assert instance_1.status == ResourceStatus.RUNNING

    async def test_lifecycle_handles_init_exception(
        self, app_registry: AppRegistry, initialized_failing: dict[int, "App[AppConfig]"]
    ):
        """App raising in on_initialize() is caught (the fixture's initialization did not raise)."""
        # App should be marked as stopped
        app_instance = app_registry.get("failing", 0)
        assert app_instance is None, "Failed app instance should be removed from registry after init failure"
        assert initialized_failing[0].status == ResourceStatus.STOPPED, (
            "Failed app instance should be marked as STOPPED after init failure"
        )

    @pytest.mark.usefixtures("initialized_failing")
    async def test_lifecycle_records_exception_failure(self, app_registry: AppRegistry):
        """Exception recorded in registry."""
        # Failure should be recorded
        failed = get_failed_by_key(app_registry, "failing")
        assert len(failed) == 1
        assert failed[0].index == 0
        assert "Intentional init failure" in failed[0].error_message

    async def test_lifecycle_logs_init_failure_exactly_once(
        self,
        app_factory: AppFactory,
        app_lifecycle: AppLifecycleService,
        app_registry: AppRegistry,
        failing_manifest: AppManifest,
        caplog: pytest.LogCaptureFixture,
    ):
        """A single ``on_initialize()`` failure produces exactly one ERROR-level log record.

        Regression test for #1826: the same exception used to be logged as three stacked
        ERROR tracebacks -- ``run_hooks()``'s ``handle_failed()`` call, the initialization
        coordinator's exception observer, and ``AppLifecycleService.initialize_instances()``'s
        own catch -- even though only the outermost, decision-owning layer for apps
        (``AppLifecycleService``) needs to surface at ERROR. The lower two are demoted to
        DEBUG rather than removed, so the traceback stays available for anyone with DEBUG
        logging enabled.
        """
        instances = create_app(app_factory, app_registry, failing_manifest)

        # Each Resource's own logger gets an explicit level set (INFO by default) in
        # _setup_logger(), which shadows the ancestor "hassette" logger's level for
        # isEnabledFor() checks -- caplog.at_level(logger="hassette") alone would not
        # unblock DEBUG records from these specific loggers.
        for inst in instances.values():
            inst.logger.setLevel(logging.DEBUG)
        app_lifecycle.logger.setLevel(logging.DEBUG)

        with caplog.at_level(logging.DEBUG, logger="hassette"):
            await app_lifecycle.initialize_instances("failing", instances, failing_manifest)

        # Only count records from the loggers involved in this init failure. The module-scoped
        # harness autostarts the configured test apps (MyAppSync schedules a job ~1s after boot),
        # so unrelated framework errors can land inside this capture window.
        init_failure_loggers = {app_lifecycle.logger.name, *(inst.logger.name for inst in instances.values())}
        init_records = [record for record in caplog.records if record.name in init_failure_loggers]

        error_records = [record for record in init_records if record.levelno == logging.ERROR]
        assert len(error_records) == 1, (
            f"expected exactly one ERROR record for the init failure, got {len(error_records)}: "
            f"{[record.getMessage() for record in error_records]}"
        )
        surviving_message = error_records[0].getMessage()
        assert "Intentional init failure" in surviving_message
        # AppLifecycleService embeds the traceback as text (get_short_traceback()) rather than
        # structured exc_info, but it must still carry enough of the stack to show the failing
        # app's own file:line, not just framework frames.
        assert "Traceback (most recent call last)" in surviving_message
        assert "failing_init_app.py" in surviving_message

        # The demoted lower-layer logs should still exist at DEBUG, not be silently dropped.
        debug_messages = [record.getMessage() for record in init_records if record.levelno == logging.DEBUG]
        assert any("failed" in message and "RuntimeError" in message for message in debug_messages), (
            "run_hooks()'s handle_failed() log should be demoted to DEBUG, not removed entirely"
        )
        assert any("unhandled exception" in message for message in debug_messages), (
            "the initialization coordinator's exception observer should be demoted to DEBUG, not removed entirely"
        )

    async def test_lifecycle_continues_after_failed_instance(
        self,
        app_factory: AppFactory,
        app_lifecycle: AppLifecycleService,
        app_registry: AppRegistry,
        multi_instance_manifest: AppManifest,
        failing_manifest: AppManifest,
    ):
        """Other instances still initialize after one fails."""
        # Create failing app first
        app_registry.set_manifests({"failing": failing_manifest})
        app_factory.create_instances("failing", failing_manifest)

        # Create succeeding app
        app_registry.set_manifests({"failing": failing_manifest, "multi_instance": multi_instance_manifest})
        app_factory.create_instances("multi_instance", multi_instance_manifest)

        # Initialize all together
        failing_instances = app_registry.get_running_apps("failing")
        success_instances = app_registry.get_running_apps("multi_instance")

        await app_lifecycle.initialize_instances("failing", failing_instances, failing_manifest)
        await app_lifecycle.initialize_instances("multi_instance", success_instances, multi_instance_manifest)

        # Failing app should be stopped
        assert failing_instances[0].status == ResourceStatus.STOPPED
        assert app_registry.get("failing", 0) is None, (
            "Failed app instance should be removed from registry after init failure"
        )
        # Success app should be running
        success_instance = get_app(app_registry, "multi_instance", 0)
        assert success_instance.status == ResourceStatus.RUNNING

    @pytest.mark.usefixtures("running_multi_instance")
    async def test_lifecycle_shuts_down_real_app(self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry):
        """Calls real shutdown() and cleanup() methods."""
        app_instance = get_app(app_registry, "multi_instance", 0)
        assert app_instance.status == ResourceStatus.RUNNING

        # Shutdown should not raise
        await app_lifecycle.shutdown_instance(app_instance)

    @pytest.mark.usefixtures("running_multi_instance")
    async def test_lifecycle_shutdown_all_clears_registry(
        self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry
    ):
        """After shutdown_all, registry is empty."""
        assert len(app_registry.all_apps()) > 0

        await app_lifecycle.shutdown_all()

        assert len(app_registry.all_apps()) == 0


class TestFullIntegrationFlow:
    """Full integration flow tests for Factory → Lifecycle pipeline."""

    async def test_full_flow_create_and_initialize(
        self,
        app_factory: AppFactory,
        app_lifecycle: AppLifecycleService,
        app_registry: AppRegistry,
        multi_instance_manifest: AppManifest,
    ):
        """Factory creates, lifecycle initializes, app runs."""
        # Create
        instances = create_app(app_factory, app_registry, multi_instance_manifest)
        assert "multi_instance" in app_registry

        # Initialize
        await app_lifecycle.initialize_instances("multi_instance", instances, multi_instance_manifest)

        # Verify running
        app = get_app(app_registry, "multi_instance", 0)
        assert app.status == ResourceStatus.RUNNING

    async def test_full_flow_with_registry_state(
        self,
        app_factory: AppFactory,
        app_lifecycle: AppLifecycleService,
        app_registry: AppRegistry,
        multi_instance_manifest: AppManifest,
    ):
        """Verify registry state at each step."""
        # Before creation
        assert app_registry.get("multi_instance", 0) is None

        # After creation
        instances = create_app(app_factory, app_registry, multi_instance_manifest)
        app = get_app(app_registry, "multi_instance", 0)
        assert app.status == ResourceStatus.NOT_STARTED

        # After initialization
        await app_lifecycle.initialize_instances("multi_instance", instances, multi_instance_manifest)
        assert app.status == ResourceStatus.RUNNING

        # After shutdown — asserted here (not deferred to fixture teardown), so the
        # explicit call stays; the fixture's own shutdown_all() afterward is a harmless no-op.
        await app_lifecycle.shutdown_all()
        assert app_registry.get("multi_instance", 0) is None

    async def test_full_flow_multiple_apps(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleService, app_registry: AppRegistry
    ):
        """Multiple app types created and initialized together."""
        manifest1 = make_manifest(
            "multi1",
            "multi_instance_app.py",
            "MultiInstanceApp",
            app_config={"instance_name": "multi1_inst", "value": "v1"},
        )
        manifest2 = make_manifest("my_app", "my_app.py", "MyApp")

        app_registry.set_manifests({"multi1": manifest1, "my_app": manifest2})

        # Create both
        app_factory.create_instances("multi1", manifest1)
        app_factory.create_instances("my_app", manifest2)

        assert "multi1" in app_registry
        assert "my_app" in app_registry

        # Initialize both
        instances1 = app_registry.get_running_apps("multi1")
        instances2 = app_registry.get_running_apps("my_app")
        await app_lifecycle.initialize_instances("multi1", instances1, manifest1)
        await app_lifecycle.initialize_instances("my_app", instances2, manifest2)

        # Both should be running
        multi1_instance = app_registry.get("multi1", 0)
        my_app_instance = app_registry.get("my_app", 0)
        assert multi1_instance is not None
        assert my_app_instance is not None
        assert multi1_instance.status == ResourceStatus.RUNNING
        assert my_app_instance.status == ResourceStatus.RUNNING

    @pytest.mark.usefixtures("running_multi_instance")
    async def test_snapshot_shows_running_apps(self, app_registry: AppRegistry):
        """Running apps appear in snapshot.instances (running_count)."""
        snapshot = app_registry.get_snapshot()
        assert snapshot.running_count == 1
        assert any(i.app_key == "multi_instance" and i.error is None for i in snapshot.instances)

    @pytest.mark.usefixtures("initialized_failing")
    async def test_snapshot_shows_failed_apps(self, app_registry: AppRegistry):
        """Failed apps appear in snapshot.instances (failed_count)."""
        snapshot = app_registry.get_snapshot()
        assert snapshot.failed_count == 1
        assert any(i.app_key == "failing" and i.error is not None for i in snapshot.instances)


class TestAppRestartPreservesChildren:
    """Verify that an App's children survive a shutdown + re-initialize cycle."""

    @pytest.mark.usefixtures("running_multi_instance")
    async def test_restart_round_trip(self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry):
        """Shutdown propagates to children, re-initialize restores them all to ready."""
        app_instance = get_app(app_registry, "multi_instance", 0)
        assert app_instance.status == ResourceStatus.RUNNING

        # All four children should be ready after init
        assert app_instance.bus.is_ready(), "Bus should be ready after initialize"
        assert app_instance.scheduler.is_ready(), "Scheduler should be ready after initialize"
        assert app_instance.api.is_ready(), "Api should be ready after initialize"
        assert app_instance.states.is_ready(), "StateManager should be ready after initialize"

        # Shutdown
        await app_lifecycle.shutdown_instance(app_instance)

        assert app_instance.status == ResourceStatus.STOPPED
        assert not app_instance.bus.is_ready(), "Bus should not be ready after shutdown"
        assert not app_instance.scheduler.is_ready(), "Scheduler should not be ready after shutdown"
        assert not app_instance.api.is_ready(), "Api should not be ready after shutdown"
        assert not app_instance.states.is_ready(), "StateManager should not be ready after shutdown"

        # Re-initialize
        await app_instance.initialize()

        assert app_instance.status == ResourceStatus.RUNNING, "App should be RUNNING after re-initialize"
        assert app_instance.bus.is_ready(), "Bus should be ready after re-initialize"
        assert app_instance.scheduler.is_ready(), "Scheduler should be ready after re-initialize"
        assert app_instance.api.is_ready(), "Api should be ready after re-initialize"
        assert app_instance.states.is_ready(), "StateManager should be ready after re-initialize"

        # Clean up
        await app_instance.shutdown()


class TestInvalidInheritanceBlocksLoad:
    """An InvalidInheritanceError from validate_app fails the class load instead of being swallowed."""

    def test_precheck_fails_for_invalid_inheritance(self, test_config: "HassetteConfig"):
        """run_apps_pre_check reports the app as failed and blocks startup."""
        manifest = make_manifest("invalid_inheritance", "invalid_inheritance_app.py", "InvalidInheritanceApp")
        apps = test_config.apps.model_copy(update={"manifests": {"invalid_inheritance": manifest}})
        config = test_config.model_copy(update={"apps": apps})

        with pytest.raises(AppPrecheckFailedError):
            app_utils.run_apps_pre_check(config)

        assert isinstance(
            app_utils.get_class_load_error(manifest.full_path, manifest.class_name), InvalidInheritanceError
        )

    async def test_start_app_records_failure_for_invalid_inheritance(
        self, app_lifecycle: AppLifecycleService, app_registry: AppRegistry
    ):
        """start_app creates no instance and records the inheritance error as the app's failure."""
        manifest = make_manifest("invalid_inheritance", "invalid_inheritance_app.py", "InvalidInheritanceApp")
        app_registry.set_manifests({"invalid_inheritance": manifest})

        await app_lifecycle.start_app("invalid_inheritance", admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

        assert "invalid_inheritance" not in app_registry
        failed = get_failed_by_key(app_registry, "invalid_inheritance")
        assert len(failed) == 1
        assert isinstance(failed[0].error, InvalidInheritanceError)
