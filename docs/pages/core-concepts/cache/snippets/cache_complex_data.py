import dataclasses
from dataclasses import dataclass

from hassette import App, AppConfig
from whenever import ZonedDateTime


@dataclass
class EnergyStats:
    total_kwh: float
    peak_usage: float
    last_updated: ZonedDateTime


class EnergyTrackerApp(App[AppConfig]):
    async def on_initialize(self):
        # Load previous stats or create new ones
        self.stats: EnergyStats = self.cache.get(
            "energy_stats",
            EnergyStats(0.0, 0.0, self.now()),
        )

        self.scheduler.run_hourly(self.update_stats)

    async def update_stats(self):
        current_usage = await self.get_current_usage()

        # Create a new stats object — do not mutate the existing one
        self.stats = dataclasses.replace(
            self.stats,
            total_kwh=self.stats.total_kwh + current_usage,
            peak_usage=max(self.stats.peak_usage, current_usage),
            last_updated=self.now(),
        )

        # Persist to cache
        self.cache["energy_stats"] = self.stats
        self.logger.info("Updated stats: %s", self.stats)

    async def get_current_usage(self) -> float:
        state = await self.api.get_state("sensor.power_usage")
        return float(state.state)
