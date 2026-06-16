from hassette import App, AppConfig


# ---------------------------------------------------------------------------
# single (default for app jobs)
# ---------------------------------------------------------------------------

# --8<-- [start:single_implicit]
class PollApp(App[AppConfig]):
    async def on_initialize(self):
        # App jobs default to single — no mode= needed.
        await self.scheduler.run_every(
            self.sync_data,
            seconds=30,
            name="sync_data",
        )

    async def sync_data(self):
        # Only one copy of this job runs at a time.
        # A re-fire that arrives while this is running is dropped.
        self.logger.info("Syncing data")
        await self.api.call_service(
            "homeassistant", "update_entity",
            entity_id="sensor.outdoor_temperature",
        )
# --8<-- [end:single_implicit]


# ---------------------------------------------------------------------------
# restart — latest trigger wins
# ---------------------------------------------------------------------------

# --8<-- [start:restart]
class RefreshApp(App[AppConfig]):
    async def on_initialize(self):
        await self.scheduler.run_every(
            self.refresh_report,
            minutes=5,
            name="refresh_report",
            mode="restart",
        )

    async def refresh_report(self):
        # If the next tick arrives before this finishes,
        # the in-flight run is cancelled and a fresh one starts.
        self.logger.info("Refreshing report")
        await self.api.call_service(
            "script", "turn_on",
            entity_id="script.generate_report",
        )
# --8<-- [end:restart]


# ---------------------------------------------------------------------------
# queued — serialize every tick in arrival order
# ---------------------------------------------------------------------------

# --8<-- [start:queued]
class AuditApp(App[AppConfig]):
    async def on_initialize(self):
        await self.scheduler.run_every(
            self.run_audit,
            minutes=2,
            name="run_audit",
            mode="queued",
        )

    async def run_audit(self):
        # Every tick runs in arrival order, one at a time.
        # If the queue reaches 10 pending ticks, the newest is dropped.
        self.logger.info("Starting audit run")
        await self.api.call_service(
            "script", "turn_on",
            entity_id="script.run_audit",
        )
# --8<-- [end:queued]


# ---------------------------------------------------------------------------
# parallel — concurrent (opt-in for app jobs)
# ---------------------------------------------------------------------------

# --8<-- [start:parallel]
class MetricApp(App[AppConfig]):
    async def on_initialize(self):
        await self.scheduler.run_every(
            self.record_reading,
            seconds=10,
            name="record_reading",
            mode="parallel",
        )

    async def record_reading(self):
        # Each tick spawns an independent recording task.
        # Multiple readings can run concurrently.
        self.logger.info("Recording sensor reading")
        await self.api.call_service(
            "homeassistant", "update_entity",
            entity_id="sensor.outdoor_temperature",
        )
# --8<-- [end:parallel]


# ---------------------------------------------------------------------------
# Intro: the mode= parameter
# ---------------------------------------------------------------------------

class IntroApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:mode_parameter_basic]
        await self.scheduler.run_every(
            self.sync_data,
            minutes=5,
            name="sync_data",
            mode="single",  # or "restart", "queued", "parallel"
        )
        # --8<-- [end:mode_parameter_basic]

    async def sync_data(self):
        pass


# ---------------------------------------------------------------------------
# One-shot: mode= accepted, no overlap effect
# ---------------------------------------------------------------------------

# --8<-- [start:one_shot_mode]
class CleanupApp(App[AppConfig]):
    async def on_initialize(self):
        # mode= is accepted on run_in for API uniformity.
        # It has no overlap effect — a one-shot never re-fires.
        await self.scheduler.run_in(
            self.cleanup,
            delay=60,
            name="delayed_cleanup",
            mode="single",
        )

    async def cleanup(self):
        self.logger.info("Running cleanup")
# --8<-- [end:one_shot_mode]
