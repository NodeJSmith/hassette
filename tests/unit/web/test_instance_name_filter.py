"""The temporary index-to-name lookup the index-addressed telemetry routes filter through, until routes take names."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hassette.config.classes import instance_name_reason
from hassette.core.app_registry import AppRegistry
from hassette.web.dependencies import instance_name_filter
from tests.support.factories import make_app
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


def test_index_past_config_resolves_to_a_label_no_stored_row_can_hold(hassette: SimpleNamespace) -> None:
    label = instance_name_filter(hassette, "my_app_multi", 9)  # pyright: ignore[reportArgumentType]

    assert label is not None
    assert instance_name_reason(label) is not None


def test_removed_app_applies_no_filter(hassette: SimpleNamespace) -> None:
    """An app with no manifest and no tracked instance has no name to filter on, so its index means every instance."""
    assert instance_name_filter(hassette, "no_such_app", 0) is None  # pyright: ignore[reportArgumentType]


def test_still_running_orphan_keeps_its_name(hassette: SimpleNamespace) -> None:
    """An app removed from config while its instance runs has no manifest, but its entry still names it."""
    hassette.app_handler.registry.register_app("orphan", 0, make_app(instance_name="kitchen"))

    assert instance_name_filter(hassette, "orphan", 0) == "kitchen"  # pyright: ignore[reportArgumentType]


def test_needs_restart_record_keeps_its_name(hassette: SimpleNamespace) -> None:
    hassette.app_handler.registry.flag_needs_restart(
        "orphan", 0, instance_name="kitchen", class_name="Kitchen", reason="task still running"
    )

    assert instance_name_filter(hassette, "orphan", 0) == "kitchen"  # pyright: ignore[reportArgumentType]


def test_untracked_index_on_an_orphan_matches_no_other_instance(hassette: SimpleNamespace) -> None:
    """A tracked app is still present, so another index resolves to a label rather than dropping the filter."""
    hassette.app_handler.registry.register_app("orphan", 0, make_app(instance_name="kitchen"))

    label = instance_name_filter(hassette, "orphan", 2)  # pyright: ignore[reportArgumentType]

    assert label is not None
    assert instance_name_reason(label) is not None
