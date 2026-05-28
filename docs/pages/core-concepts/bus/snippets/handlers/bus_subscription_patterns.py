from hassette import App, AppConfig
from hassette.bus.event import RawStateChangeEvent
from hassette.bus.subscription import Subscription


class MyApp(App[AppConfig]):
    sub: Subscription | None = None

    async def on_initialize(self) -> None:
        # --8<-- [start:await_persistence]
        sub = self.bus.on_state_change("sensor.temperature", handler=self.on_temp)

        # Wait until the listener is persisted to the DB before continuing
        if sub.registration_task is not None:
            await sub.registration_task

        # Check whether persistence actually succeeded
        if sub.listener.db_id is None:
            self.logger.warning("Listener was not persisted to the database")
        # --8<-- [end:await_persistence]

    # --8<-- [start:routing_independence]
    async def register_with_check(self) -> None:
        sub = self.bus.on_state_change("sensor.temperature", handler=self.on_temp)

        # Handler is already routable here — no await needed for event delivery.
        # Await only if you need to know whether persistence succeeded.
        if sub.registration_task is not None:
            await sub.registration_task  # resolves whether DB write succeeded or failed

        if sub.listener.db_id is None:
            self.logger.warning("Listener was not persisted — telemetry unavailable")
        # Either way, the handler is routing and will receive events.
    # --8<-- [end:routing_independence]

    # --8<-- [start:resubscribe]
    async def resubscribe(self) -> None:
        if self.sub is not None:
            # Cancel the old subscription — routing removal is immediate.
            self.sub.cancel()

        # Register the replacement — it is routable before this line returns.
        # The old handler is guaranteed gone; no overlap, no gap.
        self.sub = self.bus.on_state_change("light.kitchen", handler=self.on_light)
    # --8<-- [end:resubscribe]

    async def on_temp(self, event: RawStateChangeEvent) -> None: ...
    async def on_light(self, event: RawStateChangeEvent) -> None: ...
