"""Integration tests for AppFactory and AppLifecycleManager."""

from pathlib import Path

import pytest

from hassette import Hassette
from hassette.config.classes import AppManifest
from hassette.core.app_factory import AppFactory
from hassette.core.app_lifecycle import AppLifecycleManager
from hassette.core.app_registry import AppInstanceInfo, AppRegistry
from hassette.types.enums import ResourceStatus
from hassette.utils import app_utils


def get_failed_by_key(registry: AppRegistry, app_key: str) -> list[AppInstanceInfo]:
    """Get failed app instances for a specific app_key."""
    snapshot = registry.get_snapshot()
    return [info for info in snapshot.failed if info.app_key == app_key]


TEST_APPS_PATH = Path(__file__).parent.parent / "data" / "apps"


def clear_class_cache():
    """Clear the loaded and failed class caches."""
    app_utils.LOADED_CLASSES.clear()
    app_utils.FAILED_TO_LOAD_CLASSES.clear()


@pytest.fixture
def app_registry() -> AppRegistry:
    """Create a fresh AppRegistry instance."""
    return AppRegistry()


@pytest.fixture
def app_factory(hassette_with_app_handler: Hassette, app_registry: AppRegistry) -> AppFactory:
    """Create an AppFactory with real Hassette instance."""
    return AppFactory(hassette_with_app_handler, app_registry)


@pytest.fixture
def app_lifecycle(hassette_with_app_handler: Hassette, app_registry: AppRegistry) -> AppLifecycleManager:
    """Create an AppLifecycleManager with real Hassette instance."""
    return AppLifecycleManager(hassette_with_app_handler, app_registry)


def make_manifest(
    app_key: str, filename: str, class_name: str, app_config: dict | list[dict] | None = None, enabled: bool = True
) -> AppManifest:
    """Helper to create AppManifest instances for testing."""
    config = app_config or {"instance_name": f"{class_name}.0"}
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


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the class cache before each test."""
    clear_class_cache()
    yield
    clear_class_cache()


class TestAppFactoryIntegration:
    """Integration tests for AppFactory with real app classes."""

    def test_factory_loads_real_app_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Verify factory loads actual MyApp class from filesystem."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        app_factory.create_instances("my_app", manifest)

        assert "my_app" in app_registry.apps
        assert 0 in app_registry.apps["my_app"]
        app_instance = app_registry.apps["my_app"][0]
        assert app_instance.__class__.__name__ == "MyApp"

    def test_factory_creates_real_app_instance(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Verify created instance is actual App subclass with working methods."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        app_factory.create_instances("my_app", manifest)

        app_instance = app_registry.apps["my_app"][0]
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

        app_factory.create_instances("my_app", manifest)

        app_instance = app_registry.apps["my_app"][0]
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

        app_factory.create_instances("multi_instance", manifest)

        assert len(app_registry.apps["multi_instance"]) == 2
        assert 0 in app_registry.apps["multi_instance"]
        assert 1 in app_registry.apps["multi_instance"]

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

        app_factory.create_instances("multi_instance", manifest)

        instance_0 = app_registry.apps["multi_instance"][0]
        instance_1 = app_registry.apps["multi_instance"][1]
        assert instance_0.app_config.value == "first"
        assert instance_1.app_config.value == "second"

    def test_factory_records_failure_for_invalid_module(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Records failure when module path is wrong."""
        manifest = make_manifest("invalid", "nonexistent_file.py", "SomeClass")

        app_factory.create_instances("invalid", manifest)

        assert "invalid" not in app_registry.apps
        failed = get_failed_by_key(app_registry, "invalid")
        assert len(failed) == 1
        assert failed[0].index == 0

    def test_factory_records_failure_for_missing_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Records failure when class doesn't exist in module."""
        manifest = make_manifest("invalid", "my_app.py", "NonExistentClass")

        app_factory.create_instances("invalid", manifest)

        assert "invalid" not in app_registry.apps
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

        app_factory.create_instances("my_app", manifest)

        # Should fail validation
        assert "my_app" not in app_registry.apps or len(app_registry.apps.get("my_app", {})) == 0
        failed = get_failed_by_key(app_registry, "my_app")
        assert len(failed) == 1

    def test_factory_caches_loaded_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """Second call returns same class object."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        app_factory.create_instances("my_app", manifest)
        first_class = app_registry.apps["my_app"][0].__class__

        # Clear registry but keep class cache
        app_registry.unregister_app("my_app")

        app_factory.create_instances("my_app", manifest)
        second_class = app_registry.apps["my_app"][0].__class__

        assert first_class is second_class

    def test_factory_force_reload_reloads_class(self, app_factory: AppFactory, app_registry: AppRegistry):
        """force_reload=True reimports the module."""
        manifest = make_manifest("my_app", "my_app.py", "MyApp")

        app_factory.create_instances("my_app", manifest)
        first_class = app_registry.apps["my_app"][0].__class__

        # Clear registry
        app_registry.unregister_app("my_app")

        app_factory.create_instances("my_app", manifest, force_reload=True)
        second_class = app_registry.apps["my_app"][0].__class__

        # After force reload, it should be a different class object
        assert first_class is not second_class


class TestAppLifecycleManagerIntegration:
    """Integration tests for AppLifecycleManager with real app instances."""

    async def test_lifecycle_initializes_real_app(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleManager, app_registry: AppRegistry
    ):
        """Calls real on_initialize() hook."""
        manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"multi_instance": manifest})

        app_factory.create_instances("multi_instance", manifest)
        instances = app_registry.get_apps_by_key("multi_instance")

        await app_lifecycle.initialize_instances("multi_instance", instances, manifest)

        # Verify the app was initialized (status should be RUNNING after mark_ready)
        app_instance = app_registry.apps["multi_instance"][0]
        assert app_instance.status == ResourceStatus.RUNNING

    async def test_lifecycle_marks_app_ready(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleManager, app_registry: AppRegistry
    ):
        """App status transitions to RUNNING after init."""
        manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"multi_instance": manifest})

        app_factory.create_instances("multi_instance", manifest)
        instances = app_registry.get_apps_by_key("multi_instance")

        # Before initialization
        app_instance = app_registry.apps["multi_instance"][0]
        assert app_instance.status != ResourceStatus.RUNNING

        await app_lifecycle.initialize_instances("multi_instance", instances, manifest)

        # After initialization
        assert app_instance.status == ResourceStatus.RUNNING

    async def test_lifecycle_initializes_multiple_instances(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleManager, app_registry: AppRegistry
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
        app_registry.set_manifests({"multi_instance": manifest})

        app_factory.create_instances("multi_instance", manifest)
        instances = app_registry.get_apps_by_key("multi_instance")

        await app_lifecycle.initialize_instances("multi_instance", instances, manifest)

        # Both instances should be running
        assert app_registry.apps["multi_instance"][0].status == ResourceStatus.RUNNING
        assert app_registry.apps["multi_instance"][1].status == ResourceStatus.RUNNING

    async def test_lifecycle_handles_init_exception(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleManager, app_registry: AppRegistry
    ):
        """App raising in on_initialize() is caught."""
        manifest = make_manifest("failing", "failing_init_app.py", "FailingInitApp")
        app_registry.set_manifests({"failing": manifest})

        app_factory.create_instances("failing", manifest)
        instances = app_registry.get_apps_by_key("failing")

        # Should not raise
        await app_lifecycle.initialize_instances("failing", instances, manifest)

        # App should be marked as stopped
        app_instance = app_registry.get("failing", 0)
        assert app_instance is None, "Failed app instance should be removed from registry after init failure"
        assert instances[0].status == ResourceStatus.STOPPED, (
            "Failed app instance should be marked as STOPPED after init failure"
        )

    async def test_lifecycle_records_exception_failure(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleManager, app_registry: AppRegistry
    ):
        """Exception recorded in registry."""
        manifest = make_manifest("failing", "failing_init_app.py", "FailingInitApp")
        app_registry.set_manifests({"failing": manifest})

        app_factory.create_instances("failing", manifest)
        instances = app_registry.get_apps_by_key("failing")

        await app_lifecycle.initialize_instances("failing", instances, manifest)

        # Failure should be recorded
        failed = get_failed_by_key(app_registry, "failing")
        assert len(failed) == 1
        assert failed[0].index == 0
        assert "Intentional init failure" in failed[0].error_message

    async def test_lifecycle_continues_after_failed_instance(
        self, hassette_with_app_handler: Hassette, app_registry: AppRegistry
    ):
        """Other instances still initialize after one fails."""
        # Create a custom setup with one failing and one succeeding app
        factory = AppFactory(hassette_with_app_handler, app_registry)
        lifecycle = AppLifecycleManager(hassette_with_app_handler, app_registry)

        # Create failing app first
        failing_manifest = make_manifest("failing", "failing_init_app.py", "FailingInitApp")
        app_registry.set_manifests({"failing": failing_manifest})
        factory.create_instances("failing", failing_manifest)

        # Create succeeding app
        success_manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"failing": failing_manifest, "multi_instance": success_manifest})
        factory.create_instances("multi_instance", success_manifest)

        # Initialize all together
        failing_instances = app_registry.get_apps_by_key("failing")
        success_instances = app_registry.get_apps_by_key("multi_instance")

        await lifecycle.initialize_instances("failing", failing_instances, failing_manifest)
        await lifecycle.initialize_instances("multi_instance", success_instances, success_manifest)

        # Failing app should be stopped
        assert failing_instances[0].status == ResourceStatus.STOPPED
        assert app_registry.get("failing", 0) is None, (
            "Failed app instance should be removed from registry after init failure"
        )
        # Success app should be running
        assert app_registry.get("multi_instance", 0) is not None
        assert app_registry.get("multi_instance", 0).status == ResourceStatus.RUNNING

    async def test_lifecycle_shuts_down_real_app(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleManager, app_registry: AppRegistry
    ):
        """Calls real shutdown() and cleanup() methods."""
        manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"multi_instance": manifest})

        app_factory.create_instances("multi_instance", manifest)
        instances = app_registry.get_apps_by_key("multi_instance")
        await app_lifecycle.initialize_instances("multi_instance", instances, manifest)

        app_instance = app_registry.apps["multi_instance"][0]
        assert app_instance.status == ResourceStatus.RUNNING

        # Shutdown should not raise
        await app_lifecycle.shutdown_instance(app_instance)

    async def test_lifecycle_shutdown_all_clears_registry(
        self, app_factory: AppFactory, app_lifecycle: AppLifecycleManager, app_registry: AppRegistry
    ):
        """After shutdown_all, registry is empty."""
        manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"multi_instance": manifest})

        app_factory.create_instances("multi_instance", manifest)
        instances = app_registry.get_apps_by_key("multi_instance")
        await app_lifecycle.initialize_instances("multi_instance", instances, manifest)

        assert len(app_registry.all_apps()) > 0

        await app_lifecycle.shutdown_all()

        assert len(app_registry.all_apps()) == 0


class TestFullIntegrationFlow:
    """Full integration flow tests for Factory → Lifecycle pipeline."""

    async def test_full_flow_create_and_initialize(
        self, hassette_with_app_handler: Hassette, app_registry: AppRegistry
    ):
        """Factory creates, lifecycle initializes, app runs."""
        factory = AppFactory(hassette_with_app_handler, app_registry)
        lifecycle = AppLifecycleManager(hassette_with_app_handler, app_registry)

        manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"multi_instance": manifest})

        # Create
        factory.create_instances("multi_instance", manifest)
        assert "multi_instance" in app_registry.apps

        # Initialize
        instances = app_registry.get_apps_by_key("multi_instance")
        await lifecycle.initialize_instances("multi_instance", instances, manifest)

        # Verify running
        app = app_registry.get("multi_instance", 0)
        assert app is not None
        assert app.status == ResourceStatus.RUNNING

    async def test_full_flow_with_registry_state(self, hassette_with_app_handler: Hassette, app_registry: AppRegistry):
        """Verify registry state at each step."""
        factory = AppFactory(hassette_with_app_handler, app_registry)
        lifecycle = AppLifecycleManager(hassette_with_app_handler, app_registry)

        manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"multi_instance": manifest})

        # Before creation
        assert app_registry.get("multi_instance", 0) is None

        # After creation
        factory.create_instances("multi_instance", manifest)
        app = app_registry.get("multi_instance", 0)
        assert app is not None
        assert app.status == ResourceStatus.NOT_STARTED

        # After initialization
        instances = app_registry.get_apps_by_key("multi_instance")
        await lifecycle.initialize_instances("multi_instance", instances, manifest)
        assert app.status == ResourceStatus.RUNNING

        # After shutdown
        await lifecycle.shutdown_all()
        assert app_registry.get("multi_instance", 0) is None

    async def test_full_flow_multiple_apps(self, hassette_with_app_handler: Hassette, app_registry: AppRegistry):
        """Multiple app types created and initialized together."""
        factory = AppFactory(hassette_with_app_handler, app_registry)
        lifecycle = AppLifecycleManager(hassette_with_app_handler, app_registry)

        manifest1 = make_manifest(
            "multi1",
            "multi_instance_app.py",
            "MultiInstanceApp",
            app_config={"instance_name": "multi1_inst", "value": "v1"},
        )
        manifest2 = make_manifest("my_app", "my_app.py", "MyApp")

        app_registry.set_manifests({"multi1": manifest1, "my_app": manifest2})

        # Create both
        factory.create_instances("multi1", manifest1)
        factory.create_instances("my_app", manifest2)

        assert "multi1" in app_registry.apps
        assert "my_app" in app_registry.apps

        # Initialize both
        instances1 = app_registry.get_apps_by_key("multi1")
        instances2 = app_registry.get_apps_by_key("my_app")
        await lifecycle.initialize_instances("multi1", instances1, manifest1)
        await lifecycle.initialize_instances("my_app", instances2, manifest2)

        # Both should be running
        assert app_registry.get("multi1", 0).status == ResourceStatus.RUNNING
        assert app_registry.get("my_app", 0).status == ResourceStatus.RUNNING

    async def test_snapshot_shows_running_apps(self, hassette_with_app_handler: Hassette, app_registry: AppRegistry):
        """Running apps appear in snapshot.running."""
        factory = AppFactory(hassette_with_app_handler, app_registry)
        lifecycle = AppLifecycleManager(hassette_with_app_handler, app_registry)

        manifest = make_manifest("multi_instance", "multi_instance_app.py", "MultiInstanceApp")
        app_registry.set_manifests({"multi_instance": manifest})

        factory.create_instances("multi_instance", manifest)
        instances = app_registry.get_apps_by_key("multi_instance")
        await lifecycle.initialize_instances("multi_instance", instances, manifest)

        snapshot = app_registry.get_snapshot()
        assert snapshot.running_count == 1
        assert "multi_instance" in snapshot.running_apps

    async def test_snapshot_shows_failed_apps(self, hassette_with_app_handler: Hassette, app_registry: AppRegistry):
        """Failed apps appear in snapshot.failed."""
        factory = AppFactory(hassette_with_app_handler, app_registry)
        lifecycle = AppLifecycleManager(hassette_with_app_handler, app_registry)

        manifest = make_manifest("failing", "failing_init_app.py", "FailingInitApp")
        app_registry.set_manifests({"failing": manifest})

        factory.create_instances("failing", manifest)
        instances = app_registry.get_apps_by_key("failing")
        await lifecycle.initialize_instances("failing", instances, manifest)

        snapshot = app_registry.get_snapshot()
        assert snapshot.failed_count == 1
        assert "failing" in snapshot.failed_apps
