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
`name=` parameter for preventing duplicate jobs.

### H2: Passing Arguments to Handlers
`args=` and `kwargs=` parameters.

### H2: Custom Triggers
Implementing `TriggerProtocol` for custom scheduling logic.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~15 files from `scheduler/snippets/` | Review | Method-specific examples |

## Cross-Links

- **Links to:** Job Management, Scheduler overview, Custom Triggers (TriggerProtocol)
- **Linked from:** Scheduler overview, Recipes
