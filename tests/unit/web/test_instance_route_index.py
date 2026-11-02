"""The instance routes' temporary index-to-name translation, against a real ``AppRegistry``, until routes take names."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from hassette_wire import ProblemCode

from hassette import Hassette
from hassette.core.app_registry import AppRegistry
from hassette.web.errors import WebApiError
from hassette.web.routes.apps import _require_valid_instance_index
from tests.support.factories import make_app
from tests.support.helpers import create_app_manifest

APP_KEY = "my_app_multi"


@pytest.fixture
def registry(tmp_path: Path) -> AppRegistry:
    registry = AppRegistry()
    manifest = create_app_manifest("multi", tmp_path, app_config=[{"instance_name": "one"}, {"instance_name": "two"}])
    registry.set_manifests({manifest.app_key: manifest})
    return registry


def hassette_with(registry: AppRegistry) -> Hassette:
    handler = SimpleNamespace(registry=registry, is_action_in_progress=lambda _app_key: False)
    return cast("Hassette", SimpleNamespace(app_handler=handler))


def test_index_translates_to_the_name_at_that_position(registry: AppRegistry) -> None:
    assert _require_valid_instance_index(APP_KEY, 1, hassette_with(registry), "reload") == "two"


def test_a_reorder_moves_the_name_an_index_addresses(registry: AppRegistry, tmp_path: Path) -> None:
    swapped = create_app_manifest("multi", tmp_path, app_config=[{"instance_name": "two"}, {"instance_name": "one"}])
    registry.set_manifests({swapped.app_key: swapped})

    assert _require_valid_instance_index(APP_KEY, 0, hassette_with(registry), "stop") == "two"


def test_stop_addresses_a_running_orphan_by_its_derived_index(registry: AppRegistry) -> None:
    registry.register_app(APP_KEY, "attic", make_app())

    assert _require_valid_instance_index(APP_KEY, 2, hassette_with(registry), "stop") == "attic"


@pytest.mark.parametrize("action", ["start", "reload"])
def test_only_stop_addresses_an_orphan(registry: AppRegistry, action: str) -> None:
    registry.register_app(APP_KEY, "attic", make_app())

    with pytest.raises(WebApiError) as exc_info:
        _require_valid_instance_index(APP_KEY, 2, hassette_with(registry), action)  # pyright: ignore[reportArgumentType]

    assert exc_info.value.code is ProblemCode.INSTANCE_NOT_FOUND


@pytest.mark.parametrize("index", [-1, 2])
def test_an_index_with_no_instance_is_not_found(registry: AppRegistry, index: int) -> None:
    with pytest.raises(WebApiError) as exc_info:
        _require_valid_instance_index(APP_KEY, index, hassette_with(registry), "stop")

    assert exc_info.value.code is ProblemCode.INSTANCE_NOT_FOUND
