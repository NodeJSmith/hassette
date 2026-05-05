"""Presence Tracker.

Monitors a device tracker and dynamically subscribes to zone changes
when a person leaves home. Creates a custom sensor entity with
presence status.

Designed for multi-instance use — each instance tracks a different person.

Demo entities:
    - device_tracker.demo_paulus
    - device_tracker.demo_home_boy
    - zone.home
"""

from typing import TYPE_CHECKING

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig, C, D, RawStateChangeEvent, states

if TYPE_CHECKING:
    from hassette.bus import Subscription


class PresenceTrackerConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="presence_")

    tracker_entity: str = "device_tracker.demo_paulus"
    person_name: str = "Unknown"
    status_interval: float = 120.0  # seconds


class PresenceTracker(App[PresenceTrackerConfig]):
    """Track a person's presence and dynamically manage zone subscriptions."""

    async def on_initialize(self) -> None:
        self._zone_subscription: Subscription | None = None
        cfg = self.app_config
        self.logger.info("Tracking presence for %s via %s", cfg.person_name, cfg.tracker_entity)

        # Watch for tracker state changes
        self.bus.on_state_change(
            cfg.tracker_entity,
            handler=self.on_tracker_change,
        )

        # Periodic status log — group for easy filtering in the dashboard
        self.scheduler.run_every(
            self.log_status,
            seconds=cfg.status_interval,
            name=f"{cfg.person_name}_status",
            group="tracking",
        )

        # Create a custom presence sensor
        tracker_state = self.states.device_tracker.get(cfg.tracker_entity)
        initial_status = "home" if tracker_state and tracker_state.value == "home" else "away"
        await self.api.set_state(
            f"sensor.{cfg.person_name.lower()}_presence",
            initial_status,
            attributes={"friendly_name": f"{cfg.person_name} Presence", "source": cfg.tracker_entity},
        )
        self.logger.info("Created sensor.%s_presence = %s", cfg.person_name.lower(), initial_status)

        # If person is already away, subscribe to zone changes
        if initial_status == "away":
            self._subscribe_to_zone()

    async def on_tracker_change(
        self,
        new_state: D.StateNew[states.DeviceTrackerState],
        old_state: D.MaybeStateOld[states.DeviceTrackerState],
    ) -> None:
        """Device tracker state changed."""
        cfg = self.app_config
        old_val = old_state.value if old_state else None
        self.logger.info("%s tracker changed: %s -> %s", cfg.person_name, old_val, new_state.value)

        # Update custom sensor
        status = "home" if new_state.value == "home" else "away"
        await self.api.set_state(
            f"sensor.{cfg.person_name.lower()}_presence",
            status,
            attributes={"friendly_name": f"{cfg.person_name} Presence", "source": cfg.tracker_entity},
        )

        if new_state.value != "home" and self._zone_subscription is None:
            # Person left home — subscribe to zone changes
            self.logger.info("%s left home, subscribing to zone.home changes", cfg.person_name)
            self._subscribe_to_zone()
        elif new_state.value == "home" and self._zone_subscription is not None:
            # Person returned home — unsubscribe from zone changes
            self.logger.info("%s returned home, cancelling zone subscription", cfg.person_name)
            self._zone_subscription.cancel()
            self._zone_subscription = None

    def _subscribe_to_zone(self) -> None:
        """Dynamically subscribe to zone.home occupancy changes."""
        self._zone_subscription = self.bus.on_state_change(
            "zone.home",
            changed=C.Increased(),
            handler=self.on_zone_occupancy_increased,
        )
        self.logger.info("Subscribed to zone.home occupancy changes")

    async def on_zone_occupancy_increased(
        self,
        event: RawStateChangeEvent,
    ) -> None:
        """Zone occupancy count increased — someone came home."""
        data = event.payload.data
        self.logger.info(
            "zone.home occupancy increased: %s -> %s",
            data.old_state_value,
            data.new_state_value,
        )

    async def log_status(self) -> None:
        """Periodic presence status log."""
        cfg = self.app_config
        tracker = self.states.device_tracker.get(cfg.tracker_entity)
        if tracker:
            self.logger.info(
                "%s status: %s (lat=%s, lon=%s)",
                cfg.person_name,
                tracker.value,
                tracker.attributes.latitude,
                tracker.attributes.longitude,
            )
        else:
            self.logger.warning("Tracker entity %s not found", cfg.tracker_entity)
