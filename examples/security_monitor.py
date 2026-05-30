"""Security Monitor.

App that monitors lock service calls and moisture sensor alerts.
Demonstrates on_call_service, throttle, and state access patterns.

Demo entities:
    - lock.front_door
    - lock.kitchen_door
    - binary_sensor.basement_floor_wet
"""

from hassette import App, AppConfig
from hassette.events import CallServiceEvent


class SecurityMonitorConfig(AppConfig):
    moisture_throttle: float = 300.0  # notify at most once per 5 minutes


class SecurityMonitor(App[SecurityMonitorConfig]):
    """Monitor locks and moisture sensors."""

    async def on_initialize(self) -> None:
        cfg = self.app_config
        self.logger.info("Security monitor started (moisture throttle=%.0fs)", cfg.moisture_throttle)

        # Intercept all lock service calls
        await self.bus.on_call_service(
            domain="lock",
            handler=self.on_lock_service_called,
            name="security_monitor.on_lock_service_called",
        )

        # Moisture detection with throttle
        await self.bus.on_state_change(
            "binary_sensor.basement_floor_wet",
            changed_to="on",
            handler=self.on_moisture_detected,
            throttle=cfg.moisture_throttle,
            name="security_monitor.on_moisture_detected",
        )

        # Log current lock states
        for entity_id, lock_state in self.states.lock:
            self.logger.info("Lock %s is currently %s", entity_id, lock_state.value)

    def on_lock_service_called(self, event: CallServiceEvent) -> None:
        """A lock service was called (lock, unlock, etc.)."""
        data = event.payload.data
        self.logger.info(
            "Lock service called: %s.%s — data=%s",
            data.domain,
            data.service,
            data.service_data,
        )

    def on_moisture_detected(self) -> None:
        """Moisture sensor triggered — basement floor is wet."""
        self.logger.warning("ALERT: Moisture detected on basement floor! Immediate attention required.")

        # Log all current lock states for the security report
        self.logger.info("Current lock states during moisture alert:")
        for entity_id, lock_state in self.states.lock:
            self.logger.info("  %s: %s", entity_id, lock_state.value)
