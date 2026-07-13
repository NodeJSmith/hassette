"""Completeness guard and annotation-origin guard for the forgotten-await protection feature.

Covers:
    - Canonical protected-method list; completeness/drift test
    - Parametrized warning test over the full canonical list (primaries + delegates)
      PLUS the two-set completeness check:
        detected is a subset of (canonical | DOCUMENTED_EXCLUSIONS)
        canonical and DOCUMENTED_EXCLUSIONS are disjoint
    - Annotation-origin guard: every canonical method's return annotation
      __origin__ is collections.abc.Coroutine

This file is the single source of truth for the canonical protected-method list.
The per-class conversion tests (test_bus_coroutine_conversion.py, etc.) complement
these guards; this file owns the cross-class canonical constant and completeness check.
"""

import collections.abc
import gc
import inspect
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.api.api import Api
from hassette.bus.bus import Bus
from hassette.bus.listeners import Listener
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.triggers import Every as _Every
from hassette.test_utils.factories import make_mock_parent
from hassette.test_utils.helpers import noop
from hassette.utils.date_utils import now
from tests.unit.conftest import make_api

# Canonical protected-method list — single source of truth consumed by every guard in this file.

#: Every public registration/scheduling/fire-and-forget method across Bus,
#: Scheduler, and Api that is protected by the forgotten-await mechanism.
#: Includes primaries (Shape A, hold the guard_await) and delegates (Shape B,
#: thread the handle up from the primary).  See design/071 for the
#: full membership rationale.
CANONICAL_PROTECTED: dict[type, set[str]] = {
    Bus: {
        # Shape A primaries (true registration methods)
        "on",
        "on_state_change",
        "on_attribute_change",
        "on_call_service",
        "add_listener",
        "on_service_registered",
        "on_component_loaded",
        "on_hassette_service_status",
        "on_app_state_changed",
        # Shape B delegates (thread the handle from a primary above)
        "on_homeassistant_restart",
        "on_homeassistant_start",
        "on_homeassistant_stop",
        "on_websocket_connected",
        "on_websocket_disconnected",
        "on_app_running",
        "on_app_stopping",
        "on_hassette_service_failed",
        "on_hassette_service_crashed",
        "on_hassette_service_started",
    },
    Scheduler: {
        # Shape A primary
        "add_job",
        # Shape B delegates
        "schedule",
        "run_in",
        "run_once",
        "run_every",
        "run_minutely",
        "run_hourly",
        "run_daily",
        "run_cron",
    },
    Api: {
        # Shape A primaries
        "call_service",
        "fire_event",
        "set_state",
        # Shape B delegates → call_service
        "turn_on",
        "turn_off",
        "toggle_service",
    },
}

#: Inherited Resource/Service lifecycle methods that are detected but not protected.
#: These are framework plumbing, not user registration API — apps never call them.
#: The inherited-surface guard below fails when a NEW detected method appears on a
#: base class without being added here, to CANONICAL_PROTECTED, or to
#: DOCUMENTED_EXCLUSIONS — closing the vars(cls) blind spot for inherited methods.
#: Counterpart: ``LIFECYCLE_METHODS`` in codegen/src/hassette_codegen/sync_facade/ast_utils.py
#: covers the same concept for sync-facade generation; a new lifecycle async def
#: usually needs an entry in both.
INHERITED_LIFECYCLE_EXCLUSIONS: set[str] = {
    "after_initialize",
    "after_shutdown",
    "before_initialize",
    "before_shutdown",
    "cleanup",
    "initialize",
    "on_initialize",
    "on_shutdown",
    "shutdown",
    "wait_ready",
}

#: Methods that are *detected* by the completeness criterion (iscoroutinefunction
#: OR Coroutine[...] return annotation) but are intentionally *not* protected.
#:
#: Bus:       emit        — event delivery failure is observable downstream.
#:            on_initialize / on_shutdown — internal lifecycle hooks, not user API.
#: Scheduler: on_initialize / on_shutdown — same.
#: Api:       get_* / create_* / update_* / delete_* / list_* / reset_* /
#:            decrement_* / increment_* / entity_exists / *rest_request /
#:            ws_send_* / render_template / on_initialize
#:            — all return data that is consumed immediately; a dropped coroutine
#:            produces an AttributeError downstream (not silent). Also covers
#:            infrastructure helpers not part of the public automation API.
DOCUMENTED_EXCLUSIONS: dict[type, set[str]] = {
    Bus: {"emit", "on_initialize", "on_shutdown"},
    Scheduler: {"on_initialize", "on_shutdown"},
    Api: {
        # Lifecycle
        "on_initialize",
        # Data-returning query methods — fail loudly if dropped (AttributeError)
        "get_attribute",
        "get_calendar_events",
        "get_calendars",
        "get_camera_image",
        "get_config",
        "get_entity",
        "get_entity_or_none",
        "get_histories",
        "get_history",
        "get_logbook",
        "get_panels",
        "get_services",
        "get_state",
        "get_state_or_none",
        "get_state_raw",
        "get_state_value",
        "get_states",
        "get_states_raw",
        # Input-helper CRUD — return data; not silent on drop
        "create_counter",
        "create_input_boolean",
        "create_input_button",
        "create_input_datetime",
        "create_input_number",
        "create_input_select",
        "create_input_text",
        "create_timer",
        "decrement_counter",
        "delete_counter",
        "delete_entity",
        "delete_input_boolean",
        "delete_input_button",
        "delete_input_datetime",
        "delete_input_number",
        "delete_input_select",
        "delete_input_text",
        "delete_rest_request",
        "delete_timer",
        "entity_exists",
        "increment_counter",
        "list_counters",
        "list_input_booleans",
        "list_input_buttons",
        "list_input_datetimes",
        "list_input_numbers",
        "list_input_selects",
        "list_input_texts",
        "list_timers",
        "post_rest_request",
        "render_template",
        "reset_counter",
        "rest_request",
        "get_rest_request",
        "update_counter",
        "update_input_boolean",
        "update_input_button",
        "update_input_datetime",
        "update_input_number",
        "update_input_select",
        "update_input_text",
        "update_timer",
        # Infrastructure helpers — internal transport, not automation API
        "ws_send_and_wait",
        "ws_send_json",
    },
}


# Detection helper (same OR-semantics as the parity tests)


# add_listener is handled separately (requires a Listener object).
# sorted() pins the parametrize order: CANONICAL_PROTECTED[Bus] is a set, and unsorted set
# iteration order varies with PYTHONHASHSEED across processes. Without the sort, xdist workers
# collect these cases in different orders and abort with "Different tests were collected between
# gw0 and gwN" under `-n` (the suite only survived because pytest-randomly syncs the seed).
_BUS_METHODS_PARAMETRIZED = sorted(m for m in CANONICAL_PROTECTED[Bus] if m != "add_listener")
# add_job is handled separately (requires a ScheduledJob object).
# sorted() for the same cross-process determinism reason as _BUS_METHODS_PARAMETRIZED above.
_SCHED_METHODS_PARAMETRIZED = sorted(m for m in CANONICAL_PROTECTED[Scheduler] if m != "add_job")
_API_METHOD_CALLS: dict[str, object] = {
    "call_service": lambda api: api.call_service("light", "turn_on"),
    "fire_event": lambda api: api.fire_event("custom_event"),
    "set_state": lambda api: api.set_state("light.test", "on"),
    "turn_on": lambda api: api.turn_on("light.kitchen"),
    "turn_off": lambda api: api.turn_off("light.kitchen"),
    "toggle_service": lambda api: api.toggle_service("switch.fan"),
}


def _is_detected(cls: type, name: str) -> bool:
    """Return True if ``name`` on ``cls`` satisfies the completeness detection criterion.

    Detection: iscoroutinefunction(m) OR return annotation __origin__ is
    collections.abc.Coroutine.  Uses raw __annotations__ (not get_type_hints) to
    survive TYPE_CHECKING-guarded parameter annotations (HandlerType etc.) that
    are not available at test collection time.  Forward-ref string annotations
    are evaluated in the class module's globals.

    Uses inspect.getattr_static to resolve inherited methods that are not in
    vars(cls) directly, avoiding false negatives for subclassed methods.
    """
    method = inspect.getattr_static(cls, name, None)
    if method is None or not callable(method):
        return False
    if inspect.iscoroutinefunction(method):
        return True
    annotations = getattr(method, "__annotations__", {})
    return_ann = annotations.get("return")
    if return_ann is None:
        return False
    if isinstance(return_ann, str):
        module = sys.modules.get(cls.__module__)
        if module is None:
            return False
        try:
            return_ann = eval(return_ann, vars(module))  # noqa: S307 — resolving module annotation
        except Exception:
            return False
    return getattr(return_ann, "__origin__", None) is collections.abc.Coroutine


# Canonical list completeness/disjointness guard


class TestCompletenessGuard:
    """Enumeration-based drift guard for the canonical protected-method list.

    Fails if:
    (a) A new public method on Bus/Scheduler/Api is detected but absent from
        both CANONICAL_PROTECTED and DOCUMENTED_EXCLUSIONS — meaning a developer
        added a new registration/scheduling method without protecting it.
    (b) canonical_list and DOCUMENTED_EXCLUSIONS overlap — the two sets must be
        disjoint; an overlap means a method is both protected AND excluded, which
        is contradictory.
    """

    @pytest.mark.parametrize("cls", [Bus, Scheduler, Api], ids=lambda c: c.__name__)
    def test_every_detected_method_is_accounted_for(self, cls: type) -> None:
        """All detected methods are in canonical | exclusions — no unaccounted method."""
        canonical = CANONICAL_PROTECTED[cls]
        exclusions = DOCUMENTED_EXCLUSIONS[cls]
        accounted = canonical | exclusions

        def _is_callable_non_property(n: str) -> bool:
            raw = inspect.getattr_static(cls, n, None)
            # Exclude properties and other descriptors that aren't plain callables.
            if isinstance(raw, (property, classmethod, staticmethod)):
                return False
            return callable(raw)

        # Use vars(cls) to enumerate only methods defined directly on this class,
        # not inherited lifecycle hooks from Resource/Service parent classes.
        all_public_names = {n for n in vars(cls) if not n.startswith("_") and _is_callable_non_property(n)}
        detected = {n for n in all_public_names if _is_detected(cls, n)}

        unaccounted = detected - accounted
        assert not unaccounted, (
            f"{cls.__name__} has detected public methods not in CANONICAL_PROTECTED or "
            f"DOCUMENTED_EXCLUSIONS — a new registration/scheduling method was added without "
            f"protection.\nUnaccounted: {sorted(unaccounted)}\n"
            f"Add each to CANONICAL_PROTECTED (with guard_await conversion) or "
            f"DOCUMENTED_EXCLUSIONS (with a rationale comment) in "
            f"tests/unit/test_forgotten_await_completeness.py."
        )

    @pytest.mark.parametrize("cls", [Bus, Scheduler, Api], ids=lambda c: c.__name__)
    def test_inherited_detected_methods_are_accounted_for(self, cls: type) -> None:
        """Companion to the vars(cls) check above: cover the INHERITED surface.

        vars(cls) enumerates only directly-defined methods, so a registration-shaped
        ``async def`` added to the Resource/Service base classes would bypass the
        primary guard entirely.  This check walks dir(cls) minus vars(cls) and
        requires every detected inherited method to be a documented lifecycle
        exclusion (or explicitly canonical/excluded).
        """
        inherited_names = {n for n in dir(cls) if not n.startswith("_") and n not in vars(cls)}
        detected = {n for n in inherited_names if _is_detected(cls, n)}

        accounted = INHERITED_LIFECYCLE_EXCLUSIONS | CANONICAL_PROTECTED[cls] | DOCUMENTED_EXCLUSIONS[cls]
        unaccounted = detected - accounted
        assert not unaccounted, (
            f"{cls.__name__} inherits detected methods not accounted for — a new "
            f"registration-shaped async method was added to a base class without "
            f"forgotten-await protection.\nUnaccounted: {sorted(unaccounted)}\n"
            f"Add each to CANONICAL_PROTECTED (with guard_await conversion) or "
            f"INHERITED_LIFECYCLE_EXCLUSIONS (with a rationale) in "
            f"tests/unit/test_forgotten_await_completeness.py."
        )

    @pytest.mark.parametrize("cls", [Bus, Scheduler, Api], ids=lambda c: c.__name__)
    def test_canonical_and_exclusions_are_disjoint(self, cls: type) -> None:
        """CANONICAL_PROTECTED and DOCUMENTED_EXCLUSIONS must not overlap."""
        canonical = CANONICAL_PROTECTED[cls]
        exclusions = DOCUMENTED_EXCLUSIONS[cls]
        overlap = canonical & exclusions
        assert not overlap, (
            f"{cls.__name__}: CANONICAL_PROTECTED and DOCUMENTED_EXCLUSIONS overlap: "
            f"{sorted(overlap)}.  A method cannot be both protected and excluded."
        )


# Annotation-origin guard — cross-class, canonical list


class TestAnnotationOriginGuard:
    """Every method in the canonical list must have return annotation __origin__ == collections.abc.Coroutine.

    Fails if a future edit narrows an annotation to Awaitable or a concrete type,
    which would silently kill Pyright's reportUnusedCoroutine.  See design/071.
    """

    @pytest.mark.parametrize(
        ("cls", "method_name"),
        [
            pytest.param(cls, name, id=f"{cls.__name__}.{name}")
            for cls, names in CANONICAL_PROTECTED.items()
            for name in sorted(names)
        ],
    )
    def test_return_annotation_origin_is_coroutine(self, cls: type, method_name: str) -> None:
        """Return annotation __origin__ must be collections.abc.Coroutine."""
        m = getattr(cls, method_name)
        ann = getattr(m, "__annotations__", {})
        ret = ann.get("return")
        assert ret is not None, (
            f"{cls.__name__}.{method_name} has no return annotation.  Annotate it as -> Coroutine[Any, Any, T]."
        )
        if isinstance(ret, str):
            mod = sys.modules.get(cls.__module__)
            assert mod is not None
            try:
                ret = eval(ret, vars(mod))  # noqa: S307 — resolving module annotation
            except Exception as exc:
                raise AssertionError(
                    f"{cls.__name__}.{method_name} return annotation {ret!r} could not be resolved: {exc}"
                ) from exc
        origin = getattr(ret, "__origin__", None)
        assert origin is collections.abc.Coroutine, (
            f"{cls.__name__}.{method_name} return annotation __origin__ is {origin!r}, "
            f"expected collections.abc.Coroutine.  Narrowing to Awaitable or a concrete "
            f"type silently kills Pyright's reportUnusedCoroutine.  See design/071."
        )


# Parametrized warning test over the full canonical list
#
# Each canonical method must emit HassetteForgottenAwaitWarning when its handle
# is dropped un-awaited.  The test builds a minimal instance for each class
# and calls every method (primaries and two-hop delegates alike).
#
# Note: the per-class conversion tests (test_bus_coroutine_conversion.py,
# test_scheduler_coroutine_conversion.py, test_api_coroutine_conversion.py)
# test individual methods in depth.  This parametrized guard tests the
# *complete* canonical set end-to-end to catch future gaps.
# The overlap between per-class warning tests and this parametrized guard is
# deliberate dual-path coverage: per-class tests exercise real fixtures
# (mock_add_listener/conftest bus), while this guard exercises lean stubs
# across the full canonical list — catching drift that per-class tests miss.


# Bus fixtures


def _make_bus() -> Bus:
    """Minimal Bus with mocked bus_service.add_listener."""
    hassette_mock = MagicMock()
    bus = Bus.__new__(Bus)
    bus.hassette = hassette_mock
    bus._unique_name = "test_bus"
    bus._error_handler = None
    bus.logger = MagicMock()
    bus.bus_service = MagicMock()
    bus.bus_service.add_listener = AsyncMock(return_value=1)
    bus.parent = make_mock_parent()
    return bus


async def _bus_handler(event: object) -> None:
    pass


def _bus_call(method_name: str):
    """Return a callable that invokes bus.<method_name> with minimal valid args."""
    _calls = {
        "on": lambda b: b.on(topic="t", handler=_bus_handler, name="n"),
        "on_state_change": lambda b: b.on_state_change("light.x", handler=_bus_handler, name="n"),
        "on_attribute_change": lambda b: b.on_attribute_change("light.x", "brightness", handler=_bus_handler, name="n"),
        "on_call_service": lambda b: b.on_call_service(handler=_bus_handler, name="n"),
        "on_service_registered": lambda b: b.on_service_registered(handler=_bus_handler, name="n"),
        "on_component_loaded": lambda b: b.on_component_loaded(handler=_bus_handler, name="n"),
        "on_hassette_service_status": lambda b: b.on_hassette_service_status(handler=_bus_handler, name="n"),
        "on_app_state_changed": lambda b: b.on_app_state_changed(handler=_bus_handler, name="n"),
        "on_homeassistant_restart": lambda b: b.on_homeassistant_restart(handler=_bus_handler, name="n"),
        "on_homeassistant_start": lambda b: b.on_homeassistant_start(handler=_bus_handler, name="n"),
        "on_homeassistant_stop": lambda b: b.on_homeassistant_stop(handler=_bus_handler, name="n"),
        "on_websocket_connected": lambda b: b.on_websocket_connected(handler=_bus_handler, name="n"),
        "on_websocket_disconnected": lambda b: b.on_websocket_disconnected(handler=_bus_handler, name="n"),
        "on_app_running": lambda b: b.on_app_running(handler=_bus_handler, name="n"),
        "on_app_stopping": lambda b: b.on_app_stopping(handler=_bus_handler, name="n"),
        "on_hassette_service_failed": lambda b: b.on_hassette_service_failed(handler=_bus_handler, name="n"),
        "on_hassette_service_crashed": lambda b: b.on_hassette_service_crashed(handler=_bus_handler, name="n"),
        "on_hassette_service_started": lambda b: b.on_hassette_service_started(handler=_bus_handler, name="n"),
    }
    return _calls[method_name]


# Scheduler fixtures


def _make_scheduler() -> Scheduler:
    """Minimal Scheduler with mocked scheduler_service.add_job."""
    hassette_mock = MagicMock()
    hassette_mock.config.logging.scheduler_service = "INFO"
    sched = Scheduler.__new__(Scheduler)
    sched.hassette = hassette_mock
    sched._jobs_by_name = {}
    sched._jobs_by_group = {}
    sched._unique_name = "test_sched"
    sched._error_handler = None
    mock_service = MagicMock()

    async def _add_job(job: ScheduledJob) -> None:
        job.mark_registered(1)

    mock_service.add_job = AsyncMock(side_effect=_add_job)
    sched.scheduler_service = mock_service
    sched.parent = make_mock_parent()
    return sched


def _sched_call(method_name: str):
    """Return a callable that invokes scheduler.<method_name> with minimal valid args."""
    _every = _Every(hours=1)
    _calls = {
        "schedule": lambda s: s.schedule(noop, _every, name="n"),
        "run_in": lambda s: s.run_in(noop, 30, name="n"),
        "run_once": lambda s: s.run_once(noop, at="23:59", name="n"),
        "run_every": lambda s: s.run_every(noop, minutes=5, name="n"),
        "run_minutely": lambda s: s.run_minutely(noop, minutes=5, name="n"),
        "run_hourly": lambda s: s.run_hourly(noop, hours=1, name="n"),
        "run_daily": lambda s: s.run_daily(noop, at="08:00", name="n"),
        "run_cron": lambda s: s.run_cron(noop, "0 9 * * 1-5", name="n"),
    }
    return _calls[method_name]


# Api fixtures


# Build parametrized cases


def _build_warning_cases() -> list[pytest.param]:
    """Build one pytest.param per canonical method, skipping those with special setup."""
    cases = []
    for method_name in _BUS_METHODS_PARAMETRIZED:
        call = _bus_call(method_name)
        cases.append(pytest.param("bus", call, id=f"Bus.{method_name}"))
    for method_name in _SCHED_METHODS_PARAMETRIZED:
        call = _sched_call(method_name)
        cases.append(pytest.param("sched", call, id=f"Scheduler.{method_name}"))
    for method_name, call in _API_METHOD_CALLS.items():
        cases.append(pytest.param("api", call, id=f"Api.{method_name}"))
    return cases


@pytest.mark.parametrize(("resource", "call_fn"), _build_warning_cases())
def test_canonical_method_warns_on_forgotten_await(resource: str, call_fn) -> None:
    """Every canonical method emits HassetteForgottenAwaitWarning when dropped un-awaited.

    Single assertion per method — no warning-type split.  Primaries and
    two-hop delegates alike must fire the attributed runtime warning.
    """
    if resource == "bus":
        instance = _make_bus()
    elif resource == "sched":
        instance = _make_scheduler()
    else:
        instance = make_api()

    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = call_fn(instance)
        del _
        gc.collect()


# Special-case methods that need different argument construction


def test_bus_add_listener_warns_on_forgotten_await() -> None:
    """Dropping an un-awaited Bus.add_listener() handle emits HassetteForgottenAwaitWarning."""
    bus = _make_bus()
    # Pass a MagicMock as the Listener — add_listener only uses it in _resolve_and_register's
    # async body (the handle wraps that coroutine); the forgotten-await check fires
    # before the coroutine runs, so the mock is sufficient for this warning test.
    listener = MagicMock(spec=Listener)
    listener.identity.name = "completeness_add_listener"
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = bus.add_listener(listener)
        del _
        gc.collect()


def test_scheduler_add_job_warns_on_forgotten_await() -> None:
    """Dropping an un-awaited Scheduler.add_job() handle emits HassetteForgottenAwaitWarning."""
    sched = _make_scheduler()
    job = ScheduledJob(owner_id="test_app.0", next_run=now(), job=noop, name="completeness_add_job")
    with pytest.warns(HassetteForgottenAwaitWarning):
        _ = sched.add_job(job)
        del _
        gc.collect()


# Suppress stray HassetteForgottenAwaitWarning from gc.collect() at teardown


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""
