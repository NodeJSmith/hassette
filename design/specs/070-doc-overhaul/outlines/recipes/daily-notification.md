# Recipes — Daily Notification

**Status:** Exists (47 lines), needs JTBD redesign — "How It Works" uses bullet lists with bold lead-ins (anti-pattern)
**Voice mode:** Recipe — problem statement uses "you", "How It Works" uses system-as-subject prose paragraphs
**Page type:** Recipe
**Reader's job:** Send a push notification at a fixed time every day without manually creating HA automations.

## What was cut

The existing "How It Works" uses bold-label bullet lists. Content stays, format
changes to flowing prose paragraphs.

The existing page is missing a "Verify It's Working" section. Adding one.

The "Different time" variation currently shows `apps.yaml` format. Hassette
uses `hassette.toml` — the example should use TOML config format consistent
with the rest of the docs.

## Outline

### H2: (Problem statement)
You want a daily push notification — a morning greeting, a reminder, or a
fixed-schedule alert. Drop it in without touching HA automations.

### H2: The Code
Full app via `--8<--` include of `daily_notification.py`.

### H2: How It Works
Flowing prose paragraphs, one decision each:

1. Config — `DailyNotificationConfig` defines the time as `"HH:MM"`, the
   notify service name, and the message body. All overridable per-instance.
2. Scheduling — `on_initialize` calls `run_daily(at=...)` with the configured
   time string. The `Daily` trigger is cron-backed and handles DST transitions.
3. Notification — `call_service("notify", <service>, ...)` where the service
   name is the part after `notify.` in HA (e.g., `mobile_app_phone`). Extra
   kwargs become `service_data` fields forwarded to HA.

### H2: Verify It's Working
`hassette job --app <key>` to confirm the daily job is scheduled with the
correct next-run time. `hassette log --app <key> --since 1d` after the
scheduled time to verify the notification fired. Expected: one entry per day.

### H2: Variations
- Different time — change `notify_time` in `hassette.toml`.
- Include sensor data — fetch a sensor value before sending (snippet:
  `daily_notification_handler.py:send_notification`).
- Weekdays only — swap `run_daily` for `run_cron` (snippet:
  `daily_notification_handler.py:cron_parse`).

### H2: See Also
Links to Scheduler/Methods (run_daily, run_cron), API overview (call_service).

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `daily_notification.py` | Keep | Main app |
| `daily_notification_handler.py` | Keep | Variation fragments (send_notification, cron_parse) |

## Cross-Links

- **Links to:** Scheduler/Methods (run_daily, run_cron), API overview (call_service), Testing overview
- **Linked from:** Recipes overview
