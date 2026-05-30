from hassette import App, AppConfig
from hassette.bus import Subscription
from hassette.events import RawStateChangeEvent


class MyApp(App[AppConfig]):
    sub: Subscription | None = None

    async def on_initialize(self) -> None:
        # --8<-- [start:await_persistence]
        # Registration is synchronous — db_id is set before this line returns.
        sub = await self.bus.on_state_change(
            "sensor.temperature", handler=self.on_temp, name="temp_monitor"
        )

        # db_id is always set immediately after the awaited call returns.
        self.logger.info("Listener registered with db_id=%d", sub.listener.db_id)
        # --8<-- [end:await_persistence]

    # --8<-- [start:routing_independence]
    async def register_with_check(self) -> None:
        # Await the registration — routing and DB persistence both complete before
        # this line returns. The handler receives events from this point on.
        sub = await self.bus.on_state_change(
            "sensor.temperature", handler=self.on_temp, name="temp_check"
        )

        # db_id is guaranteed set — no guard needed.
        self.logger.info("Listener db_id=%d", sub.listener.db_id)
    # --8<-- [end:routing_independence]

    # --8<-- [start:resubscribe]
    async def resubscribe(self) -> None:
        if self.sub is not None:
            # Cancel the old subscription — routing removal is immediate.
            self.sub.cancel()

        # Register the replacement — routing and DB persistence both complete
        # before this line returns. The old handler is guaranteed gone; no overlap.
        self.sub = await self.bus.on_state_change(
            "light.kitchen", handler=self.on_light, name="kitchen_light"
        )
    # --8<-- [end:resubscribe]

    async def on_temp(self, event: RawStateChangeEvent) -> None: ...
    async def on_light(self, event: RawStateChangeEvent) -> None: ...
