"""Unit tests for App.state_registry / App.type_registry accessors (issue #971).

Confirms App exposes the registries via `self.state_registry` / `self.type_registry`,
delegating to the parent Hassette instance rather than duplicating registry state.
"""

from hassette.conversion import StateRegistry, TypeRegistry
from tests.support.factories import make_app
from tests.support.mock_hassette import make_mock_hassette


class TestAppRegistries:
    def test_state_registry_delegates_to_hassette(self) -> None:
        """App.state_registry returns the exact StateRegistry instance owned by hassette."""
        hassette = make_mock_hassette(sealed=False)
        hassette.state_registry = StateRegistry()
        app = make_app(hassette=hassette)

        assert app.state_registry is hassette.state_registry

    def test_type_registry_delegates_to_hassette(self) -> None:
        """App.type_registry returns the exact TypeRegistry instance owned by hassette."""
        hassette = make_mock_hassette(sealed=False)
        hassette.type_registry = TypeRegistry()
        app = make_app(hassette=hassette)

        assert app.type_registry is hassette.type_registry
