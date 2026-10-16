"""RuntimeQueryService bus subscriptions, exercised through a real harness Bus.

Calling a handler directly cannot catch a wrong topic, a dropped registration, or a broken
``where=`` filter in on_initialize(); these tests dispatch real events instead.
"""

import contextlib
import typing
from unittest.mock import AsyncMock, MagicMock

import pytest
from hassette_wire import ResourceRole, ResourceStatus

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
    filter), which calling a handler directly cannot detect. The harness config needs
    ``web_api.run=True``: on_initialize() returns early without subscribing otherwise.
    """
    svc = RuntimeQueryService(harness.hassette)
    broadcast_calls: list[dict] = []
    svc.broadcast = AsyncMock(side_effect=lambda msg: broadcast_calls.append(msg))

    # with_bus() doesn't call wire_services(), so hassette.logging_service is unset --
    # on_initialize() only needs its capture_handler for the log-broadcast wiring, which
    # is orthogonal to the bus registrations under test.
    harness.hassette._logging_service = MagicMock()

    await svc.on_initialize()
    try:
        yield broadcast_calls
    finally:
        await svc.on_shutdown()


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
