# Daily Notification

You want a push notification at the same time every day. A morning greeting, a weather briefing, a reminder. Home Assistant's notify services already handle delivery. This recipe schedules the call from Python, without touching HA automations.

## The Code

```python
--8<-- "pages/recipes/snippets/daily_notification.py"
```

## Run It

Save the code as `daily_notification.py` in your apps directory and register it in `hassette.toml`:

```toml
[hassette.apps.daily_notification]
filename = "daily_notification.py"
class_name = "DailyNotificationApp"
```

The section name (`daily_notification`) is the app key — the same key the `hassette job` and `hassette log` commands below take via `--app`. [App Configuration](../core-concepts/apps/configuration.md) covers registration in full.

## How It Works

Every `App` instance carries `self.scheduler` (runs functions on a schedule), `self.api` (calls HA services), and `self.app_config` (the validated config) — Hassette provides them at startup. Lifecycle hooks and handlers are `async def`; Hassette runs the event loop, so the pattern works without prior async experience.

`DailyNotificationConfig` defines three fields: the wall-clock time as an `"HH:MM"` string (24-hour local time), the notify service name, and the message body. All three carry defaults and can be overridden per instance in [`hassette.toml`](../core-concepts/configuration/index.md). Find your notify service name in HA under **Developer Tools → Services**, filter for `notify` — it looks like `mobile_app_your_device_name`. The `model_config = SettingsConfigDict(...)` line is standard boilerplate from `pydantic-settings` (installed with Hassette — nothing extra to install); its `env_prefix` means environment variables like `DAILY_NOTIFICATION_MESSAGE=...` also override config file values.

`on_initialize` calls `self.scheduler.run_daily(self.send_notification, at=...)` with the configured time string. `run_daily` registers a [`Daily`][hassette.scheduler.triggers.Daily] trigger that recalculates the next fire time after each trigger, so clock-forward and clock-back DST transitions do not cause double-fires or skips. The notification fires at 08:00 local time year-round.

`send_notification` calls `self.api.call_service("notify", self.app_config.notify_service, ...)`. The first argument is the HA domain (`notify`). The second is the service name, the part after `notify.` in the HA instance. For `notify.mobile_app_phone`, pass `"mobile_app_phone"`. Extra keyword arguments (`message`, `title`) are sent to the service as its data fields — `service_data` in HA terms.

## Verify It's Working

Run these from your project directory while Hassette is running. Confirm the job is registered immediately after startup:

```
hassette job --app daily_notification
```

Expected output (`instance 0` is the default when one copy of the app runs):

```
daily_notification (instance 0)
  send_notification   next: 2026-06-03 08:00:00 local   trigger: daily@08:00
```

After the scheduled time fires, check the log to confirm delivery:

```
hassette log --app daily_notification --since 1d
```

Expected output includes two lines:

```
INFO  Daily notification scheduled at 08:00 via notify.mobile_app_phone
INFO  Daily notification sent.
```

If the second line is missing, check the Home Assistant logs (**Settings → System → Logs**) for a failed service call.

## Variations

**Different time.** Change `notify_time` in the app's config block in `hassette.toml`:

```toml
[hassette.apps.daily_notification.config]
notify_time = "20:30"
notify_service = "mobile_app_tablet"
message = "Time to wind down."
```

**Include sensor data.** Fetch a live sensor value before sending — replace `send_notification` with this version. `get_state` returns the current entity state; `.value` holds the state string:

```python
--8<-- "pages/recipes/snippets/daily_notification_handler.py:send_notification"
```

**Weekdays only.** Swap `run_daily` for `run_cron` to skip weekends. `run_cron` accepts a standard cron expression — fields are minute first, so `f"{m} {h} * * 1-5"` means "at `h:m` on days 1–5 (Monday–Friday)". The fragment below derives the cron fields from the `"HH:MM"` config string:

```python
--8<-- "pages/recipes/snippets/daily_notification_handler.py:cron_parse"
```

## See Also

- [`Scheduler` Methods](../core-concepts/scheduler/methods.md), covering `run_daily`, `run_cron`, and all scheduling options
- [API Overview](../core-concepts/api/index.md), covering `call_service` and other Home Assistant API methods
