"""Shared fixtures and helpers for the AppFactory tests in this directory."""

from typing import cast
from unittest.mock import Mock

import pytest

from hassette import App, AppConfig
from hassette.core.app_factory import AppFactory


def make_app_class(config_cls: type[AppConfig] = AppConfig, **kwargs) -> Mock:
    """A mock App class with a real config class, so config validation runs for real."""
    return Mock(app_config_cls=config_cls, **kwargs)


def as_app_class(mock_app_class: Mock) -> type[App[AppConfig]]:
    """Present a mock App class where ``create_single_instance`` expects a real one."""
    return cast("type[App[AppConfig]]", mock_app_class)


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance."""
    return Mock()


@pytest.fixture
def mock_registry() -> Mock:
    """Create a mock AppRegistry instance."""
    registry = Mock()
    registry.register_app = Mock()
    registry.record_failure = Mock()
    registry.get = Mock(return_value=None)
    registry.get_running_apps = Mock(return_value={})
    registry.refusal_reason = Mock(return_value=None)
    return registry


@pytest.fixture
def mock_manifest():
    """Create a mock AppManifest instance."""
    manifest = Mock()
    manifest.full_path = "/path/to/app.py"
    manifest.class_name = "TestApp"
    manifest.display_name = "test_app"
    manifest.app_config = {"instance_name": "test_instance"}
    return manifest


def flag_indices(mock_registry: Mock, *flagged: int) -> None:
    """Make ``mock_registry`` refuse each index in ``flagged``, with the refusal text ``refused <index>``."""
    mock_registry.refusal_reason = Mock(side_effect=lambda _key, idx: f"refused {idx}" if idx in flagged else None)


@pytest.fixture
def factory(mock_hassette, mock_registry):
    """Create an AppFactory instance with mocked dependencies."""
    return AppFactory(mock_hassette, mock_registry)
