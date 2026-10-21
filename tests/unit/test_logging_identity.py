"""Tests for LogIdentityFilter: author and subject resolved from the writing logger.

Verifies:
- A logger's owner stamp wins over bound context; context supplies the subject only for ownerless loggers.
- Loggers with no identity anywhere up their ancestry take their author from the namespace rule.
- Captured warnings take their author from the warning's category and source file.
- The filter is idempotent, so the Phase 2 listener thread doesn't overwrite what the caller's thread stamped.
- The Phase 1 stream handler resolves identity too.
- The bound app key no longer decides author.

Logger names are unique per test: logger objects are process-global, and an identity another test
fixed on a shared name would leak in.
"""

import logging
import warnings
from collections.abc import Iterator
from io import StringIO
from logging.handlers import BufferingHandler
from pathlib import Path

import pytest
import structlog

from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.logging_ import (
    PY_WARNINGS_LOGGER_NAME,
    LogIdentity,
    LogIdentityFilter,
    _showwarning,  # pyright: ignore[reportPrivateUsage]
    enable_basic_logging,
    set_logger_identity,
    warning_author,
)
from hassette.utils.stack_frames import HASSETTE_PACKAGE_DIR
from tests.support.factories import make_log_record
from tests.support.helpers import first_json_record_containing

USER_APP_FILE = "/home/user/apps/my_app.py"
OWNER = LogIdentity(author="framework", app_key="owner_app", instance_name="owner_inst", instance_index=1)


@pytest.fixture(autouse=True)
def clean_contextvars() -> Iterator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def stamp_identity(name: str, **record_attrs: object) -> logging.LogRecord:
    """Run a fresh record on the named logger through LogIdentityFilter and return it."""
    record = make_log_record(name=name)
    for key, value in record_attrs.items():
        setattr(record, key, value)
    LogIdentityFilter().filter(record)
    return record


def identity_subject(record: logging.LogRecord) -> tuple[object, object, object]:
    return (
        getattr(record, "app_key", None),
        getattr(record, "instance_name", None),
        getattr(record, "instance_index", None),
    )


class TestOwnedLoggers:
    def test_owner_stamp_sets_author_and_subject(self) -> None:
        set_logger_identity(logging.getLogger("hassette.identity_test.owned"), OWNER)

        record = stamp_identity("hassette.identity_test.owned")

        assert record.source_tier == "framework"  # pyright: ignore[reportAttributeAccessIssue]
        assert identity_subject(record) == ("owner_app", "owner_inst", 1)

    def test_owner_wins_over_bound_context(self) -> None:
        """A framework task that inherited another app's context still reports its own owner."""
        set_logger_identity(logging.getLogger("hassette.identity_test.owned_ctx"), OWNER)
        structlog.contextvars.bind_contextvars(app_key="other_app", instance_name="other", instance_index=9)

        record = stamp_identity("hassette.identity_test.owned_ctx")

        assert identity_subject(record) == ("owner_app", "owner_inst", 1)

    def test_descendant_takes_nearest_identified_ancestor(self) -> None:
        set_logger_identity(logging.getLogger("hassette.identity_test.parent"), OWNER)
        nearer = LogIdentity(author="app", app_key="near_app", instance_name="near", instance_index=0)
        set_logger_identity(logging.getLogger("hassette.identity_test.parent.mid"), nearer)
        logging.getLogger("hassette.identity_test.parent.mid.leaf")  # registers the leaf logger

        record = stamp_identity("hassette.identity_test.parent.mid.leaf")

        assert record.source_tier == "app"  # pyright: ignore[reportAttributeAccessIssue]
        assert identity_subject(record) == ("near_app", "near", 0)


class TestOwnerlessLoggers:
    def test_identified_framework_logger_without_owner_takes_subject_from_context(self) -> None:
        set_logger_identity(logging.getLogger("hassette.identity_test.service"), LogIdentity(author="framework"))
        structlog.contextvars.bind_contextvars(app_key="ctx_app", instance_name="ctx", instance_index=2)

        record = stamp_identity("hassette.identity_test.service")

        assert record.source_tier == "framework"  # pyright: ignore[reportAttributeAccessIssue]
        assert identity_subject(record) == ("ctx_app", "ctx", 2)

    @pytest.mark.parametrize(
        ("name", "author"),
        [
            ("hassette", "framework"),
            ("hassette.identity_test.unowned", "framework"),
            ("identity_test_user_module", "app"),
            ("hassettex.identity_test", "app"),
        ],
    )
    def test_namespace_rule_when_nothing_is_identified(self, name: str, author: str) -> None:
        logging.getLogger(name)

        record = stamp_identity(name)

        assert record.source_tier == author  # pyright: ignore[reportAttributeAccessIssue]

    def test_bound_app_key_does_not_make_a_line_app_authored(self) -> None:
        structlog.contextvars.bind_contextvars(app_key="ctx_app")
        logging.getLogger("hassette.identity_test.lifecycle_service")

        record = stamp_identity("hassette.identity_test.lifecycle_service")

        assert record.source_tier == "framework"  # pyright: ignore[reportAttributeAccessIssue]
        assert identity_subject(record) == ("ctx_app", None, None)

    def test_no_context_means_no_subject(self) -> None:
        record = stamp_identity("hassette.identity_test.no_ctx")

        assert identity_subject(record) == (None, None, None)

    def test_unregistered_logger_name_falls_back_to_namespace(self) -> None:
        record = stamp_identity("identity_test.never_created.by_getlogger")

        assert record.source_tier == "app"  # pyright: ignore[reportAttributeAccessIssue]


class TestCapturedWarnings:
    def test_hassette_warning_category_is_framework(self) -> None:
        assert warning_author(HassetteForgottenAwaitWarning, USER_APP_FILE) == "framework"

    def test_warning_raised_in_a_hassette_module_is_framework(self) -> None:
        assert warning_author(DeprecationWarning, str(HASSETTE_PACKAGE_DIR / "bus" / "bus.py")) == "framework"

    def test_user_warning_from_user_code_is_app(self) -> None:
        assert warning_author(UserWarning, USER_APP_FILE) == "app"

    def test_workspace_member_warning_category_is_framework(self) -> None:
        client_warning = type("ClientWarning", (UserWarning,), {"__module__": "hassette_client.errors"})

        assert warning_author(client_warning, USER_APP_FILE) == "framework"

    def test_sibling_directory_with_a_shared_prefix_is_not_hassette(self) -> None:
        sibling = Path(f"{HASSETTE_PACKAGE_DIR}_extras") / "mod.py"

        assert warning_author(UserWarning, str(sibling)) == "app"

    def test_py_warnings_record_uses_the_warning_origin(self) -> None:
        record = stamp_identity(PY_WARNINGS_LOGGER_NAME, warning_category=UserWarning, warning_filename=USER_APP_FILE)
        framework = stamp_identity(
            PY_WARNINGS_LOGGER_NAME,
            warning_category=HassetteForgottenAwaitWarning,
            warning_filename=USER_APP_FILE,
        )

        assert record.source_tier == "app"  # pyright: ignore[reportAttributeAccessIssue]
        assert framework.source_tier == "framework"  # pyright: ignore[reportAttributeAccessIssue]

    def test_showwarning_puts_category_and_filename_on_the_record(self) -> None:
        """Calls the hook directly: pytest replaces warnings.showwarning around each test body."""
        warnings_logger = logging.getLogger(PY_WARNINGS_LOGGER_NAME)
        handler = BufferingHandler(capacity=10)
        warnings_logger.addHandler(handler)
        try:
            _showwarning(UserWarning("careful"), UserWarning, USER_APP_FILE, 12)
        finally:
            warnings_logger.removeHandler(handler)

        records = handler.buffer
        assert len(records) == 1
        assert records[0].warning_category is UserWarning  # pyright: ignore[reportAttributeAccessIssue]
        assert records[0].warning_filename == USER_APP_FILE  # pyright: ignore[reportAttributeAccessIssue]
        assert "careful" in records[0].getMessage()

    def test_enable_basic_logging_installs_the_hook(self) -> None:
        enable_basic_logging("INFO", log_format="json", stream=StringIO())

        assert warnings.showwarning is _showwarning


class TestPipelineBehavior:
    def test_already_resolved_record_is_left_alone(self) -> None:
        """Phase 2 runs the stream handler's filter again on the listener thread, where no context is bound."""
        structlog.contextvars.bind_contextvars(app_key="from_caller_thread")
        record = stamp_identity("hassette.identity_test.resolved_once")
        structlog.contextvars.clear_contextvars()

        LogIdentityFilter().filter(record)

        assert record.app_key == "from_caller_thread"  # pyright: ignore[reportAttributeAccessIssue]

    def test_caller_supplied_source_tier_does_not_skip_subject(self) -> None:
        """A record built with extra={"source_tier": ...} still gets its subject resolved."""
        structlog.contextvars.bind_contextvars(app_key="ctx_app")

        record = stamp_identity("hassette.identity_test.extra_tier", source_tier="app")

        assert record.source_tier == "framework"  # pyright: ignore[reportAttributeAccessIssue]
        assert identity_subject(record) == ("ctx_app", None, None)

    def test_phase1_stream_handler_resolves_identity(self) -> None:
        stream = StringIO()
        enable_basic_logging("INFO", log_format="json", stream=stream)
        set_logger_identity(logging.getLogger("hassette.identity_test.phase1"), OWNER)

        logging.getLogger("hassette.identity_test.phase1").info("phase one line")

        parsed = first_json_record_containing(stream, "phase one line")
        assert parsed["source_tier"] == "framework"
        assert (parsed["app_key"], parsed["instance_name"], parsed["instance_index"]) == ("owner_app", "owner_inst", 1)
