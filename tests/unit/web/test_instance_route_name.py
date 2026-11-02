"""The instance routes' name check, against a real ``AppRegistry``."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from hassette_wire import ProblemCode

from hassette import Hassette
from hassette.core.app_registry import AppRegistry
from hassette.web.errors import WebApiError
from hassette.web.routes.apps import _require_addressable_instance
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


@pytest.mark.parametrize("action", ["start", "stop", "reload"])
def test_a_configured_name_is_addressable_for_every_action(registry: AppRegistry, action: str) -> None:
    _require_addressable_instance(APP_KEY, "two", hassette_with(registry), action)  # pyright: ignore[reportArgumentType]


def test_a_reorder_does_not_change_what_a_name_addresses(registry: AppRegistry, tmp_path: Path) -> None:
    swapped = create_app_manifest("multi", tmp_path, app_config=[{"instance_name": "two"}, {"instance_name": "one"}])
    registry.set_manifests({swapped.app_key: swapped})

    _require_addressable_instance(APP_KEY, "two", hassette_with(registry), "stop")


def test_stop_addresses_a_running_orphan_by_name(registry: AppRegistry) -> None:
    registry.register_app(APP_KEY, make_app(instance_name="attic"))

    _require_addressable_instance(APP_KEY, "attic", hassette_with(registry), "stop")


@pytest.mark.parametrize("action", ["start", "reload"])
def test_only_stop_addresses_an_orphan(registry: AppRegistry, action: str) -> None:
    registry.register_app(APP_KEY, make_app(instance_name="attic"))

    with pytest.raises(WebApiError) as exc_info:
        _require_addressable_instance(APP_KEY, "attic", hassette_with(registry), action)  # pyright: ignore[reportArgumentType]

    assert exc_info.value.code is ProblemCode.INSTANCE_NOT_FOUND


@pytest.mark.parametrize("name", ["0", "1", "no_such_instance"])
def test_a_name_with_no_instance_is_not_found_with_no_fallback(registry: AppRegistry, name: str) -> None:
    with pytest.raises(WebApiError) as exc_info:
        _require_addressable_instance(APP_KEY, name, hassette_with(registry), "stop")

    assert exc_info.value.code is ProblemCode.INSTANCE_NOT_FOUND


def test_an_app_removed_from_config_stops_only_a_tracked_name(registry: AppRegistry) -> None:
    registry.register_app(APP_KEY, make_app(instance_name="one"))
    registry.set_manifests({})

    _require_addressable_instance(APP_KEY, "one", hassette_with(registry), "stop")
    with pytest.raises(WebApiError) as exc_info:
        _require_addressable_instance(APP_KEY, "two", hassette_with(registry), "stop")

    assert exc_info.value.code is ProblemCode.INSTANCE_NOT_FOUND


def test_an_app_removed_from_config_with_nothing_tracked_is_app_not_found(registry: AppRegistry) -> None:
    registry.set_manifests({})

    with pytest.raises(WebApiError) as exc_info:
        _require_addressable_instance(APP_KEY, "one", hassette_with(registry), "stop")

    assert exc_info.value.code is ProblemCode.APP_NOT_FOUND
