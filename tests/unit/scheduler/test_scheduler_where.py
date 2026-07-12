"""Tests for Scheduler where= parameter: normalization, DI plan building, and forwarding.

Covers ``_normalize_where()`` and ``_build_predicate_invoker()`` (module-level helpers in
``hassette.scheduler.scheduler``) plus ``where=`` forwarding through ``schedule()`` and
all seven convenience methods. Mirrors the pattern in ``test_scheduler_error_handler.py``
for ``on_error=`` forwarding.
"""

from unittest.mock import MagicMock, patch

import pytest

from hassette.exceptions import DependencyInjectionError
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import _build_predicate_invoker, _normalize_where
from hassette.scheduler.triggers import Every
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.test_utils.helpers import noop

from .conftest import PATCH_TARGET, make_scheduler


def is_home() -> bool:
    return True


def is_dark() -> bool:
    return True


class TestBuildPredicateInvoker:
    """Unit tests for `_build_predicate_invoker()` — DI-based ScheduledJob detection."""

    def test_zero_arg_predicate_empty_plan(self) -> None:
        def pred() -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == 0

    def test_annotated_scheduled_job_has_plan(self) -> None:
        def pred(_job: ScheduledJob) -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == 1
        assert invoker.params[0].source_type is ScheduledJob

    def test_optional_scheduled_job_annotation_has_plan(self) -> None:
        def pred(_job: ScheduledJob | None = None) -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == 1

    def test_scheduled_job_with_extra_optional_has_plan(self) -> None:
        def pred(_job: ScheduledJob, _threshold: float = 0.5) -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == 1
        assert invoker.params[0].name == "_job"

    def test_unannotated_one_arg_empty_plan(self) -> None:
        def pred(_x) -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == 0

    def test_wrong_annotation_empty_plan(self) -> None:
        def pred(_x: int) -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == 0

    def test_multiple_positional_no_scheduled_job_empty_plan(self) -> None:
        def pred(_a: int, _b: str) -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == 0

    def test_async_predicate_raises_type_error(self) -> None:
        async def pred() -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            _build_predicate_invoker(pred)

    def test_async_callable_instance_raises_type_error(self) -> None:
        class AsyncPred:
            async def __call__(self) -> bool:
                return True

        with pytest.raises(TypeError, match="synchronous"):
            _build_predicate_invoker(AsyncPred())

    def test_no_introspectable_signature_defaults_to_empty_plan(self) -> None:
        def pred() -> bool:
            return True

        with patch("hassette.scheduler.scheduler.get_typed_signature", side_effect=ValueError("no signature")):
            invoker = _build_predicate_invoker(pred)
            assert len(invoker.params) == 0

    def test_lambda_empty_plan(self) -> None:
        invoker = _build_predicate_invoker(lambda: True)
        assert len(invoker.params) == 0

    def test_var_positional_predicate_raises_di_error(self) -> None:
        """Predicates with *args are rejected at registration, matching bus handler behavior."""

        def pred(*_args) -> bool:
            return True

        with pytest.raises(DependencyInjectionError, match="\\*args"):
            _build_predicate_invoker(pred)

    def test_invoker_resolves_kwargs_for_annotated_predicate(self) -> None:
        def pred(job: ScheduledJob) -> bool:
            return job.name == "test"

        invoker = _build_predicate_invoker(pred)
        mock_job = MagicMock(spec=ScheduledJob)
        mock_job.name = "test"

        kwargs = invoker.invoke({ScheduledJob: mock_job})
        assert kwargs == {"job": mock_job}

    def test_invoker_resolves_empty_kwargs_for_zero_arg(self) -> None:
        def pred() -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        kwargs = invoker.invoke({ScheduledJob: MagicMock()})
        assert kwargs == {}


class TestNormalizeWhere:
    """Unit tests for `_normalize_where()` — the single entry point used by `schedule()`."""

    def test_none_returns_none_predicate_and_none_invoker(self) -> None:
        predicate, invoker = _normalize_where(None)
        assert predicate is None
        assert invoker is None

    def test_single_zero_arg_callable_stored_directly(self) -> None:
        def pred() -> bool:
            return True

        predicate, invoker = _normalize_where(pred)
        assert predicate is pred
        assert invoker is not None
        assert len(invoker.params) == 0

    def test_single_annotated_callable_has_invoker_with_plan(self) -> None:
        def pred(_job: ScheduledJob) -> bool:
            return True

        predicate, invoker = _normalize_where(pred)
        assert predicate is pred
        assert invoker is not None
        assert len(invoker.params) == 1

    def test_sequence_collapses_into_combinator_anding_results(self) -> None:
        calls: list[str] = []

        def pred_true() -> bool:
            calls.append("true")
            return True

        def pred_false() -> bool:
            calls.append("false")
            return False

        predicate, invoker = _normalize_where([pred_true, pred_false])

        assert invoker is not None
        assert len(invoker.params) == 1, "Combinator invoker should inject the job"
        assert callable(predicate)
        assert predicate is not pred_true
        assert predicate is not pred_false
        kwargs = invoker.invoke({ScheduledJob: MagicMock(spec=ScheduledJob)})
        assert predicate(**kwargs) is False
        assert calls == ["true", "false"]

    def test_sequence_all_true_predicates_returns_true(self) -> None:
        predicate, invoker = _normalize_where([lambda: True, lambda: True])
        assert predicate is not None
        assert invoker is not None
        kwargs = invoker.invoke({ScheduledJob: MagicMock(spec=ScheduledJob)})
        assert predicate(**kwargs) is True

    def test_sequence_with_async_member_raises_type_error_at_registration(self) -> None:
        async def async_pred() -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            _normalize_where([lambda: True, async_pred])

    def test_sequence_member_with_scheduled_job_annotation_receives_job(self) -> None:
        seen: list[str] = []

        def job_pred(job: ScheduledJob) -> bool:
            seen.append(job.name)
            return job.name == "expected"

        predicate, invoker = _normalize_where([lambda: True, job_pred])
        assert predicate is not None
        assert invoker is not None

        mock_job = MagicMock(spec=ScheduledJob)
        mock_job.name = "expected"
        kwargs = invoker.invoke({ScheduledJob: mock_job})
        assert predicate(**kwargs) is True
        assert seen == ["expected"]

    def test_sequence_summarize_joins_member_names(self) -> None:
        # Module-level predicates: callable_stable_name renders <callable> for test-local closures.
        predicate, _ = _normalize_where([is_home, is_dark])
        assert predicate is not None
        assert predicate.summarize() == "is_home and is_dark"  # pyright: ignore[reportFunctionMemberAccess]

    def test_sequence_predicates_with_same_members_compare_equal(self) -> None:
        def p1() -> bool:
            return True

        def p2() -> bool:
            return False

        pred_a, _ = _normalize_where([p1, p2])
        pred_b, _ = _normalize_where([p1, p2])
        assert pred_a == pred_b

    def test_sequence_predicates_with_different_members_compare_unequal(self) -> None:
        def p1() -> bool:
            return True

        def p2() -> bool:
            return False

        pred_a, _ = _normalize_where([p1])
        pred_b, _ = _normalize_where([p1, p2])
        assert pred_a != pred_b

    def test_sequence_combinator_captures_tuple_not_mutable_list(self) -> None:
        preds: list = [lambda: True]

        predicate, invoker = _normalize_where(preds)
        preds.append(lambda: False)

        assert predicate is not None
        assert invoker is not None
        kwargs = invoker.invoke({ScheduledJob: MagicMock(spec=ScheduledJob)})
        assert predicate(**kwargs) is True


class TestScheduleAcceptsWhere:
    """`Scheduler.schedule()` accepts where= and stores the normalized predicate on the job."""

    async def test_schedule_stores_zero_arg_predicate(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            def pred() -> bool:
                return True

            job = await scheduler.schedule(
                noop, Every(hours=1), where=pred, name="schedule_stores_zero_arg_predicate_schedule"
            )

            assert job.predicate is pred
            assert job.predicate_invoker is not None
            assert len(job.predicate_invoker.params) == 0

    async def test_schedule_stores_annotated_predicate_with_invoker(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            def pred(_job: ScheduledJob) -> bool:
                return True

            job = await scheduler.schedule(
                noop, Every(hours=1), where=pred, name="schedule_stores_annotated_predicate_with_schedule"
            )

            assert job.predicate is pred
            assert job.predicate_invoker is not None
            assert len(job.predicate_invoker.params) == 1

    async def test_schedule_defaults_predicate_to_none(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            job = await scheduler.schedule(noop, Every(hours=1), name="schedule_defaults_predicate_to_none_schedule")

            assert job.predicate is None
            assert job.predicate_invoker is None

    async def test_schedule_raises_for_async_predicate(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            async def pred() -> bool:
                return True

            with pytest.raises(TypeError, match="synchronous"):
                await scheduler.schedule(
                    noop, Every(hours=1), where=pred, name="schedule_raises_for_async_predicate_schedule"
                )


class TestConvenienceMethodsForwardWhereToJob:
    """All seven convenience methods accept where= and it ends up on the registered job."""

    async def test_all_seven_convenience_methods_store_where_on_job(self) -> None:
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()

            def pred() -> bool:
                return True

            job_run_in = await scheduler.run_in(noop, delay=60, where=pred, name="all_seven_conv_methods_where_run_in")
            assert job_run_in.predicate is pred

            job_run_once = await scheduler.run_once(
                noop, at="23:59", where=pred, name="all_seven_conv_methods_where_run_once"
            )
            assert job_run_once.predicate is pred

            job_run_every = await scheduler.run_every(
                noop, seconds=30, where=pred, name="all_seven_conv_methods_where_run_every"
            )
            assert job_run_every.predicate is pred

            job_run_minutely = await scheduler.run_minutely(
                noop, where=pred, name="all_seven_conv_methods_where_run_minutely"
            )
            assert job_run_minutely.predicate is pred

            job_run_hourly = await scheduler.run_hourly(
                noop, where=pred, name="all_seven_conv_methods_where_run_hourly"
            )
            assert job_run_hourly.predicate is pred

            job_run_daily = await scheduler.run_daily(
                noop, at="00:00", where=pred, name="all_seven_conv_methods_where_run_daily"
            )
            assert job_run_daily.predicate is pred

            job_run_cron = await scheduler.run_cron(
                noop, "0 * * * *", where=pred, name="all_seven_conv_methods_where_run_cron"
            )
            assert job_run_cron.predicate is pred


class TestConvenienceMethodsForwardWhereKwarg:
    """Verify each convenience method passes where= through to schedule() as a kwarg."""

    async def _assert_forwards_where(self, call) -> None:
        scheduler = make_scheduler()

        async def fake_schedule(*_args, **_kwargs) -> MagicMock:
            return MagicMock()

        def pred() -> bool:
            return True

        with patch.object(
            scheduler, "schedule", side_effect=fake_schedule
        ) as mock_schedule:  # boundary-exempt: self-shunt verifying kwarg forwarding
            await call(scheduler, pred)

        assert mock_schedule.call_args.kwargs["where"] is pred

    async def test_run_in_forwards_where(self) -> None:
        await self._assert_forwards_where(
            lambda s, pred: s.run_in(noop, delay=60, where=pred, name="run_in_forwards_where_run_in")
        )

    async def test_run_once_forwards_where(self) -> None:
        await self._assert_forwards_where(
            lambda s, pred: s.run_once(noop, at="23:59", where=pred, name="run_once_forwards_where_run_once")
        )

    async def test_run_every_forwards_where(self) -> None:
        await self._assert_forwards_where(
            lambda s, pred: s.run_every(noop, seconds=30, where=pred, name="run_every_forwards_where_run_every")
        )

    async def test_run_minutely_forwards_where(self) -> None:
        await self._assert_forwards_where(
            lambda s, pred: s.run_minutely(noop, where=pred, name="run_minutely_forwards_where_run_minutely")
        )

    async def test_run_hourly_forwards_where(self) -> None:
        await self._assert_forwards_where(
            lambda s, pred: s.run_hourly(noop, where=pred, name="run_hourly_forwards_where_run_hourly")
        )

    async def test_run_daily_forwards_where(self) -> None:
        await self._assert_forwards_where(
            lambda s, pred: s.run_daily(noop, at="00:00", where=pred, name="run_daily_forwards_where_run_daily")
        )

    async def test_run_cron_forwards_where(self) -> None:
        await self._assert_forwards_where(
            lambda s, pred: s.run_cron(noop, "0 * * * *", where=pred, name="run_cron_forwards_where_run_cron")
        )
