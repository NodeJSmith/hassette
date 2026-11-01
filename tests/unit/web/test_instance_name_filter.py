"""The temporary index-to-name lookup the index-addressed telemetry routes filter through, until routes take names."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hassette.config.classes import instance_name_reason
from hassette.core.app_registry import AppRegistry
from hassette.web.dependencies import instance_name_filter
from tests.support.helpers import create_app_manifest


@pytest.fixture
def hassette(tmp_path: Path) -> SimpleNamespace:
    registry = AppRegistry()
    manifest = create_app_manifest("multi", tmp_path, app_config=[{"instance_name": "one"}, {"instance_name": "two"}])
    registry.set_manifests({manifest.app_key: manifest})
    return SimpleNamespace(app_handler=SimpleNamespace(registry=registry))


def test_configured_index_resolves_to_its_name(hassette: SimpleNamespace) -> None:
    assert instance_name_filter(hassette, "my_app_multi", 1) == "two"  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("app_key", "index"),
    [("__hassette__.BusService", 0), ("__hassette__", 0), (None, 0), ("my_app_multi", None)],
    ids=["framework_key", "framework_root", "all_apps", "every_instance"],
)
def test_no_filter_applies(app_key: str | None, index: int | None) -> None:
    """A framework key has one instance, and no app or no index means every instance."""
    assert instance_name_filter(MagicMock(), app_key, index) is None


@pytest.mark.parametrize(
    ("app_key", "index"), [("my_app_multi", 9), ("no_such_app", 0)], ids=["past_config", "unknown"]
)
def test_index_with_no_name_resolves_to_a_label_no_stored_row_can_hold(
    hassette: SimpleNamespace, app_key: str, index: int
) -> None:
    label = instance_name_filter(hassette, app_key, index)  # pyright: ignore[reportArgumentType]

    assert label is not None
    assert instance_name_reason(label) is not None
