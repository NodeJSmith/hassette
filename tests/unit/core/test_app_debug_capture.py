"""Debug capture state on AppRegistry and the AppHandler toggle (spec 148)."""

import inspect
import logging
from collections.abc import Iterator
from logging.handlers import BufferingHandler

import pytest
from hassette_wire import ResourceStatus

from hassette.core.app_handler import AppHandler
from hassette.core.app_registry import AppRegistry
from hassette.logging_ import LogIdentityFilter
from tests.support.factories import make_app

from .conftest import make_app_instance, make_manifest_obj

APP_KEY = "my_app"
CONFIGURED = [{"instance_name": "alpha"}, {"instance_name": "beta"}]


@pytest.fixture
def registry() -> AppRegistry:
    registry = AppRegistry()
    registry.set_manifests({APP_KEY: make_manifest_obj(APP_KEY, app_config=CONFIGURED)})
    return registry


@pytest.fixture
def handler(app_handler: AppHandler) -> AppHandler:
    app_handler.registry.set_manifests({APP_KEY: make_manifest_obj(APP_KEY, app_config=CONFIGURED)})
    return app_handler


@pytest.fixture
def handler_records(handler: AppHandler) -> Iterator[BufferingHandler]:
    """Records the AppHandler logger writes, with app identity stamped from bound context."""
    buffer = BufferingHandler(capacity=100)
    buffer.addFilter(LogIdentityFilter())
    handler.logger.addHandler(buffer)
    yield buffer
    handler.logger.removeHandler(buffer)


def capture_warnings(buffer: BufferingHandler) -> list[logging.LogRecord]:
    return [record for record in buffer.buffer if "Debug capture" in record.getMessage()]


class TestRegistryState:
    def test_pair_survives_unregister_and_reregister(self, registry: AppRegistry) -> None:
        registry.register_app(APP_KEY, make_app_instance(APP_KEY, "alpha"))
        registry.set_debug_capture(APP_KEY, ["alpha"], enabled=True)

        registry.unregister_app(APP_KEY, "alpha")
        registry.register_app(APP_KEY, make_app_instance(APP_KEY, "alpha"))

        assert registry.is_debug_captured(APP_KEY, "alpha")

    def test_status_read_reports_capture_for_running_failed_and_stopped(self, registry: AppRegistry) -> None:
        registry.register_app(APP_KEY, make_app_instance(APP_KEY, "alpha"))
        registry.record_failure(APP_KEY, "beta", ValueError("boom"))
        registry.set_debug_capture(APP_KEY, ["alpha", "beta"], enabled=True)

        info = registry.build_manifest_info(APP_KEY, registry.manifests[APP_KEY])
        assert {i.instance_name: (i.status, i.debug_capture) for i in info.instances} == {
            "alpha": (ResourceStatus.RUNNING, True),
            "beta": (ResourceStatus.FAILED, True),
        }

        registry.unregister_app(APP_KEY)
        info = registry.build_manifest_info(APP_KEY, registry.manifests[APP_KEY])
        assert all(i.status == ResourceStatus.STOPPED and i.debug_capture for i in info.instances)

    def test_status_read_reports_flagged_instance_capture(self, registry: AppRegistry) -> None:
        registry.flag_needs_restart(APP_KEY, "alpha", class_name="MyApp", reason="work still running")
        registry.set_debug_capture(APP_KEY, ["alpha"], enabled=True)

        info = registry.resolve_instance_info(APP_KEY, "alpha")
        assert info is not None
        assert info.debug_capture is True

    def test_prune_drops_unconfigured_pairs_no_live_instance_holds(self, registry: AppRegistry) -> None:
        registry.register_app(APP_KEY, make_app_instance(APP_KEY, "running_orphan"))
        registry.set_debug_capture(APP_KEY, ["alpha", "gone", "running_orphan"], enabled=True)

        registry.prune_stale_debug_capture(APP_KEY, ["alpha", "beta"])

        assert registry.debug_captured_names(APP_KEY) == {"alpha", "running_orphan"}

    def test_clear_all_ends_capture(self, registry: AppRegistry) -> None:
        registry.set_debug_capture(APP_KEY, ["alpha"], enabled=True)

        registry.clear_all()

        assert not registry.is_debug_captured(APP_KEY, "alpha")


class TestToggle:
    def test_is_synchronous(self) -> None:
        """No await may split the toggle, so a concurrent build sees all of it or none (spec 148 D6)."""
        assert not inspect.iscoroutinefunction(AppHandler.set_debug_capture)

    def test_app_wide_on_captures_every_configured_instance(self, handler: AppHandler) -> None:
        states = handler.set_debug_capture(APP_KEY, None, enabled=True)

        assert states == {"alpha": True, "beta": True}

    def test_app_wide_off_ends_capture_for_unconfigured_names_too(self, handler: AppHandler) -> None:
        handler.registry.set_debug_capture(APP_KEY, ["alpha", "leftover"], enabled=True)

        states = handler.set_debug_capture(APP_KEY, None, enabled=False)

        assert states == {"alpha": False, "beta": False, "leftover": False}
        assert handler.registry.debug_captured_names(APP_KEY) == set()

    def test_instance_off_leaves_siblings_captured(self, handler: AppHandler) -> None:
        handler.set_debug_capture(APP_KEY, None, enabled=True)

        states = handler.set_debug_capture(APP_KEY, "alpha", enabled=False)

        assert states == {"alpha": False}
        assert handler.registry.debug_captured_names(APP_KEY) == {"beta"}

    def test_instance_on_reapplies_a_running_instance_at_once(self, handler: AppHandler) -> None:
        app = make_app(instance_name="alpha", app_key=APP_KEY)
        handler.registry.register_app(APP_KEY, app)

        handler.set_debug_capture(APP_KEY, "alpha", enabled=True)

        assert app.debug_capture is True
        assert app.logger.level == logging.DEBUG
        assert app.bus.logger.level == logging.DEBUG

        handler.set_debug_capture(APP_KEY, "alpha", enabled=False)

        assert app.debug_capture is False
        assert app.bus.logger.level > logging.DEBUG

    def test_repeating_a_state_repairs_a_live_instance_whose_flag_drifted(self, handler: AppHandler) -> None:
        """The App's flag is a mirror: a repeat request re-applies it even though the registry says nothing changed."""
        app = make_app(instance_name="alpha", app_key=APP_KEY)
        handler.registry.register_app(APP_KEY, app)
        handler.set_debug_capture(APP_KEY, "alpha", enabled=True)
        app.set_debug_capture(False)
        assert app.bus.logger.level > logging.DEBUG

        handler.set_debug_capture(APP_KEY, "alpha", enabled=True)

        assert app.debug_capture is True
        assert app.logger.level == logging.DEBUG
        assert app.bus.logger.level == logging.DEBUG

    def test_each_change_warns_attributed_to_its_instance(
        self, handler: AppHandler, handler_records: BufferingHandler
    ) -> None:
        handler.set_debug_capture(APP_KEY, None, enabled=True)
        handler.set_debug_capture(APP_KEY, "alpha", enabled=False)

        records = capture_warnings(handler_records)
        assert [(r.levelno, getattr(r, "app_key", None), getattr(r, "instance_name", None)) for r in records] == [
            (logging.WARNING, APP_KEY, "alpha"),
            (logging.WARNING, APP_KEY, "beta"),
            (logging.WARNING, APP_KEY, "alpha"),
        ]
        assert "hassette app debug my_app off" in records[0].getMessage()

    def test_repeating_a_state_changes_nothing_and_logs_nothing(
        self, handler: AppHandler, handler_records: BufferingHandler
    ) -> None:
        handler.set_debug_capture(APP_KEY, "alpha", enabled=False)

        assert capture_warnings(handler_records) == []
