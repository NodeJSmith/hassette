# Recipes — Daily Notification

**Status:** Exists (47 lines), follows recipe template, voice polish needed
**Voice mode:** Recipe — problem statement, code, How It Works, variations

## Outline

### H2: (Problem Statement)
Send a notification at a fixed time every day (weather summary, reminder, etc.).

### H2: The Code
Full app with `run_daily` and `call_service` for notify.

### H2: How It Works
Walk through the code decisions. Voice-guide rule #21: system-as-subject, one decision per paragraph.

### H2: Verify It's Working
**New section needed** — add `hassette log` / `hassette job` verification step per recipe template.

### H2: Variations
Alternative triggers (cron), different notification services, conditional notifications.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `daily_notification.py` (in `recipes/snippets/`) | Keep | Review for voice, DI alignment |

## Cross-Links

- **Links to:** Scheduler/Methods (run_daily, run_cron), API/Services (call_service)
- **Linked from:** Recipes overview
