"""Pyright probe fixture: forgotten-await detection (FR#5, AC#3).

This file is INTENTIONALLY WRONG — every call is a bare un-awaited call
that should trigger reportUnusedCoroutine in Pyright.

It is excluded from the main pyrightconfig.json (via **/tests ignore) and
from the docs pyrightconfig.json.  It is checked by a dedicated pyrightconfig
at tests/pyright_probes/pyrightconfig.json that treats
reportUnusedCoroutine as an error.

The test tests/unit/test_pyright_probe.py runs pyright on this directory
and asserts that every expected diagnostic is reported.

Empirically verified 2026-06-11: def -> Coroutine[Any, Any, T] fires
reportUnusedCoroutine for simple, overloaded, and None-returning methods.
See design/071 FR#5, AC#3.
"""

# ruff: noqa
# pyright: basic

from hassette.api.api import Api
from hassette.bus.bus import Bus
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from unittest.mock import MagicMock, AsyncMock


def _make_bus() -> Bus:
    hassette_mock = MagicMock()
    bus = Bus.__new__(Bus)
    bus.hassette = hassette_mock
    bus._unique_name = "probe_bus"
    bus._error_handler = None
    bus.logger = MagicMock()
    bus.bus_service = MagicMock()
    bus.bus_service.add_listener = AsyncMock(return_value=1)
    mock_parent = MagicMock()
    mock_parent.app_key = "probe_app"
    mock_parent.index = 0
    mock_parent.unique_name = "probe_app.0"
    mock_parent.source_tier = "app"
    mock_parent.class_name = "ProbeApp"
    mock_parent.app_config = MagicMock()
    mock_parent.app_config.forgotten_await_behavior = None
    bus.parent = mock_parent
    return bus


def _make_scheduler() -> Scheduler:
    hassette_mock = MagicMock()
    hassette_mock.config.logging.scheduler_service = "INFO"
    sched = Scheduler.__new__(Scheduler)
    sched.hassette = hassette_mock
    sched._jobs_by_name = {}
    sched._jobs_by_group = {}
    sched._unique_name = "probe_scheduler"
    sched._error_handler = None
    mock_service = MagicMock()

    async def _add_job(job: ScheduledJob) -> None:
        job.mark_registered(1)

    mock_service.add_job = AsyncMock(side_effect=_add_job)
    sched.scheduler_service = mock_service
    mock_parent = MagicMock()
    mock_parent.app_key = "probe_app"
    mock_parent.index = 0
    mock_parent.source_tier = "app"
    mock_parent.class_name = "ProbeApp"
    mock_parent.app_config = MagicMock()
    mock_parent.app_config.forgotten_await_behavior = None
    sched.parent = mock_parent
    return sched


def _make_api() -> Api:
    hassette_mock = MagicMock()
    hassette_mock.config.logging.api = "INFO"
    hassette_mock.config.forgotten_await_behavior = None
    api = Api.__new__(Api)
    api.hassette = hassette_mock
    api._unique_name = "probe_api"  # pyright: ignore[reportAttributeAccessIssue]
    api.logger = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
    mock_parent = MagicMock()
    mock_parent.app_key = "probe_app"
    mock_parent.index = 0
    mock_parent.unique_name = "probe_app.0"
    mock_parent.source_tier = "app"
    mock_parent.class_name = "ProbeApp"
    mock_parent.app_config = MagicMock()
    mock_parent.app_config.forgotten_await_behavior = None
    api.parent = mock_parent  # pyright: ignore[reportAttributeAccessIssue]
    api.ws_send_and_wait = AsyncMock(return_value={})  # pyright: ignore[reportAttributeAccessIssue]
    api.ws_send_json = AsyncMock(return_value=None)  # pyright: ignore[reportAttributeAccessIssue]
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={"state": "on", "entity_id": "light.test"})
    api.post_rest_request = AsyncMock(return_value=mock_resp)  # pyright: ignore[reportAttributeAccessIssue]
    api.entity_exists = AsyncMock(return_value=False)  # pyright: ignore[reportAttributeAccessIssue]
    return api


async def _handler(event: object) -> None:
    pass


async def probe_cases() -> None:
    bus = _make_bus()
    sched = _make_scheduler()
    api = _make_api()

    # --- Simple bus method (bare call, no await) ---
    bus.on_state_change(  # PROBE: bus_on_state_change
        "light.kitchen", handler=_handler, name="probe_bus"
    )

    # --- Scheduler method (bare call, no await) ---
    sched.run_in(_handler, 30, name="probe_scheduler")  # PROBE: scheduler_run_in

    # --- Overloaded call_service: ServiceResponse overload (target=None, return_response=True) ---
    api.call_service("light", "turn_on", None, True)  # PROBE: api_call_service_response_overload

    # --- Overloaded call_service: None overload (no return_response) ---
    api.call_service("light", "turn_on")  # PROBE: api_call_service_none_overload

    # --- None-returning method: turn_on ---
    api.turn_on("light.kitchen")  # PROBE: api_turn_on
