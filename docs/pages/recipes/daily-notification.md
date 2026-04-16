# Daily Notification

Send a push notification to a mobile device at a configurable time each day. Drop this in to get a morning greeting, a reminder, or any fixed-schedule alert without touching Home Assistant automations.

## The Code

```python
--8<-- "pages/recipes/snippets/daily_notification.py"
```

## How It Works

- **`DailyNotificationConfig`** defines three env-backed fields: the time as a `"HH:MM"` string, the notify service name, and the message body — all overridable without changing code.
- **`on_initialize`** calls `self.scheduler.run_daily(...)` with `at=self.app_config.notify_time`, scheduling a wall-clock-aligned daily job. The `Daily` trigger is cron-backed and handles DST transitions correctly.
- **`send_notification`** calls `self.api.call_service("notify", <service>, ...)` — the domain is `notify` and the service name is the part after `notify.` in your Home Assistant instance (e.g., `mobile_app_phone`).
- Extra keyword arguments to `call_service` (`message`, `title`) become `service_data` fields forwarded to Home Assistant.

## Variations

**Different time** — Change `notify_time` in your config:

```yaml
# apps.yaml
daily_notification:
  module: daily_notification
  class: DailyNotificationApp
  notify_time: "20:30"   # 8:30 PM
  notify_service: mobile_app_tablet
  message: "Time to wind down."
```

**Include sensor data** — Fetch a sensor value before sending:

```python
async def send_notification(self) -> None:
    temp_state = await self.api.get_state("sensor.outdoor_temperature")
    message = f"Good morning! It's {temp_state.state}° outside."
    await self.api.call_service(
        "notify",
        self.app_config.notify_service,
        message=message,
        title="Daily Reminder",
    )
```

**Weekdays only** — Swap `run_daily` for `run_cron` to skip weekends:

```python
# Parse the "HH:MM" config value into a cron expression
h, m = self.app_config.notify_time.split(":")
self.scheduler.run_cron(self.send_notification, f"{m} {h} * * 1-5")
```

## See Also

- [Scheduler Methods](../core-concepts/scheduler/methods.md) — `run_daily`, `run_cron`, and all scheduling options
- [API Services](../core-concepts/api/index.md) — `call_service` and other Home Assistant API methods
