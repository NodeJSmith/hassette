"""Unit tests for AppFactory."""

import logging
from typing import cast
from unittest.mock import Mock, patch

import pytest

from hassette.core.app_factory import AppFactory
from hassette.core.app_registry import AppRegistry


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance."""
    return Mock()


@pytest.fixture
def mock_registry():
    """Create a mock AppRegistry instance."""
    registry = Mock()
    registry.register_app = Mock()
    registry.record_failure = Mock()
    return cast("AppRegistry", registry)


@pytest.fixture
def mock_manifest():
    """Create a mock AppManifest instance."""
    manifest = Mock()
    manifest.full_path = "/path/to/app.py"
    manifest.class_name = "TestApp"
    manifest.display_name = "test_app"
    manifest.app_config = {"instance_name": "test_instance"}
    return manifest


@pytest.fixture
def factory(mock_hassette, mock_registry):
    """Create an AppFactory instance with mocked dependencies."""
    # Ensure propagate=True so caplog can capture logs even if integration
    # tests ran first and set propagate=False on the hassette logger.
    logging.getLogger("hassette").propagate = True
    return AppFactory(mock_hassette, mock_registry)


class TestAppFactoryInit:
    def test_init_stores_hassette_and_registry(self, mock_hassette, mock_registry):
        """Verify constructor stores references correctly."""
        factory = AppFactory(mock_hassette, mock_registry)

        assert factory.hassette is mock_hassette
        assert factory.registry is mock_registry


class TestAppFactoryCreateInstances:
    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_success_single_config(
        self,
        mock_load_class,
        factory: AppFactory,
        mock_registry: AppRegistry,
        mock_manifest,
    ):
        """Successfully creates single app instance from dict config."""
        mock_load_class.return_value = mock_app_class = Mock()

        factory.create_instances("test_app", mock_manifest)

        mock_app_class.create.assert_called_once()
        mock_registry.register_app.assert_called_once_with("test_app", 0, mock_app_class.create.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_success_multiple_configs(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Creates multiple instances from list of configs."""
        mock_load_class.return_value = mock_app_class = Mock()
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
        ]

        factory.create_instances("test_app", mock_manifest)

        assert mock_app_class.create.call_count == 2
        assert mock_registry.register_app.call_count == 2
        mock_registry.register_app.assert_any_call("test_app", 0, mock_app_class.create.return_value)
        mock_registry.register_app.assert_any_call("test_app", 1, mock_app_class.create.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_empty_config(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Handles empty/None app_config gracefully."""
        mock_manifest.app_config = None
        mock_load_class.return_value = mock_app_class = Mock()

        factory.create_instances("test_app", mock_manifest)

        mock_app_class.create.assert_not_called()
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_create_instances_class_load_failure(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure at index 0 when class loading fails."""
        cached_error = ValueError("Failed to load")
        mock_get_error.return_value = cached_error

        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once_with("test_app", 0, cached_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_missing_instance_name(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure for config missing instance_name, continues with others."""
        mock_manifest.app_config = [
            {"other_field": "value"},  # Missing instance_name
            {"instance_name": "valid_instance"},
        ]
        mock_load_class.return_value = mock_app_class = Mock()

        factory.create_instances("test_app", mock_manifest)

        # First config should fail
        assert mock_registry.record_failure.call_count == 1
        call_args = mock_registry.record_failure.call_args
        assert call_args[0][0] == "test_app"
        assert call_args[0][1] == 0
        assert isinstance(call_args[0][2], ValueError)

        # Second config should succeed
        mock_registry.register_app.assert_called_once_with("test_app", 1, mock_app_class.create.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_validation_failure(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure when Pydantic validation fails."""
        mock_app_class = Mock(__name__="TestApp")

        validation_error = ValueError("Validation failed")
        mock_app_class.app_config_cls.model_validate.side_effect = validation_error
        mock_load_class.return_value = mock_app_class

        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once_with("test_app", 0, validation_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_app_create_failure(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure when App.create() raises exception."""
        create_error = RuntimeError("Create failed")
        mock_app_class = Mock(__name__="TestApp")

        mock_app_class.create.side_effect = create_error
        mock_load_class.return_value = mock_app_class
        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once_with("test_app", 0, create_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_sets_manifest_on_class(self, mock_load_class, factory: AppFactory, mock_manifest):
        """Verifies app_class.app_manifest = manifest is called."""
        mock_load_class.return_value = mock_app_class = Mock()

        factory.create_instances("test_app", mock_manifest)

        assert mock_app_class.app_manifest is mock_manifest

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_registers_each_app(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Verifies registry.register_app() called for each successful instance."""

        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
            {"instance_name": "instance_2"},
        ]
        mock_load_class.return_value = Mock()

        factory.create_instances("test_app", mock_manifest)

        assert mock_registry.register_app.call_count == 3

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_create_instances_force_reload(self, mock_loaded, mock_load_class, factory: AppFactory, mock_manifest):
        """Passes force_reload=True through to _load_class()."""
        mock_load_class.return_value = Mock()

        factory.create_instances("test_app", mock_manifest, force_reload=True)

        # When force_reload=True, should call load_app_class_from_manifest even if already loaded
        mock_load_class.assert_called_once_with(mock_manifest, force_reload=True)


class TestAppFactoryLoadClass:
    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_load_class_fresh_load_success(self, mock_load_class, factory: AppFactory, mock_manifest):
        """Loads class when not cached."""
        mock_load_class.return_value = mock_app_class = Mock()

        result = factory._load_class("test_app", mock_manifest, force_reload=False)

        assert result is mock_app_class
        mock_load_class.assert_called_once()

    @patch("hassette.core.app_factory.get_loaded_class")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_load_class_returns_cached(self, mock_loaded, mock_get_loaded, factory: AppFactory, mock_manifest):
        """Returns cached class when already loaded."""
        mock_get_loaded.return_value = mock_app_class = Mock()

        result = factory._load_class("test_app", mock_manifest, force_reload=False)

        assert result is mock_app_class
        mock_get_loaded.assert_called_once_with(mock_manifest.full_path, mock_manifest.class_name)

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    def test_load_class_returns_none_when_previously_failed(self, mock_failed, factory: AppFactory, mock_manifest):
        """Returns None for previously failed classes."""

        result = factory._load_class("test_app", mock_manifest, force_reload=False)

        assert result is None

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_load_class_force_reload_clears_cache(
        self, mock_loaded, mock_load_class, factory: AppFactory, mock_manifest
    ):
        """Force reload attempts fresh load even if cached."""
        mock_load_class.return_value = mock_app_class = Mock()

        result = factory._load_class("test_app", mock_manifest, force_reload=True)

        assert result is mock_app_class
        mock_load_class.assert_called_once_with(mock_manifest, force_reload=True)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_load_class_logs_error_on_failure(self, mock_load_class, factory: AppFactory, caplog, mock_manifest):
        """Logs error with traceback on load failure."""
        mock_load_class.side_effect = ImportError("Module not found")

        result = factory._load_class("test_app", mock_manifest, force_reload=False)

        assert result is None
        assert "Failed to load app class" in caplog.text


class TestAppFactoryGetLoadError:
    @patch("hassette.core.app_factory.get_class_load_error")
    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    def test_get_load_error_returns_cached_exception(
        self, mock_failed, mock_get_error, factory: AppFactory, mock_manifest
    ):
        """Returns cached exception from app_utils."""
        cached_error = ValueError("Cached error")
        mock_get_error.return_value = cached_error

        result = factory._get_load_error(mock_manifest)

        assert result is cached_error

    def test_get_load_error_returns_runtime_error_if_no_cached(self, factory: AppFactory, mock_manifest):
        """Returns RuntimeError if no cached error."""

        result = factory._get_load_error(mock_manifest)

        assert isinstance(result, RuntimeError)
        assert "Unknown error" in str(result)


class TestAppFactoryNormalizeConfigs:
    def test_normalize_configs_none(self):
        """Returns empty list for None."""
        result = AppFactory._normalize_configs(None)
        assert result == []

    def test_normalize_configs_empty_dict(self):
        """Returns empty list for empty dict."""
        result = AppFactory._normalize_configs({})
        assert result == [{}]

    def test_normalize_configs_single_dict(self):
        """Wraps single dict in list."""
        config = {"instance_name": "test"}
        result = AppFactory._normalize_configs(config)
        assert result == [config]

    def test_normalize_configs_list(self):
        """Returns list as-is."""
        configs = [{"instance_name": "test1"}, {"instance_name": "test2"}]
        result = AppFactory._normalize_configs(configs)
        assert result == configs


class TestAppFactoryCheckOnlyAppDecorator:
    @patch("hassette.core.app_factory.get_loaded_class")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_check_only_app_returns_true(
        self, mock_already_loaded, mock_get_loaded, factory: AppFactory, mock_manifest
    ):
        """Returns True when _only_app attribute is True."""
        mock_class = Mock()
        mock_class._only_app = True
        mock_get_loaded.return_value = mock_class

        result = factory.check_only_app_decorator(mock_manifest)

        assert result is True

    @patch("hassette.core.app_factory.get_loaded_class")
    def test_check_only_app_returns_false_no_decorator(self, mock_get_loaded, factory: AppFactory, mock_manifest):
        """Returns False when attribute missing/False."""
        mock_class = Mock(spec=[])  # No _only_app attribute
        mock_get_loaded.return_value = mock_class

        result = factory.check_only_app_decorator(mock_manifest)

        assert result is False

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    def test_check_only_app_returns_false_on_failed_class(self, mock_failed, factory: AppFactory, mock_manifest):
        """Returns False when class previously failed to load."""
        result = factory.check_only_app_decorator(mock_manifest)

        assert result is False

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_check_only_app_catches_exceptions(self, mock_load_class, factory: AppFactory, caplog, mock_manifest):
        """Returns False and logs error on exception."""
        mock_load_class.side_effect = ImportError("Failed to load")

        result = factory.check_only_app_decorator(mock_manifest)
        assert result is False
        assert "Failed to check only_app" in caplog.text
