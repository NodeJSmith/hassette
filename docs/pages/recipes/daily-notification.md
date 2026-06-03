# Daily Notification

You want a push notification at the same time every day. A morning greeting, a weather briefing, a reminder. Home Assistant's notify services already handle delivery. This recipe schedules the call from Python, without touching HA automations.

## The Code

```python
--8<-- "pages/recipes/snippets/daily_notification.py"
```

## How It Works

`DailyNotificationConfig` defines three fields: the wall-clock time as an `"HH:MM"` string, the notify service name, and the message body. All three carry defaults and can be overridden per instance in `hassette.toml`. The `env_prefix` means environment variables (`DAILY_NOTIFICATION_NOTIFY_TIME`, etc.) override config file values.

`on_initialize` calls `self.scheduler.run_daily(self.send_notification, at=...)` with the configured time string. `run_daily` registers a [`Daily`][hassette.scheduler.triggers.Daily] trigger that aligns to wall-clock time and handles DST transitions. The notification fires at 08:00 local time year-round, not at a fixed UTC offset.

`send_notification` calls `self.api.call_service("notify", self.app_config.notify_service, ...)`. The first argument is the HA domain (`notify`). The second is the service name, the part after `notify.` in the HA instance. For `notify.mobile_app_phone`, pass `"mobile_app_phone"`. Extra keyword arguments (`message`, `title`) become `service_data` fields forwarded to Home Assistant.

## Verify It's Working

Confirm the job is registered immediately after startup:

```
hassette job --app daily_notification
```

Expected output:

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

If the second line is missing, check the HA logs for a failed service call.

## Variations

**Different time.** Change `notify_time` in `hassette.toml`:

```toml
[apps.daily_notification]
notify_time = "20:30"
notify_service = "mobile_app_tablet"
message = "Time to wind down."
```

**Include sensor data.** Fetch a live sensor value before sending. `get_state` returns the current entity state; `.value` holds the state string:

```python
--8<-- "pages/recipes/snippets/daily_notification_handler.py:send_notification"
```

**Weekdays only.** Swap `run_daily` for `run_cron` to skip weekends. `run_cron` accepts a standard cron expression. The fragment below derives the cron fields from the `"HH:MM"` config string:

```python
--8<-- "pages/recipes/snippets/daily_notification_handler.py:cron_parse"
```

## See Also

- [Scheduler Methods](../core-concepts/scheduler/methods.md), covering `run_daily`, `run_cron`, and all scheduling options
- [API Overview](../core-concepts/api/index.md), covering `call_service` and other Home Assistant API methods
