"""Tests for Scheduler job name uniqueness validation."""

from unittest.mock import AsyncMock

import pytest

from hassette.exceptions import SchedulerNameRequiredError
from hassette.scheduler.triggers import After, Every
from tests.support.factories import make_scheduled_job, make_scheduler
from tests.support.helpers import noop


class TestJobNameUniqueness:
    async def test_duplicate_name_raises(self) -> None:
        scheduler = make_scheduler()
        await scheduler.add_job(make_scheduled_job(name="daily_backup"))

        with pytest.raises(ValueError, match="daily_backup"):
            await scheduler.add_job(make_scheduled_job(name="daily_backup"))

    async def test_different_names_ok(self) -> None:
        scheduler = make_scheduler()
        await scheduler.add_job(make_scheduled_job(name="job_a"))
        await scheduler.add_job(make_scheduled_job(name="job_b"))

        assert set(scheduler._jobs_by_name) == {"job_a", "job_b"}

    async def test_removal_allows_reuse(self) -> None:
        scheduler = make_scheduler()
        job = make_scheduled_job(name="ephemeral")
        await scheduler.add_job(job)
        assert "ephemeral" in scheduler._jobs_by_name

        # Simulate callback-based removal (as fired by scheduler_service.dequeue_job)
        scheduler._on_job_removed(job)
        assert "ephemeral" not in scheduler._jobs_by_name

        # Re-adding with the same name should now succeed
        await scheduler.add_job(make_scheduled_job(name="ephemeral"))
        assert "ephemeral" in scheduler._jobs_by_name

    async def test_remove_all_clears_names(self) -> None:
        scheduler = make_scheduler()
        await scheduler.add_job(make_scheduled_job(name="a"))
        await scheduler.add_job(make_scheduled_job(name="b"))
        assert set(scheduler._jobs_by_name) == {"a", "b"}

        scheduler.remove_all_jobs()
        assert scheduler._jobs_by_name == {}


class TestIfExistsSkip:
    async def test_skip_returns_existing_when_matching(self) -> None:
        """if_exists='skip' returns the existing job when everything matches."""
        scheduler = make_scheduler()
        fn = lambda: None  # noqa: E731
        job1 = make_scheduled_job(name="poll", job=fn)
        added = await scheduler.add_job(job1)

        job2 = make_scheduled_job(name="poll", job=fn)
        result = await scheduler.add_job(job2, if_exists="skip")

        assert result is added

    async def test_skip_raises_when_config_differs(self) -> None:
        """if_exists='skip' still raises when the name matches but config differs."""
        scheduler = make_scheduler()
        fn_a = lambda: None  # noqa: E731
        fn_b = lambda: None  # noqa: E731
        await scheduler.add_job(make_scheduled_job(name="poll", job=fn_a))

        with pytest.raises(ValueError, match="poll"):
            await scheduler.add_job(make_scheduled_job(name="poll", job=fn_b), if_exists="skip")

    async def test_skip_checks_trigger_equality(self) -> None:
        """if_exists='skip' considers trigger type and value."""
        scheduler = make_scheduler()
        fn = lambda: None  # noqa: E731
        trigger_30s = Every(seconds=30)
        trigger_60s = Every(seconds=60)

        await scheduler.add_job(make_scheduled_job(name="poll", job=fn, trigger=trigger_30s))

        # Same trigger config → skip
        same_trigger = Every(seconds=30)
        result = await scheduler.add_job(
            make_scheduled_job(name="poll", job=fn, trigger=same_trigger), if_exists="skip"
        )
        assert result is scheduler._jobs_by_name["poll"]

        # Different trigger config → error
        with pytest.raises(ValueError, match="poll"):
            await scheduler.add_job(make_scheduled_job(name="poll", job=fn, trigger=trigger_60s), if_exists="skip")

    async def test_error_mode_always_raises_on_duplicate(self) -> None:
        """Default if_exists='error' raises even when config matches."""
        scheduler = make_scheduler()
        fn = lambda: None  # noqa: E731
        await scheduler.add_job(make_scheduled_job(name="poll", job=fn))

        with pytest.raises(ValueError, match="poll"):
            await scheduler.add_job(make_scheduled_job(name="poll", job=fn))


class TestIfExistsReplace:
    async def test_replace_cancels_old_and_registers_new(self) -> None:
        """if_exists='replace' cancels the existing job and registers the new one."""
        scheduler = make_scheduler(wire_dequeue=True)
        fn_old = lambda: None  # noqa: E731
        fn_new = lambda: None  # noqa: E731
        old_job = await scheduler.add_job(make_scheduled_job(name="sensor_check", job=fn_old))

        new_job = make_scheduled_job(name="sensor_check", job=fn_new)
        result = await scheduler.add_job(new_job, if_exists="replace")

        assert result is new_job
        assert scheduler._jobs_by_name["sensor_check"] is new_job
        assert old_job._dequeued is True

    async def test_replace_with_no_existing_job(self) -> None:
        """if_exists='replace' with no pre-existing job behaves like a normal add."""
        scheduler = make_scheduler(wire_dequeue=True)
        fn = lambda: None  # noqa: E731
        job = make_scheduled_job(name="fresh_job", job=fn)

        result = await scheduler.add_job(job, if_exists="replace")

        assert result is job
        assert scheduler._jobs_by_name["fresh_job"] is job

    async def test_replace_preserves_group_membership_of_new_job(self) -> None:
        """if_exists='replace' cleans up old job's group and adds new job to its group."""
        scheduler = make_scheduler(wire_dequeue=True)
        fn_old = lambda: None  # noqa: E731
        fn_new = lambda: None  # noqa: E731
        old_job = make_scheduled_job(name="check", job=fn_old, group="monitors")
        await scheduler.add_job(old_job)

        new_job = make_scheduled_job(name="check", job=fn_new, group="monitors")
        await scheduler.add_job(new_job, if_exists="replace")

        assert new_job in scheduler._jobs_by_group["monitors"]
        assert old_job not in scheduler._jobs_by_group["monitors"]

    async def test_replace_returns_new_job_not_old(self) -> None:
        """if_exists='replace' returns the newly registered job object."""
        scheduler = make_scheduler(wire_dequeue=True)
        fn = lambda: None  # noqa: E731
        old_job = await scheduler.add_job(make_scheduled_job(name="poller", job=fn))

        new_job = make_scheduled_job(name="poller", job=fn, trigger=Every(seconds=120))
        result = await scheduler.add_job(new_job, if_exists="replace")

        assert result is new_job
        assert result is not old_job

    async def test_replace_cross_group(self) -> None:
        """if_exists='replace' moves from old group to new group correctly."""
        scheduler = make_scheduler(wire_dequeue=True)
        fn_old = lambda: None  # noqa: E731
        fn_new = lambda: None  # noqa: E731
        old_job = make_scheduled_job(name="check", job=fn_old, group="old_group")
        await scheduler.add_job(old_job)

        new_job = make_scheduled_job(name="check", job=fn_new, group="new_group")
        await scheduler.add_job(new_job, if_exists="replace")

        assert "old_group" not in scheduler._jobs_by_group or scheduler._jobs_by_group["old_group"] == set()
        assert new_job in scheduler._jobs_by_group["new_group"]

    async def test_replace_failure_leaves_no_old_and_no_partial_new(self) -> None:
        """When the new registration's ``add_job()`` raises after the old job's removal
        write has already succeeded, the old registration must be gone (removed) and the
        new registration must never become live (no partial state, no residual name/group
        entry). Also asserts the write-ordering guarantee that replacement depends on: the
        old job's ``mark_job_removed`` write is awaited strictly before the new job's
        ``add_job`` upsert is attempted — the exact fire-and-forget race this behavior
        exists to prevent.
        """
        scheduler = make_scheduler(wire_dequeue=True)
        fn_old = lambda: None  # noqa: E731
        fn_new = lambda: None  # noqa: E731
        old_job = await scheduler.add_job(make_scheduled_job(name="sensor_check", job=fn_old))
        assert old_job.db_id is not None

        call_order: list[str] = []

        async def _tracking_mark_job_removed(db_id: int) -> None:
            call_order.append(f"mark_job_removed:{db_id}")

        async def _failing_add_job(job) -> None:
            call_order.append(f"add_job:{job.name}")
            raise RuntimeError("simulated new-registration failure")

        scheduler.scheduler_service.mark_job_removed = AsyncMock(side_effect=_tracking_mark_job_removed)
        scheduler.scheduler_service.add_job = AsyncMock(side_effect=_failing_add_job)

        new_job = make_scheduled_job(name="sensor_check", job=fn_new)

        with pytest.raises(RuntimeError, match="simulated new-registration failure"):
            await scheduler.add_job(new_job, if_exists="replace")

        # Write-ordering guarantee: old removal write awaited before the new upsert is attempted.
        assert call_order == [f"mark_job_removed:{old_job.db_id}", "add_job:sensor_check"]

        # Old registration is gone.
        assert old_job._dequeued is True

        # New registration never became live: its add_job() raised before mark_registered()
        # ran, so it has no db_id (no partial DB row), and the name is freed entirely (both
        # the old and the failed-new job are gone from the local indexes).
        assert new_job.db_id is None
        assert "sensor_check" not in scheduler._jobs_by_name

        # Rollback ran for the failed new job specifically (identity, not just name),
        # through the unified removal operation.
        scheduler.scheduler_service.remove_job.assert_any_call(new_job)

    async def test_rollback_removes_generic_job_after_post_persist_failure(self) -> None:
        """Generic (non-EntityTime, non-replace) rollback path: a plain registration whose
        persistence succeeds (``db_id`` assigned) but a later registration step fails must
        leave no registry, group, or name residue, and the persisted row must be marked
        removed via ``mark_job_removed``. Exercises ``Scheduler._rollback_failed_registration()``
        through the ordinary ``add_job()`` path (no ``if_exists='replace'`` involved).
        """
        scheduler = make_scheduler(wire_dequeue=True)
        fn = lambda: None  # noqa: E731

        async def _persist_then_fail(job) -> None:
            job.mark_registered(42)  # simulates persist + registry insertion succeeding
            raise RuntimeError("simulated enqueue failure")

        scheduler.scheduler_service.add_job = AsyncMock(side_effect=_persist_then_fail)

        job = make_scheduled_job(name="flaky_job", job=fn, group="monitors")

        with pytest.raises(RuntimeError, match="simulated enqueue failure"):
            await scheduler.add_job(job)

        assert job.db_id == 42
        assert "flaky_job" not in scheduler._jobs_by_name
        assert job not in scheduler._jobs_by_group.get("monitors", set())
        scheduler.scheduler_service.remove_job.assert_awaited_once_with(job)
        scheduler.scheduler_service.mark_job_removed.assert_awaited_once_with(42)


class TestSchedulerNameRequired:
    """Empty ``name=""`` raises SchedulerNameRequiredError on every registration entry point."""

    async def test_schedule_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.schedule(noop, Every(hours=1), name="")

    async def test_run_in_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.run_in(noop, 5, name="")

    async def test_run_once_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.run_once(noop, at="23:59", name="")

    async def test_run_every_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.run_every(noop, minutes=5, name="")

    async def test_run_minutely_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.run_minutely(noop, minutes=5, name="")

    async def test_run_hourly_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.run_hourly(noop, hours=1, name="")

    async def test_run_daily_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.run_daily(noop, at="07:00", name="")

    async def test_run_cron_empty_name_raises(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.run_cron(noop, "0 9 * * 1-5", name="")

    async def test_add_job_empty_name_raises(self) -> None:
        """add_job() bypasses schedule() entirely, so it needs its own guard."""
        scheduler = make_scheduler()
        job = make_scheduled_job(name="")
        with pytest.raises(SchedulerNameRequiredError):
            await scheduler.add_job(job)


class TestSchedulerKeywordOnlyParams:
    """name, group, jitter, timeout, and timeout_disabled are keyword-only on every method."""

    async def test_schedule_positional_name_raises_typeerror(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(TypeError):
            await scheduler.schedule(  # pyright: ignore[reportCallIssue]
                noop, After(seconds=5), "positional_name"
            )

    async def test_run_in_positional_name_raises_typeerror(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(TypeError):
            await scheduler.run_in(noop, 5, "positional_name")  # pyright: ignore[reportCallIssue]

    async def test_run_in_positional_group_raises_typeerror(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(TypeError):
            await scheduler.run_in(noop, 5, "n", "grp")  # pyright: ignore[reportCallIssue]

    async def test_run_every_positional_jitter_raises_typeerror(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(TypeError):
            await scheduler.run_every(  # pyright: ignore[reportCallIssue]
                noop, 1, 0, 0, "n", None, 1.0
            )

    async def test_run_daily_positional_timeout_raises_typeerror(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(TypeError):
            await scheduler.run_daily(  # pyright: ignore[reportCallIssue]
                noop, "07:00", "n", None, None, 5.0
            )

    async def test_run_hourly_positional_timeout_disabled_raises_typeerror(self) -> None:
        scheduler = make_scheduler()
        with pytest.raises(TypeError):
            await scheduler.run_hourly(  # pyright: ignore[reportCallIssue]
                noop, 1, "n", None, None, None, True
            )
