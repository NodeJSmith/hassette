from unittest.mock import AsyncMock, patch

from hassette import App, AppConfig
from hassette.exceptions import OutcomeUnknownError, ResponseTimeoutError
from hassette.testing import AppTestHarness


class DoorbellApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "binary_sensor.doorbell", handler=self.on_ring, name="doorbell"
        )

    async def on_ring(self) -> None:
        try:
            await self.api.call_service(
                "counter",
                "increment",
                target={"entity_id": "counter.rings"},
                wait_for_ack=True,
            )
        except OutcomeUnknownError:
            # The increment may or may not have applied, so don't retry it.
            await self.api.fire_event("doorbell_count_unconfirmed")


async def test_unconfirmed_increment_is_not_retried():
    async with AppTestHarness(DoorbellApp, config={}) as harness:
        timeout = ResponseTimeoutError("'call_service' (id 7): no response")
        with patch.object(
            harness.api_recorder,
            "call_service",
            AsyncMock(side_effect=timeout),
        ) as call_service:
            await harness.simulate_state_change(
                "binary_sensor.doorbell", old_value="off", new_value="on"
            )

        call_service.assert_awaited_once()
        harness.api_recorder.assert_called(
            "fire_event", event_type="doorbell_count_unconfirmed"
        )
