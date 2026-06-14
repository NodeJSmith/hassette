from hassette import App, AppConfig, D, states


# ---------------------------------------------------------------------------
# single (default for app handlers)
# ---------------------------------------------------------------------------

# --8<-- [start:single_implicit]
class LockApp(App[AppConfig]):
    async def on_initialize(self):
        # App handlers default to single — no mode= needed.
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            changed_to="on",
            handler=self.on_door_opened,
            name="front_door_opened",
        )

    async def on_door_opened(
        self,
        new: D.StateNew[states.BinarySensorState],
    ):
        # Only one copy of this handler runs at a time.
        # A second trigger while this is still running is dropped.
        await self.api.call_service("lock", "lock", entity_id="lock.front")
# --8<-- [end:single_implicit]


# ---------------------------------------------------------------------------
# restart — latest trigger wins
# ---------------------------------------------------------------------------

# --8<-- [start:restart]
class SearchApp(App[AppConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "input_text.search_query",
            handler=self.on_query_change,
            name="search_query",
            mode="restart",
        )

    async def on_query_change(
        self,
        new: D.StateNew[states.InputTextState],
    ):
        # If the user types again before this finishes, the in-flight
        # search is cancelled and a new one starts with the latest query.
        await self.api.call_service(
            "search",
            "query",
            entity_id="sensor.search",
            query=str(new.value),
        )
        self.logger.info("Query sent for: %s", new.value)
# --8<-- [end:restart]


# ---------------------------------------------------------------------------
# queued — process every trigger in arrival order
# ---------------------------------------------------------------------------

# --8<-- [start:queued]
class AuditApp(App[AppConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "input_boolean.trigger_audit",
            changed_to="on",
            handler=self.run_audit,
            name="audit_trigger",
            mode="queued",
        )

    async def run_audit(self):
        # Every trigger runs in the order it arrived.
        # If the queue reaches 10 pending triggers, the newest is dropped.
        self.logger.info("Starting audit run")
        await self.api.call_service(
            "script", "turn_on", entity_id="script.run_audit"
        )
# --8<-- [end:queued]


# ---------------------------------------------------------------------------
# parallel — concurrent (opt-in for app handlers)
# ---------------------------------------------------------------------------

# --8<-- [start:parallel]
class MetricApp(App[AppConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "sensor.*",
            handler=self.record_reading,
            name="all_sensors",
            mode="parallel",
        )

    async def record_reading(
        self,
        entity_id: D.EntityId,
    ):
        # Each sensor event spawns an independent recording task.
        # Multiple readings are logged concurrently.
        self.logger.info("Sensor reading from %s", entity_id)
# --8<-- [end:parallel]


# ---------------------------------------------------------------------------
# Composition: debounce + single
# ---------------------------------------------------------------------------

# --8<-- [start:debounce_single]
class TempApp(App[AppConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_temp_change,
            name="outdoor_temp",
            debounce=5.0,
            mode="single",
        )

    async def on_temp_change(
        self,
        new: D.StateNew[states.SensorState],
    ):
        # debounce governs whether an invocation starts (waits 5 s of quiet).
        # single governs overlap: if the handler is still running when the
        # next debounced call fires, that call is dropped.
        self.logger.info("Temperature settled at %s", new.value)
# --8<-- [end:debounce_single]


# ---------------------------------------------------------------------------
# Composition: once + mode
# ---------------------------------------------------------------------------

# --8<-- [start:once_mode]
class StartupApp(App[AppConfig]):
    async def on_initialize(self):
        # once=True fires at most once. The once-guard short-circuits before
        # the mode guard runs — mode has no effect when once=True.
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            changed_to="on",
            handler=self.on_first_open,
            name="first_door_open",
            once=True,
        )

    async def on_first_open(self):
        self.logger.info("Front door opened for the first time")
# --8<-- [end:once_mode]


# ---------------------------------------------------------------------------
# Composition: duration + single
# ---------------------------------------------------------------------------

# --8<-- [start:duration_single]
class OccupancyApp(App[AppConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "binary_sensor.motion_sensor",
            changed_to="on",
            duration=30.0,
            handler=self.on_sustained_motion,
            name="sustained_motion",
            mode="single",
        )

    async def on_sustained_motion(self):
        # The guard applies when the 30-second hold expires and the
        # handler actually dispatches — not when the trigger first arrives.
        await self.api.call_service(
            "light", "turn_on", entity_id="light.living_room"
        )
# --8<-- [end:duration_single]
