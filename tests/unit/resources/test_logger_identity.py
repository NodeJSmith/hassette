"""Tests for the author and owner identity resources fix on their loggers.

Verifies:
- An App's own logger is app-authored and owned by the app instance.
- An App's children (Bus, Scheduler, ...) write framework-authored lines owned by the app.
- Each App gets a framework-authored ``.Lifecycle`` logger, owned by the app, at ``app_handler``'s level.
- Generic lifecycle code writes about an App through that lifecycle logger, not the app's own.
- Framework resources carry no owner.
- Rebuilding a resource on a shared logger replaces its identity rather than accumulating anything.
"""

import logging
from collections.abc import Iterator
from logging.handlers import BufferingHandler

import pytest
from hassette_wire import LogLevel

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.logging_ import LogIdentity, LogIdentityFilter, get_logger_identity
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource

FRAMEWORK_CHILD_LEVEL_FIELDS = ("bus_service", "scheduler_service", "api", "state_proxy", "task_bucket")
"""The ``LoggingConfig`` fields of an app's framework children; the tests set them all to ERROR."""


def framework_children(app: App) -> list[Resource]:
    """An app's direct framework children, one per ``FRAMEWORK_CHILD_LEVEL_FIELDS`` entry."""
    return [app.bus, app.scheduler, app.api, app.states, app.task_bucket]


def framework_loggers(app: App) -> list[logging.Logger]:
    """The loggers an app owns that are framework-authored, a grandchild (``api.sync``) included."""
    resources = [*framework_children(app), app.api.sync]
    return [app.lifecycle_logger, *(resource.logger for resource in resources)]


def build_identity_app(
    instance_name: str,
    *,
    app_key: str = "identity_app",
    log_level: LogLevel | None = None,
    framework_log_level: LogLevel | None = None,
    debug_capture: bool = False,
) -> App:
    hassette = make_mock_hassette(sealed=False)
    hassette.config.logging.app_handler = "WARNING"
    for field in FRAMEWORK_CHILD_LEVEL_FIELDS:
        setattr(hassette.config.logging, field, "ERROR")
    config = AppConfig(instance_name=instance_name, log_level=log_level, framework_log_level=framework_log_level)
    return App(hassette, app_config=config, app_key=app_key, debug_capture=debug_capture)


@pytest.fixture
def buffered_records() -> Iterator[tuple[BufferingHandler, list[logging.Logger]]]:
    """A buffering handler with the identity resolver; the test attaches it and lists the loggers here."""
    handler = BufferingHandler(capacity=100)
    handler.addFilter(LogIdentityFilter())
    attached: list[logging.Logger] = []
    yield handler, attached
    for logger in attached:
        logger.removeHandler(handler)


class TestAppLoggerIdentity:
    def test_app_logger_is_app_authored_and_owned_by_the_instance(self) -> None:
        app = build_identity_app("identity_own")

        assert get_logger_identity(app.logger) == LogIdentity(
            author="app", app_key="identity_app", instance_name="identity_own"
        )

    def test_app_children_are_framework_authored_and_owned_by_the_app(self) -> None:
        app = build_identity_app("identity_children")
        owner = LogIdentity(author="framework", app_key="identity_app", instance_name="identity_children")

        for child in (app.bus, app.scheduler, app.api, app.states):
            assert get_logger_identity(child.logger) == owner, child.class_name

    def test_user_sub_logger_inherits_the_app_identity(self) -> None:
        app = build_identity_app("identity_sub")

        sub = app.logger.getChild("helpers")

        assert get_logger_identity(sub) == get_logger_identity(app.logger)


class TestFrameworkLogLevel:
    def test_framework_loggers_follow_framework_log_level_when_set(self) -> None:
        app = build_identity_app("fw_children", framework_log_level="DEBUG")

        for logger in framework_loggers(app):
            assert logger.level == logging.DEBUG, logger.name

    def test_children_keep_service_levels_when_unset(self) -> None:
        app = build_identity_app("fw_unset")

        for child in framework_children(app):
            assert child.logger.level == logging.ERROR, child.class_name

    def test_app_log_level_alone_does_not_raise_framework_loggers(self) -> None:
        app = build_identity_app("fw_app_debug", log_level="DEBUG")

        assert app.logger.level == logging.DEBUG
        for logger in framework_loggers(app):
            assert logger.level > logging.DEBUG, logger.name

    def test_framework_log_level_does_not_change_the_app_logger(self) -> None:
        app = build_identity_app("fw_own", log_level="WARNING", framework_log_level="DEBUG")

        assert app.logger.level == logging.WARNING

    def test_framework_log_level_is_scoped_to_its_own_app(self) -> None:
        raised = build_identity_app("fw_raised", framework_log_level="DEBUG")
        sibling = App(raised.hassette, app_config=AppConfig(instance_name="fw_sibling"), app_key="other")

        assert raised.bus.logger.level == logging.DEBUG
        assert sibling.bus.logger.level == logging.ERROR
        assert sibling.lifecycle_logger.level == logging.WARNING


def owned_loggers(app: App) -> list[logging.Logger]:
    """Every logger an app owns: its own, the framework ones, and its children's own TaskBuckets."""
    buckets = [child.task_bucket.logger for child in framework_children(app) if child.task_bucket is not child]
    return [app.logger, *framework_loggers(app), *buckets]


class TestDebugCaptureLevels:
    """Debug capture puts every logger an app owns at DEBUG, and turning it off restores config levels (spec 148)."""

    def test_app_built_captured_has_every_owned_logger_at_debug(self) -> None:
        app = build_identity_app("capture_built", log_level="WARNING", debug_capture=True)

        for logger in owned_loggers(app):
            assert logger.level == logging.DEBUG, logger.name

    def test_capture_on_a_live_app_raises_every_owned_logger(self) -> None:
        app = build_identity_app("capture_live")

        app.debug_capture = True
        app.reapply_log_levels()

        for logger in owned_loggers(app):
            assert logger.level == logging.DEBUG, logger.name

    def test_capture_off_restores_config_levels(self) -> None:
        app = build_identity_app("capture_off", log_level="WARNING", framework_log_level="ERROR")
        before = {logger.name: logger.level for logger in owned_loggers(app)}

        app.debug_capture = True
        app.reapply_log_levels()
        app.debug_capture = False
        app.reapply_log_levels()

        assert {logger.name: logger.level for logger in owned_loggers(app)} == before

    def test_capture_is_scoped_to_its_own_app(self) -> None:
        captured = build_identity_app("capture_scoped", debug_capture=True)
        sibling = App(captured.hassette, app_config=AppConfig(instance_name="capture_sibling"), app_key="other")

        assert sibling.logger.level > logging.DEBUG
        assert sibling.bus.logger.level == logging.ERROR

    def test_built_captured_app_warns_on_its_lifecycle_logger(
        self, buffered_records: tuple[BufferingHandler, list[logging.Logger]]
    ) -> None:
        handler, attached = buffered_records
        lifecycle = logging.getLogger("hassette.apps.capture_warned.Lifecycle")
        lifecycle.addHandler(handler)
        attached.append(lifecycle)

        build_identity_app("capture_warned", debug_capture=True)

        warnings = [record for record in handler.buffer if record.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "Debug capture is on" in warnings[0].getMessage()
        assert getattr(warnings[0], "instance_name", None) == "capture_warned"

    def test_uncaptured_app_does_not_warn(
        self, buffered_records: tuple[BufferingHandler, list[logging.Logger]]
    ) -> None:
        handler, attached = buffered_records
        lifecycle = logging.getLogger("hassette.apps.capture_quiet.Lifecycle")
        lifecycle.addHandler(handler)
        attached.append(lifecycle)

        build_identity_app("capture_quiet")

        assert not [record for record in handler.buffer if "Debug capture" in record.getMessage()]


class TestAppLifecycleLogger:
    def test_lifecycle_logger_is_framework_authored_and_owned_by_the_app(self) -> None:
        app = build_identity_app("identity_lifecycle")

        assert app.lifecycle_logger.name == f"{app.logger.name}.Lifecycle"
        assert get_logger_identity(app.lifecycle_logger) == LogIdentity(
            author="framework", app_key="identity_app", instance_name="identity_lifecycle"
        )

    def test_lifecycle_logger_level_follows_app_handler_not_app_log_level(self) -> None:
        app = build_identity_app("identity_level", log_level="DEBUG")

        assert app.logger.level == logging.DEBUG
        assert app.lifecycle_logger.level == logging.WARNING

    def test_lifecycle_logger_level_follows_framework_log_level_when_set(self) -> None:
        app = build_identity_app("identity_fw_lifecycle", framework_log_level="DEBUG")

        assert app.lifecycle_logger.level == logging.DEBUG

    def test_lifecycle_code_writes_through_the_lifecycle_logger(
        self, buffered_records: tuple[BufferingHandler, list[logging.Logger]]
    ) -> None:
        handler, attached = buffered_records
        app = build_identity_app("identity_ready")
        app.lifecycle_logger.setLevel(logging.DEBUG)
        # On the app's logger, the handler sees both its direct lines and the lifecycle logger's propagated ones.
        app.logger.addHandler(handler)
        attached.append(app.logger)

        mark_ready(app, reason="unit test")

        ready = [r for r in handler.buffer if r.getMessage() == "ready: unit test"]
        assert [r.name for r in ready] == [app.lifecycle_logger.name]
        record = ready[0]
        assert record.author == "framework"  # pyright: ignore[reportAttributeAccessIssue]
        assert record.app_key == "identity_app"  # pyright: ignore[reportAttributeAccessIssue]
        assert record.instance_name == "identity_ready"  # pyright: ignore[reportAttributeAccessIssue]


class TestFrameworkResourceIdentity:
    def test_framework_resource_has_no_owner(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        parent = ConcreteResource(hassette=hassette)
        child = ConcreteResource(hassette=hassette, parent=parent)

        assert get_logger_identity(child.logger) == LogIdentity(author="framework")
        assert child.lifecycle_logger is child.logger

    def test_rebuilding_on_a_shared_logger_replaces_identity_without_adding_filters(self) -> None:
        """Hot reload rebuilds an app under the same logger name; the newest instance's identity wins."""
        first = build_identity_app("identity_reload", app_key="old_key")
        filters_before = list(first.logger.filters)

        second = build_identity_app("identity_reload", app_key="new_key")

        assert second.logger is first.logger
        assert second.logger.filters == filters_before
        identity = get_logger_identity(second.logger)
        assert identity is not None
        assert identity.app_key == "new_key"
