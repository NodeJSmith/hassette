"""Tests for Scheduler where= parameter: normalization, arity detection, and forwarding.

Covers ``_normalize_where()`` and ``_predicate_wants_job()`` (module-level helpers in
``hassette.scheduler.scheduler``) plus ``where=`` forwarding through ``schedule()`` and
all seven convenience methods. Mirrors the pattern in ``test_scheduler_error_handler.py``
for ``on_error=`` forwarding.
"""

from unittest.mock import MagicMock, patch

import pytest

from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import _normalize_where, _predicate_wants_job
from hassette.scheduler.triggers import Every
from hassette.test_utils.config import TEST_SOURCE_LOCATION

from .conftest import make_scheduler, noop

PATCH_TARGET = "hassette.scheduler.scheduler.capture_registration_source"


class TestPredicateArityDetection:
    """Unit tests for `_predicate_wants_job()` — inspects a single callable's signature."""

    def test_zero_arg_predicate_wants_job_false(self) -> None:
        """A predicate with no parameters sets wants_job=False."""

        def pred() -> bool:
            return True

        assert _predicate_wants_job(pred) is False

    def test_one_required_arg_predicate_wants_job_true(self) -> None:
        """A predicate with one required positional parameter sets wants_job=True."""

        def pred(_job: ScheduledJob) -> bool:
            return True

        assert _predicate_wants_job(pred) is True

    def test_one_optional_arg_predicate_wants_job_true(self) -> None:
        """A predicate with one optional positional parameter also sets wants_job=True."""

        def pred(_job: ScheduledJob | None = None) -> bool:
            return True

        assert _predicate_wants_job(pred) is True

    def test_more_than_one_required_positional_raises_type_error(self) -> None:
        """More than one required positional parameter raises TypeError at registration."""

        def pred(_a: int, _b: int) -> bool:
            return True

        with pytest.raises(TypeError, match="required positional"):
            _predicate_wants_job(pred)

    def test_required_keyword_only_parameter_raises_type_error(self) -> None:
        """A required keyword-only parameter raises TypeError — dispatch can't supply it."""

        def pred(*, flag: bool) -> bool:
            return flag

        with pytest.raises(TypeError, match="keyword-only"):
            _predicate_wants_job(pred)

    def test_async_predicate_raises_type_error(self) -> None:
        """An async predicate raises TypeError at registration time."""

        async def pred() -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            _predicate_wants_job(pred)

    def test_no_introspectable_signature_defaults_to_zero_arg(self) -> None:
        """A predicate whose signature can't be inspected fails safe to zero-arg."""

        def pred() -> bool:
            return True

        with patch("hassette.scheduler.scheduler.inspect.signature", side_effect=ValueError("no signature")):
            assert _predicate_wants_job(pred) is False


class TestNormalizeWhere:
    """Unit tests for `_normalize_where()` — the single entry point used by `schedule()`."""

    def test_none_returns_none_predicate_and_false(self) -> None:
        """where=None normalizes to (None, False)."""
        predicate, wants_job = _normalize_where(None)
        assert predicate is None
        assert wants_job is False

    def test_single_zero_arg_callable_stored_directly(self) -> None:
        """A single zero-arg callable is stored directly, not wrapped."""

        def pred() -> bool:
            return True

        predicate, wants_job = _normalize_where(pred)
        assert predicate is pred
        assert wants_job is False

    def test_single_one_arg_callable_sets_wants_job_true(self) -> None:
        """A single one-arg callable is stored directly and wants_job is True."""

        def pred(_job: ScheduledJob) -> bool:
            return True

        predicate, wants_job = _normalize_where(pred)
        assert predicate is pred
        assert wants_job is True

    def test_sequence_collapses_into_zero_arg_closure_anding_results(self) -> None:
        """A sequence of predicates collapses into a single zero-arg closure that ANDs them."""
        calls: list[str] = []

        def pred_true() -> bool:
            calls.append("true")
            return True

        def pred_false() -> bool:
            calls.append("false")
            return False

        predicate, wants_job = _normalize_where([pred_true, pred_false])

        assert wants_job is False
        assert callable(predicate)
        assert predicate is not pred_true
        assert predicate is not pred_false
        assert predicate() is False
        assert calls == ["true", "false"]

    def test_sequence_all_true_predicates_returns_true(self) -> None:
        """A sequence where every predicate returns True collapses to a True result."""
        predicate, _ = _normalize_where([lambda: True, lambda: True])
        assert predicate is not None
        assert predicate() is True

    def test_sequence_with_async_member_raises_type_error_at_registration(self) -> None:
        """An async predicate inside a sequence raises TypeError at registration time."""

        async def async_pred() -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            _normalize_where([lambda: True, async_pred])

    def test_sequence_closure_captures_tuple_not_mutable_list(self) -> None:
        """The closure captures preds as a tuple — later mutation of the original list
        passed by the caller does not affect the already-collapsed predicate."""
        preds: list = [lambda: True]

        predicate, _ = _normalize_where(preds)
        preds.append(lambda: False)

        assert predicate is not None
        assert predicate() is True


class TestScheduleAcceptsWhere:
    """`Scheduler.schedule()` accepts where= and stores the normalized predicate on the job."""

    async def test_schedule_stores_zero_arg_predicate(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            def pred() -> bool:
                return True

            job = await scheduler.schedule(noop, Every(hours=1), where=pred)

            assert job.predicate is pred
            assert job._predicate_wants_job is False

    async def test_schedule_stores_one_arg_predicate_with_wants_job_true(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            def pred(_job: ScheduledJob) -> bool:
                return True

            job = await scheduler.schedule(noop, Every(hours=1), where=pred)

            assert job.predicate is pred
            assert job._predicate_wants_job is True

    async def test_schedule_defaults_predicate_to_none(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            job = await scheduler.schedule(noop, Every(hours=1))

            assert job.predicate is None
            assert job._predicate_wants_job is False

    async def test_schedule_raises_for_async_predicate(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            async def pred() -> bool:
                return True

            with pytest.raises(TypeError, match="synchronous"):
                await scheduler.schedule(noop, Every(hours=1), where=pred)


class TestConvenienceMethodsForwardWhereToJob:
    """All seven convenience methods accept where= and it ends up on the registered job."""

    async def test_all_seven_convenience_methods_store_where_on_job(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            def pred() -> bool:
                return True

            job_run_in = await scheduler.run_in(noop, delay=60, where=pred)
            assert job_run_in.predicate is pred

            job_run_once = await scheduler.run_once(noop, at="23:59", where=pred)
            assert job_run_once.predicate is pred

            job_run_every = await scheduler.run_every(noop, seconds=30, where=pred)
            assert job_run_every.predicate is pred

            job_run_minutely = await scheduler.run_minutely(noop, where=pred)
            assert job_run_minutely.predicate is pred

            job_run_hourly = await scheduler.run_hourly(noop, where=pred)
            assert job_run_hourly.predicate is pred

            job_run_daily = await scheduler.run_daily(noop, at="00:00", where=pred)
            assert job_run_daily.predicate is pred

            job_run_cron = await scheduler.run_cron(noop, "0 * * * *", where=pred)
            assert job_run_cron.predicate is pred


class TestConvenienceMethodsForwardWhereKwarg:
    """Verify each convenience method passes where= through to schedule() as a kwarg."""

    async def _assert_forwards_where(self, call) -> None:
        """Patch scheduler.schedule with a fresh coroutine-returning stub and assert the
        where= kwarg was forwarded from the convenience method call."""
        scheduler = make_scheduler()

        async def fake_schedule(*_args, **_kwargs) -> MagicMock:
            return MagicMock()

        def pred() -> bool:
            return True

        with patch.object(scheduler, "schedule", side_effect=fake_schedule) as mock_schedule:
            await call(scheduler, pred)

        assert mock_schedule.call_args.kwargs["where"] is pred

    async def test_run_in_forwards_where(self) -> None:
        await self._assert_forwards_where(lambda s, pred: s.run_in(noop, delay=60, where=pred))

    async def test_run_once_forwards_where(self) -> None:
        await self._assert_forwards_where(lambda s, pred: s.run_once(noop, at="23:59", where=pred))

    async def test_run_every_forwards_where(self) -> None:
        await self._assert_forwards_where(lambda s, pred: s.run_every(noop, seconds=30, where=pred))

    async def test_run_minutely_forwards_where(self) -> None:
        await self._assert_forwards_where(lambda s, pred: s.run_minutely(noop, where=pred))

    async def test_run_hourly_forwards_where(self) -> None:
        await self._assert_forwards_where(lambda s, pred: s.run_hourly(noop, where=pred))

    async def test_run_daily_forwards_where(self) -> None:
        await self._assert_forwards_where(lambda s, pred: s.run_daily(noop, at="00:00", where=pred))

    async def test_run_cron_forwards_where(self) -> None:
        await self._assert_forwards_where(lambda s, pred: s.run_cron(noop, "0 * * * *", where=pred))
