from hassette import App, AppConfig, P


class WaterLeakAlertApp(App[AppConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            "binary_sensor.water_leak",
            handler=self.on_leak_detected,
            where=P.StateTo("on"),
        )

    async def on_leak_detected(self, event):
        """Send notification, but not more than once every 4 hours."""
        cache_key = "last_leak_notification"

        # Check when we last sent a notification
        last_sent = self.cache.get(cache_key)

        if last_sent is not None:
            if last_sent > self.now().subtract(hours=4):
                time_since_last = self.now() - last_sent
                self.logger.info("Skipping notification - last sent %s ago", time_since_last)
                return

        # Send the notification
        await self.api.call_service(
            "notify",
            "mobile_app",
            message="Water leak detected!",
            title="Alert",
        )

        # Update cache with current time
        self.cache[cache_key] = self.now()
        self.logger.info("Leak notification sent")
