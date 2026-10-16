"""RuntimeQueryService bus subscriptions, exercised through a real harness Bus.

Calling a handler directly cannot catch a wrong topic, a dropped registration, or a broken
``where=`` filter in on_initialize(); these tests dispatch real events instead.
"""

import asyncio
import contextlib
import typing

import pytest
from hassette_wire import ResourceRole, ResourceStatus

from hassette.core.logging_service import LoggingService
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.events.hassette import HassetteServiceEvent, HassetteSimpleEvent
from hassette.testing import wait_for
from hassette.types.enums import Topic

if typing.TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from hassette import HassetteConfig
    from hassette.testing import HassetteHarness


@contextlib.asynccontextmanager
async def initialized_runtime(harness: "HassetteHarness") -> "AsyncIterator[list[dict]]":
    """Run a RuntimeQueryService's real on_initialize() against a harness Bus, recording broadcasts.

    Lets a test exercise the bus subscriptions on_initialize() registers (topic and ``where=``
    filter), which calling a handler directly cannot detect. Broadcasts are captured through a
    real WS client queue, so the real ``broadcast()`` path runs. The harness config needs
    ``web_api.run=True``: on_initialize() returns early without subscribing otherwise.
    """
    # with_bus() doesn't call wire_services(), so hassette.logging_service is unset.
    # on_initialize() only reads its capture_handler, so a constructed-but-uninitialized
    # LoggingService is enough; it installs no logger handlers until its own on_initialize().
    previous_logging_service = harness.hassette._logging_service
    harness.hassette._logging_service = LoggingService(harness.hassette, stream_handler=None)

    svc = RuntimeQueryService(harness.hassette)
    queue = await svc.register_ws_client()
    broadcast_calls: list[dict] = []

    async def drain() -> None:
        while (msg := await queue.get()) is not None:
            broadcast_calls.append(msg)

    await svc.on_initialize()
    drain_task = asyncio.create_task(drain())
    try:
        yield broadcast_calls
    finally:
        # on_shutdown() closes every WS client queue with a None sentinel, which ends drain().
        await svc.on_shutdown()
        await asyncio.wait_for(drain_task, timeout=5)
        harness.hassette._logging_service = previous_logging_service


class TestSubscriptionWiring:
    async def test_on_initialize_wires_app_load_completed_to_broadcast(
        self,
        hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
        test_config_class: "type[HassetteConfig]",
        unused_tcp_port_factory: "Callable[[], int]",
    ) -> None:
        """The bus subscription registered in on_initialize() actually routes
        Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED to on_apps_changed.

        Unlike the direct-call test in test_runtime_query_service.py, this exercises the real
        registration on a real Bus -- it would catch a wrong topic constant or a dropped
        registration in on_initialize(), neither of which invoking on_apps_changed() directly
        can detect. Builds its own config (rather than the shared session-scoped `test_config`
        fixture) with `web_api.run=True`, since `on_initialize()` returns early without
        registering anything when the web API is disabled -- `TestConfig`'s default -- and
        mutating the shared fixture's config in place would leak into every other test in the
        session.
        """
        config = test_config_class(web_api={"port": unused_tcp_port_factory(), "run": True})

        async with (
            hassette_harness(config).with_bus() as harness,
            initialized_runtime(harness) as broadcast_calls,
        ):
            await harness.hassette.send_event(
                HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)
            )
            await wait_for(
                lambda: any(call["type"] == "apps_changed" for call in broadcast_calls),
                desc="apps_changed broadcast",
            )

        manifest_calls = [call for call in broadcast_calls if call["type"] == "apps_changed"]
        assert len(manifest_calls) == 1
        assert manifest_calls[0]["data"] == {}

    @pytest.mark.parametrize(
        ("role", "expect_broadcast"),
        [
            (ResourceRole.SERVICE, True),
            (ResourceRole.RESOURCE, True),
            (ResourceRole.APP, False),
        ],
    )
    async def test_service_status_subscription_excludes_app_role(
        self,
        hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
        test_config_class: "type[HassetteConfig]",
        unused_tcp_port_factory: "Callable[[], int]",
        role: ResourceRole,
        expect_broadcast: bool,
    ) -> None:
        """Regression test for #1666: app lifecycle transitions stay out of the Services panel.

        Apps are Resources and emit service_status through the shared lifecycle machinery; the
        Diagnostics Services panel shows framework resources only, and two instances of one app
        class would collide on their shared class-name ``resource_name``. Dispatches through the
        real Bus so the subscription's ``where=`` filter is exercised, not just the handler.
        """
        config = test_config_class(web_api={"port": unused_tcp_port_factory(), "run": True})

        async with (
            hassette_harness(config).with_bus() as harness,
            initialized_runtime(harness) as broadcast_calls,
        ):
            await harness.hassette.send_event(
                HassetteServiceEvent.from_service_status(
                    resource_name="SomeResource", role=role, status=ResourceStatus.RUNNING
                )
            )
            await harness.hassette.bus_service.await_dispatch_idle()

        # The harness's own resources broadcast service_status too; match only the injected event.
        status_calls = [
            call
            for call in broadcast_calls
            if call["type"] == "service_status" and call["data"]["resource_name"] == "SomeResource"
        ]
        assert bool(status_calls) is expect_broadcast
