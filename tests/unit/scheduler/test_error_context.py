"""Tests for SchedulerErrorContext dataclass."""

import pytest

from hassette.scheduler.error_context import SchedulerErrorContext


def _make_scheduler_error_context(exc: BaseException | None = None) -> SchedulerErrorContext:
    """Helper to construct a SchedulerErrorContext with minimal required fields."""
    if exc is None:
        exc = ValueError("test error")

    return SchedulerErrorContext(
        exception=exc,
        traceback="Traceback (most recent call last):\n  ...\nValueError: test error\n",
        job_name="my_job",
        job_group=None,
        args=(),
        kwargs={},
    )


class TestSchedulerErrorContextConstruction:
    def test_scheduler_error_context_construction(self) -> None:
        """SchedulerErrorContext can be constructed and fields are accessible."""
        exc = RuntimeError("boom")
        ctx = _make_scheduler_error_context(exc)

        assert ctx.exception is exc
        assert ctx.job_name == "my_job"
        assert ctx.job_group is None
        assert ctx.args == ()
        assert ctx.kwargs == {}
        assert isinstance(ctx.traceback, str)

    def test_scheduler_error_context_frozen(self) -> None:
        """SchedulerErrorContext is frozen — mutation raises FrozenInstanceError."""
        ctx = _make_scheduler_error_context()

        with pytest.raises(Exception, match="cannot assign to field"):  # FrozenInstanceError (dataclasses internal)
            ctx.job_name = "other_job"  # pyright: ignore[reportGeneralIssues]

    def test_scheduler_error_context_args_kwargs(self) -> None:
        """args and kwargs are recorded at registration time and accessible on context."""
        exc = TypeError("bad arg")

        ctx = SchedulerErrorContext(
            exception=exc,
            traceback="Traceback...\nTypeError: bad arg\n",
            job_name="task_with_args",
            job_group="my_group",
            args=(1, "hello", True),
            kwargs={"timeout": 30, "retry": False},
        )

        assert ctx.args == (1, "hello", True)
        assert ctx.kwargs == {"timeout": 30, "retry": False}
        assert ctx.job_group == "my_group"

    def test_scheduler_error_context_traceback_always_populated(self) -> None:
        """traceback is always a non-empty string (type is str, not str | None)."""
        exc = ValueError("test")
        tb_str = "Traceback (most recent call last):\n  ...\nValueError: test"

        ctx = SchedulerErrorContext(
            exception=exc,
            traceback=tb_str,
            job_name="job",
            job_group=None,
            args=(),
            kwargs={},
        )
        assert ctx.traceback == tb_str
        assert isinstance(ctx.traceback, str)
