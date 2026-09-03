"""Unit tests for App.state_registry / App.type_registry accessors (issue #971).

Confirms App exposes the registries via `self.state_registry` / `self.type_registry`,
delegating to the parent Hassette instance rather than duplicating registry state.
"""

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.conversion import StateRegistry, TypeRegistry
from tests.support.factories import make_mock_hassette


def _make_app_config(name: str = "kitchen") -> AppConfig:
    return AppConfig(instance_name=name)


class TestAppRegistries:
    def test_state_registry_delegates_to_hassette(self) -> None:
        """App.state_registry returns the exact StateRegistry instance owned by hassette."""
        hassette = make_mock_hassette(sealed=False)
        hassette.state_registry = StateRegistry()
        app = App(hassette, app_config=_make_app_config(), index=0, app_key="kitchen_lights")

        assert app.state_registry is hassette.state_registry

    def test_type_registry_delegates_to_hassette(self) -> None:
        """App.type_registry returns the exact TypeRegistry instance owned by hassette."""
        hassette = make_mock_hassette(sealed=False)
        hassette.type_registry = TypeRegistry()
        app = App(hassette, app_config=_make_app_config(), index=0, app_key="kitchen_lights")

        assert app.type_registry is hassette.type_registry
