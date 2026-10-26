"""Unit tests for service failure routing on ``Hassette`` (spec 134 D2, D8, D14).

A failure after a service's handoff to ``serve()`` is reported to ``Hassette.report_service_failure()``.
A required service's report records the fatal reason and requests shutdown; an optional one's leaves
the service dead in place. Project rule: no log-capture tests, so these assert on state only.
"""

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
from hassette_wire import ResourceStatus

from hassette import HassetteConfig
from hassette.core.core import Hassette
from hassette.events import HassetteServiceEvent
from hassette.exceptions import FatalError, ServeEndedError
from hassette.resources.service import Service
from hassette.testing import wait_for


class _RequiredService(Service):
    required: ClassVar[bool] = True

    async def serve(self) -> None:
        await self.shutdown_event.wait()


class _OptionalService(Service):
    required: ClassVar[bool] = False

    async def serve(self) -> None:
        await self.shutdown_event.wait()


@pytest.fixture
async def hassette(test_config: HassetteConfig) -> AsyncIterator[Hassette]:
    """An unwired Hassette whose bucket can spawn on this loop, as it can once run_forever() starts."""
    instance = Hassette(test_config)
    instance._loop = asyncio.get_running_loop()
    instance._loop_thread_id = threading.get_ident()
    try:
        yield instance
    finally:
        instance.task_bucket.cancel_all_sync()


def capture_crashed_events(hassette: Hassette) -> list[HassetteServiceEvent]:
    """Replace send_event with a recorder of the CRASHED events it is asked to send."""
    sent: list[HassetteServiceEvent] = []

    async def record(event: Any) -> None:
        if isinstance(event, HassetteServiceEvent) and event.payload.data.status is ResourceStatus.CRASHED:
            sent.append(event)

    hassette.send_event = record  # pyright: ignore[reportAttributeAccessIssue]
    return sent


class TestRequiredServiceFailure:
    async def test_records_reason_naming_service_and_exception_then_requests_shutdown(self, hassette: Hassette) -> None:
        service = _RequiredService(hassette, parent=hassette)

        hassette.report_service_failure(service, RuntimeError("boom"))

        assert hassette.fatal_shutdown_reason is not None
        assert "_RequiredService" in hassette.fatal_shutdown_reason
        assert "RuntimeError" in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()

    async def test_unrequested_return_reason_says_serve_ended(self, hassette: Hassette) -> None:
        service = _RequiredService(hassette, parent=hassette)

        hassette.report_service_failure(service, ServeEndedError("returned"))

        assert hassette.fatal_shutdown_reason is not None
        assert "serve() ended without shutdown" in hassette.fatal_shutdown_reason

    async def test_emits_crashed_telemetry(self, hassette: Hassette) -> None:
        sent = capture_crashed_events(hassette)
        service = _RequiredService(hassette, parent=hassette)

        hassette.report_service_failure(service, RuntimeError("boom"))

        await wait_for(lambda: bool(sent), desc="CRASHED telemetry event")
        assert sent[0].payload.data.resource_name == "_RequiredService"

    async def test_first_reason_wins(self, hassette: Hassette) -> None:
        hassette.record_fatal_reason("earlier reason")
        service = _RequiredService(hassette, parent=hassette)

        hassette.report_service_failure(service, RuntimeError("boom"))

        assert hassette.fatal_shutdown_reason == "earlier reason"

    async def test_raised_fatal_error_is_routed_the_same_way(self, hassette: Hassette) -> None:
        service = _RequiredService(hassette, parent=hassette)

        hassette.report_service_failure(service, FatalError("fatal"))

        assert hassette.fatal_shutdown_reason is not None
        assert "FatalError" in hassette.fatal_shutdown_reason
        assert hassette.shutdown_event.is_set()


class TestReportAfterShutdownRequested:
    async def test_is_not_escalated(self, hassette: Hassette) -> None:
        """A clean stop still exits 0: a failure during shutdown latches no fatal reason."""
        sent = capture_crashed_events(hassette)
        hassette.shutdown_event.set()
        service = _RequiredService(hassette, parent=hassette)

        hassette.report_service_failure(service, RuntimeError("late"))
        await asyncio.sleep(0)

        assert hassette.fatal_shutdown_reason is None
        assert sent == []


class TestOptionalServiceFailure:
    async def test_stays_dead_in_place_without_ending_the_process(self, hassette: Hassette) -> None:
        sent = capture_crashed_events(hassette)
        service = _OptionalService(hassette, parent=hassette)

        hassette.report_service_failure(service, RuntimeError("serve broke"))
        await asyncio.sleep(0)

        assert hassette.fatal_shutdown_reason is None
        assert not hassette.shutdown_event.is_set()
        assert sent == []


class TestReportFromServeWrapper:
    """The serve wrapper reports before its awaited telemetry sends (spec 134 D8)."""

    async def test_required_failure_requests_shutdown_while_the_event_channel_is_stalled(
        self, hassette: Hassette
    ) -> None:
        """A full, undrained channel must not delay the report that ends the process."""

        async def stall_after_running(event: Any) -> None:
            if isinstance(event, HassetteServiceEvent) and event.payload.data.status is ResourceStatus.RUNNING:
                return
            await asyncio.Event().wait()

        hassette.send_event = stall_after_running  # pyright: ignore[reportAttributeAccessIssue]

        class _FailingRequired(Service):
            required: ClassVar[bool] = True

            async def serve(self) -> None:
                raise RuntimeError("serve failed")

        service = _FailingRequired(hassette, parent=hassette)
        serve_task = asyncio.create_task(service._serve_wrapper())
        try:
            await wait_for(hassette.shutdown_event.is_set, desc="shutdown requested by the report")
            assert hassette.fatal_shutdown_reason is not None
            assert "_FailingRequired" in hassette.fatal_shutdown_reason
        finally:
            serve_task.cancel()
            await asyncio.gather(serve_task, return_exceptions=True)
