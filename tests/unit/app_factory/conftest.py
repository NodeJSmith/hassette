"""Shared fixtures and helpers for the AppFactory tests in this directory."""

from typing import cast
from unittest.mock import Mock

import pytest

from hassette import App, AppConfig
from hassette.core.app_factory import AppFactory


def make_app_class(config_cls: type[AppConfig] = AppConfig, **kwargs) -> Mock:
    """A mock App class with a real config class, so config validation runs for real.

    Each instance it builds is a Mock App named by the validated config, as a real ``App`` is.
    """

    def build(*, app_config: AppConfig, **_: object) -> Mock:
        return Mock(instance_name=app_config.instance_name)

    return Mock(app_config_cls=config_cls, side_effect=build, **kwargs)


def registered(mock_registry: Mock) -> list[tuple[str, str]]:
    """The ``(app_key, instance_name)`` pairs the factory registered, in registration order."""
    return [(call.args[0], call.args[1].instance_name) for call in mock_registry.register_app.call_args_list]


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


def flag_names(mock_registry: Mock, *flagged: str) -> None:
    """Make ``mock_registry`` refuse each name in ``flagged``, with the refusal text ``refused <name>``."""
    mock_registry.refusal_reason = Mock(side_effect=lambda _key, name: f"refused {name}" if name in flagged else None)


@pytest.fixture
def factory(mock_hassette, mock_registry):
    """Create an AppFactory instance with mocked dependencies."""
    return AppFactory(mock_hassette, mock_registry)
