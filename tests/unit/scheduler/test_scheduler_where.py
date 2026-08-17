"""Tests for Scheduler where= parameter: normalization, DI plan building, and forwarding.

Covers ``_normalize_where()`` and ``_build_predicate_invoker()`` (module-level helpers in
``hassette.scheduler.scheduler``) plus ``where=`` forwarding through ``schedule()`` and
all seven convenience methods. Mirrors the pattern in ``test_scheduler_error_handler.py``
for ``on_error=`` forwarding.
"""

from unittest.mock import MagicMock, patch

import pytest

from hassette.exceptions import DependencyInjectionError
from hassette.scheduler.classes import Job
from hassette.scheduler.scheduler import Scheduler, _build_predicate_invoker, _normalize_where
from hassette.scheduler.triggers import Every
from hassette.test_utils.helpers import noop

from .conftest import make_scheduler


def is_home() -> bool:
    return True


def is_dark() -> bool:
    return True


def _pred_zero_arg() -> bool:
    return True


def _pred_annotated_job(_job: Job) -> bool:
    return True


def _pred_optional_job(_job: Job | None = None) -> bool:
    return True


def _pred_job_with_extra_optional(_job: Job, _threshold: float = 0.5) -> bool:
    return True


def _pred_unannotated_one_arg(_x) -> bool:
    return True


def _pred_wrong_annotation(_x: int) -> bool:
    return True


def _pred_multiple_positional(_a: int, _b: str) -> bool:
    return True


# All 7 convenience methods accept where= and it ends up on the registered job.
_WHERE_CONVENIENCE_CALLS = [
    pytest.param(
        lambda s: s.run_in(noop, delay=60, where=_pred_zero_arg, name="all_seven_conv_methods_where_run_in"),
        id="run_in",
    ),
    pytest.param(
        lambda s: s.run_once(noop, at="23:59", where=_pred_zero_arg, name="all_seven_conv_methods_where_run_once"),
        id="run_once",
    ),
    pytest.param(
        lambda s: s.run_every(noop, seconds=30, where=_pred_zero_arg, name="all_seven_conv_methods_where_run_every"),
        id="run_every",
    ),
    pytest.param(
        lambda s: s.run_minutely(noop, where=_pred_zero_arg, name="all_seven_conv_methods_where_run_minutely"),
        id="run_minutely",
    ),
    pytest.param(
        lambda s: s.run_hourly(noop, where=_pred_zero_arg, name="all_seven_conv_methods_where_run_hourly"),
        id="run_hourly",
    ),
    pytest.param(
        lambda s: s.run_daily(noop, at="00:00", where=_pred_zero_arg, name="all_seven_conv_methods_where_run_daily"),
        id="run_daily",
    ),
    pytest.param(
        lambda s: s.run_cron(noop, "0 * * * *", where=_pred_zero_arg, name="all_seven_conv_methods_where_run_cron"),
        id="run_cron",
    ),
]


class TestBuildPredicateInvoker:
    """Unit tests for `_build_predicate_invoker()` — DI-based Job detection."""

    @pytest.mark.parametrize(
        ("pred", "expected_param_count"),
        [
            pytest.param(_pred_zero_arg, 0, id="zero_arg"),
            pytest.param(_pred_annotated_job, 1, id="annotated_job"),
            pytest.param(_pred_optional_job, 1, id="optional_job"),
            pytest.param(_pred_job_with_extra_optional, 1, id="job_with_extra_optional"),
            pytest.param(_pred_unannotated_one_arg, 0, id="unannotated_one_arg"),
            pytest.param(_pred_wrong_annotation, 0, id="wrong_annotation"),
            pytest.param(_pred_multiple_positional, 0, id="multiple_positional"),
        ],
    )
    def test_param_count_for_predicate_signature(self, pred, expected_param_count: int) -> None:
        invoker = _build_predicate_invoker(pred)
        assert len(invoker.params) == expected_param_count

    def test_annotated_scheduled_job_param_has_source_type(self) -> None:
        invoker = _build_predicate_invoker(_pred_annotated_job)
        assert invoker.params[0].source_type is Job

    def test_scheduled_job_with_extra_optional_param_name(self) -> None:
        invoker = _build_predicate_invoker(_pred_job_with_extra_optional)
        assert invoker.params[0].name == "_job"

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
        def pred(job: Job) -> bool:
            return job.name == "test"

        invoker = _build_predicate_invoker(pred)
        mock_job = MagicMock(spec=Job)
        mock_job.name = "test"

        kwargs = invoker.invoke({Job: mock_job})
        assert kwargs == {"job": mock_job}

    def test_invoker_resolves_empty_kwargs_for_zero_arg(self) -> None:
        def pred() -> bool:
            return True

        invoker = _build_predicate_invoker(pred)
        kwargs = invoker.invoke({Job: MagicMock()})
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
        def pred(_job: Job) -> bool:
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
        kwargs = invoker.invoke({Job: MagicMock(spec=Job)})
        assert predicate(**kwargs) is False
        assert calls == ["true", "false"]

    def test_sequence_all_true_predicates_returns_true(self) -> None:
        predicate, invoker = _normalize_where([lambda: True, lambda: True])
        assert predicate is not None
        assert invoker is not None
        kwargs = invoker.invoke({Job: MagicMock(spec=Job)})
        assert predicate(**kwargs) is True

    def test_sequence_with_async_member_raises_type_error_at_registration(self) -> None:
        async def async_pred() -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            _normalize_where([lambda: True, async_pred])

    def test_sequence_member_with_scheduled_job_annotation_receives_job(self) -> None:
        seen: list[str] = []

        def job_pred(job: Job) -> bool:
            seen.append(job.name)
            return job.name == "expected"

        predicate, invoker = _normalize_where([lambda: True, job_pred])
        assert predicate is not None
        assert invoker is not None

        mock_job = MagicMock(spec=Job)
        mock_job.name = "expected"
        kwargs = invoker.invoke({Job: mock_job})
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
        kwargs = invoker.invoke({Job: MagicMock(spec=Job)})
        assert predicate(**kwargs) is True


class TestScheduleAcceptsWhere:
    """`Scheduler.schedule()` accepts where= and stores the normalized predicate on the job."""

    async def test_schedule_stores_zero_arg_predicate(self, patched_scheduler: Scheduler) -> None:
        def pred() -> bool:
            return True

        job = await patched_scheduler.schedule(
            noop, Every(hours=1), where=pred, name="schedule_stores_zero_arg_predicate_schedule"
        )

        assert job.predicate is pred
        assert job.predicate_invoker is not None
        assert len(job.predicate_invoker.params) == 0

    async def test_schedule_stores_annotated_predicate_with_invoker(self, patched_scheduler: Scheduler) -> None:
        def pred(_job: Job) -> bool:
            return True

        job = await patched_scheduler.schedule(
            noop, Every(hours=1), where=pred, name="schedule_stores_annotated_predicate_with_schedule"
        )

        assert job.predicate is pred
        assert job.predicate_invoker is not None
        assert len(job.predicate_invoker.params) == 1

    async def test_schedule_defaults_predicate_to_none(self, patched_scheduler: Scheduler) -> None:
        job = await patched_scheduler.schedule(
            noop, Every(hours=1), name="schedule_defaults_predicate_to_none_schedule"
        )

        assert job.predicate is None
        assert job.predicate_invoker is None

    async def test_schedule_raises_for_async_predicate(self, patched_scheduler: Scheduler) -> None:
        async def pred() -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            await patched_scheduler.schedule(
                noop, Every(hours=1), where=pred, name="schedule_raises_for_async_predicate_schedule"
            )


class TestConvenienceMethodsForwardWhereToJob:
    """All seven convenience methods accept where= and it ends up on the registered job."""

    @pytest.mark.parametrize("call", _WHERE_CONVENIENCE_CALLS)
    async def test_convenience_method_stores_where_on_job(self, patched_scheduler: Scheduler, call) -> None:
        job = await call(patched_scheduler)
        assert job.predicate is _pred_zero_arg


class TestConvenienceMethodsForwardWhereKwarg:
    """Verify each convenience method passes where= through to schedule() as a kwarg."""

    async def _assert_forwards_where(self, call) -> None:
        scheduler = make_scheduler()

        async def fake_schedule(*_args, **_kwargs) -> MagicMock:
            return MagicMock()

        def pred() -> bool:
            return True

        with patch.object(scheduler, "schedule", side_effect=fake_schedule) as mock_schedule:
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
