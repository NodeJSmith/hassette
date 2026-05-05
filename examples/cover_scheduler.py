"""Cover Scheduler.

Automates cover/blind positions on a daily schedule. Opens covers on
weekday mornings, closes them at night, and logs positions hourly.
Uses the cache to persist last-known positions across restarts.

Demo entities:
    - cover.kitchen_window
    - cover.hall_window
    - cover.living_room_window
    - sun.sun
"""

from hassette import App, AppConfig, RawStateChangeEvent

CACHE_KEY_POSITIONS = "last_cover_positions"


class CoverSchedulerConfig(AppConfig):
    morning_open_hour: int = 7
    morning_open_minute: int = 30
    night_close_hour: int = 22
    night_close_minute: int = 0


class CoverScheduler(App[CoverSchedulerConfig]):
    """Schedule cover open/close and track positions."""

    async def on_initialize(self) -> None:
        cfg = self.app_config
        self.logger.info("Cover scheduler started")

        # Restore cached positions
        cached = self.cache.get(CACHE_KEY_POSITIONS)
        if cached:
            self.logger.info("Restored cached cover positions: %s", cached)

        # Open covers on weekday mornings (Mon-Fri)
        # if_exists="skip" makes this safe to call on app reload — if the job
        # already exists from a prior initialize(), it's silently skipped.
        # group="covers" lets users filter/view cover-related jobs together.
        self.scheduler.run_cron(
            self.open_all_covers,
            f"{cfg.morning_open_minute} {cfg.morning_open_hour} * * 1-5",
            name="morning_open",
            group="covers",
            if_exists="skip",
        )

        # Close covers every night
        self.scheduler.run_daily(
            self.close_all_covers,
            at=f"{cfg.night_close_hour:02d}:{cfg.night_close_minute:02d}",
            name="night_close",
            group="covers",
            if_exists="skip",
        )

        # Log cover positions every hour — jitter=30 spreads the check slightly
        # to avoid simultaneous API calls if multiple instances are running
        self.scheduler.run_hourly(
            self.log_cover_positions,
            name="position_log",
            group="monitoring",
            jitter=30,
            if_exists="skip",
        )

        # One-time sun state report 10 seconds after startup
        self.scheduler.run_in(self.report_sun_state, 10, name="startup_sun_report")

        # Listen for any cover state changes
        self.bus.on_state_change("cover.*", handler=self.on_cover_change)

        # One-time listener: log when sun state first changes
        self.bus.on_state_change("sun.sun", handler=self.on_sun_first_change, once=True)

    async def on_shutdown(self) -> None:
        """Persist cover positions to cache before stopping."""
        positions = await self._get_cover_positions()
        self.cache[CACHE_KEY_POSITIONS] = positions
        self.logger.info("Saved cover positions to cache: %s", positions)

    async def open_all_covers(self) -> None:
        """Open all covers."""
        self.logger.info("Opening all covers (weekday morning schedule)")
        for entity_id, cover in self.states.cover:
            self.logger.info("Opening %s (current state: %s)", entity_id, cover.value)
            try:
                await self.api.call_service("cover", "open_cover", target={"entity_id": entity_id})
            except Exception:
                self.logger.exception("Failed to open %s", entity_id)

    async def close_all_covers(self) -> None:
        """Close all covers."""
        self.logger.info("Closing all covers (nightly schedule)")
        for entity_id, cover in self.states.cover:
            self.logger.info("Closing %s (current state: %s)", entity_id, cover.value)
            try:
                await self.api.call_service("cover", "close_cover", target={"entity_id": entity_id})
            except Exception:
                self.logger.exception("Failed to close %s", entity_id)

    async def log_cover_positions(self) -> None:
        """Hourly position log."""
        positions = await self._get_cover_positions()
        self.logger.info("Hourly cover positions: %s", positions)
        self.cache[CACHE_KEY_POSITIONS] = positions

    async def report_sun_state(self) -> None:
        """One-time startup report of sun state."""
        sun = self.states.sun.get("sun.sun")
        if sun:
            self.logger.info(
                "Sun state: %s (elevation=%.1f, rising=%s, next_setting=%s)",
                sun.value,
                sun.attributes.elevation or 0.0,
                sun.attributes.rising,
                sun.attributes.next_setting,
            )
        else:
            self.logger.warning("Sun entity not found")

    async def on_cover_change(self, event: RawStateChangeEvent) -> None:
        """Any cover changed state."""
        data = event.payload.data
        self.logger.info(
            "Cover %s changed: %s -> %s",
            data.entity_id,
            data.old_state_value,
            data.new_state_value,
        )

    async def on_sun_first_change(self, event: RawStateChangeEvent) -> None:
        """Fires once when the sun entity first changes."""
        data = event.payload.data
        self.logger.info("Sun transitioned: %s -> %s", data.old_state_value, data.new_state_value)

    async def _get_cover_positions(self) -> dict[str, str | None]:
        """Collect current cover positions."""
        positions: dict[str, str | None] = {}
        for entity_id, cover in self.states.cover:
            positions[entity_id] = cover.value
        return positions
