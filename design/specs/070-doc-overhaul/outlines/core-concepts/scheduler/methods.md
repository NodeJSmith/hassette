# Scheduler — Scheduling Methods

**Status:** Exists (280 lines), comprehensive reference, voice polish needed
**Voice mode:** Reference — terse, system-as-subject, code-heavy

## Outline

### H2: Primary Entry Point — `schedule`
The generic `schedule(func, trigger)` method. All convenience methods are shortcuts for this.

### H2: Convenience Methods
#### H3: `run_in` — run after a delay
#### H3: `run_once` — run at a specific time
#### H3: `run_every` — run at a fixed interval

### H2: Convenience Interval Helpers
#### H3: `run_minutely`
#### H3: `run_hourly`
#### H3: `run_daily`

### H2: Cron Scheduling — `run_cron`
Cron expression syntax, examples.

### H2: Job Groups
`group=` parameter, `cancel_group()`, `list_jobs(group=)`.

### H2: Jitter
`jitter=` parameter for randomizing execution times.

### H2: Idempotent Registration
`name=` identifies the job; `if_exists=` (`"error"`, `"skip"`, `"replace"`) controls behavior on duplicate name.

### H2: Per-Job Options
#### H3: `on_error=` — per-registration error handler
#### H3: `timeout=` / `timeout_disabled=` — per-job timeout control
#### H3: `args=` and `kwargs=` — passing arguments to handlers

### H2: Synchronous Scheduling
`self.scheduler.sync` (`SchedulerSyncFacade`) — mirrors all methods as blocking calls for `AppSync` hooks.

### H2: Custom Triggers
Implementing `TriggerProtocol` for custom scheduling logic.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~15 files from `scheduler/snippets/` | Review | Method-specific examples |

## Cross-Links

- **Links to:** Job Management, Scheduler overview, Custom Triggers (TriggerProtocol)
- **Linked from:** Scheduler overview, Recipes
