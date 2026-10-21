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

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.logging_ import LogIdentity, LogIdentityFilter, get_logger_identity
from hassette.resources.lifecycle import mark_ready
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource


def build_identity_app(
    instance_name: str, *, index: int = 0, app_key: str = "identity_app", log_level: str | None = None
) -> App:
    hassette = make_mock_hassette(sealed=False)
    hassette.config.logging.app_handler = "WARNING"
    config = AppConfig(instance_name=instance_name, log_level=log_level)
    return App(hassette, app_config=config, index=index, app_key=app_key)


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
        app = build_identity_app("identity_own", index=2)

        assert get_logger_identity(app.logger) == LogIdentity(
            author="app", app_key="identity_app", instance_name="identity_own", instance_index=2
        )

    def test_app_children_are_framework_authored_and_owned_by_the_app(self) -> None:
        app = build_identity_app("identity_children", index=1)
        owner = LogIdentity(
            author="framework", app_key="identity_app", instance_name="identity_children", instance_index=1
        )

        for child in (app.bus, app.scheduler, app.api, app.states):
            assert get_logger_identity(child.logger) == owner, child.class_name

    def test_user_sub_logger_inherits_the_app_identity(self) -> None:
        app = build_identity_app("identity_sub")

        sub = app.logger.getChild("helpers")

        assert get_logger_identity(sub) == get_logger_identity(app.logger)


class TestAppLifecycleLogger:
    def test_lifecycle_logger_is_framework_authored_and_owned_by_the_app(self) -> None:
        app = build_identity_app("identity_lifecycle", index=4)

        assert app.lifecycle_logger.name == f"{app.logger.name}.Lifecycle"
        assert get_logger_identity(app.lifecycle_logger) == LogIdentity(
            author="framework", app_key="identity_app", instance_name="identity_lifecycle", instance_index=4
        )

    def test_lifecycle_logger_level_follows_app_handler_not_app_log_level(self) -> None:
        app = build_identity_app("identity_level", log_level="DEBUG")

        assert app.logger.level == logging.DEBUG
        assert app.lifecycle_logger.level == logging.WARNING

    def test_lifecycle_code_writes_through_the_lifecycle_logger(
        self, buffered_records: tuple[BufferingHandler, list[logging.Logger]]
    ) -> None:
        handler, attached = buffered_records
        app = build_identity_app("identity_ready", index=3)
        app.lifecycle_logger.setLevel(logging.DEBUG)
        # On the app's logger, the handler sees both its direct lines and the lifecycle logger's propagated ones.
        app.logger.addHandler(handler)
        attached.append(app.logger)

        mark_ready(app, reason="unit test")

        ready = [r for r in handler.buffer if r.getMessage() == "ready: unit test"]
        assert [r.name for r in ready] == [app.lifecycle_logger.name]
        record = ready[0]
        assert record.source_tier == "framework"  # pyright: ignore[reportAttributeAccessIssue]
        assert record.app_key == "identity_app"  # pyright: ignore[reportAttributeAccessIssue]
        assert record.instance_name == "identity_ready"  # pyright: ignore[reportAttributeAccessIssue]
        assert record.instance_index == 3  # pyright: ignore[reportAttributeAccessIssue]


class TestFrameworkResourceIdentity:
    def test_framework_resource_has_no_owner(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        parent = ConcreteResource(hassette=hassette)
        child = ConcreteResource(hassette=hassette, parent=parent)

        assert get_logger_identity(child.logger) == LogIdentity(author="framework")
        assert child.lifecycle_logger is child.logger

    def test_rebuilding_on_a_shared_logger_replaces_identity_without_adding_filters(self) -> None:
        """Hot reload rebuilds an app under the same logger name; the newest instance's identity wins."""
        first = build_identity_app("identity_reload", index=0, app_key="old_key")
        filters_before = list(first.logger.filters)

        second = build_identity_app("identity_reload", index=5, app_key="new_key")

        assert second.logger is first.logger
        assert second.logger.filters == filters_before
        identity = get_logger_identity(second.logger)
        assert identity is not None
        assert identity.app_key == "new_key"
        assert identity.instance_index == 5
