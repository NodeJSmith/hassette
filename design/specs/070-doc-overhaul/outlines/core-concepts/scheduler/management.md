# Job Management

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Cancel, inspect, and handle errors for scheduled jobs.

The existing page is well-structured but mixes two reader jobs: "how do I manage job lifecycle?" (cancel, inspect, automatic cleanup) and "how do I handle errors?" These are distinct concerns. The reader who needs to cancel a job doesn't need error handler registration in the same mental frame. Group lifecycle operations first (the more common need), then error handling.

The "Best Practices" section feels bolted on. Job naming is an idempotent registration concern (covered on Methods page). Overlapping jobs is a real operational issue — keep it, but as a targeted subsection rather than a numbered best-practices list.

## What was cut (and where it goes)

- **Job naming guidance** (the "Name your jobs" best practice) — idempotent registration is now fully covered on the Methods page, including `if_exists` semantics. A brief reminder here that names appear in logs is fine; the full "why name" discussion lives on Methods.
- **Troubleshooting** section — the existing "Job Not Running?" and "Runs Too Often?" sections are good operational content. Keep them as a collapsible section at the end rather than a full H2, since they serve a small subset of readers.

## Outline

### H2: The `ScheduledJob` Object
What `schedule()` and all convenience methods return. Attribute table: `name`, `next_run`, `trigger`, `group`, `jitter`, `job_id`. Note: no public `cancelled` attribute — cancellation state is checked via `list_jobs()`. Snippet showing attribute access.

### H2: Cancelling Jobs
`job.cancel()` — immediate removal from the scheduler queue. Snippet.

#### H3: Cancelling Groups
`cancel_group(group)` — cancel all jobs in a named group. Snippet.

#### H3: Listing Jobs
`list_jobs()` — all active jobs. `list_jobs(group=)` — jobs in a group. Snippet.

#### H3: Checking Whether a Job Is Active
No `cancelled` attribute. Check via `list_jobs()`, or store the reference as `None` after cancelling. Snippet showing both patterns.

### H2: Automatic Cleanup
All jobs created by an app are cancelled automatically when the app stops or reloads. Manual cancellation is only needed to stop a job while the app is running.

### H2: Self-Cancelling Jobs
Pattern for "poll until condition met" — store the `ScheduledJob` reference on the app, cancel from inside the handler. Note: double-execution cannot occur (dispatch checks dequeue state). Snippet.

### H2: Avoiding Overlapping Executions
When a job takes longer than its interval, multiple instances run concurrently. Guard with `asyncio.Lock`. Snippet.

### H2: Error Handling
#### H3: App-Level Error Handler
`scheduler.on_error(handler)` — all jobs without a per-registration handler. Register first in `on_initialize()`. Snippet.
#### H3: Per-Registration Error Handler
`on_error=` parameter on any scheduling method. Snippet.
#### H3: What `SchedulerErrorContext` Contains
Table: `job_name`, `job_group`, `args`, `kwargs`, plus `exception` and `traceback` from `ErrorContext` base.

### Collapsible: Troubleshooting
??? note "Job not running?"
- Wrong time string or interval?
- Unhandled exception? (logged at ERROR, job keeps firing)
- Lost reference? (doesn't stop the job, but prevents cancellation)

??? note "Job runs too often?"
- Check units: `seconds=5` is 5 seconds, not minutes
- Check cron: `"5 * * * *"` is minute 5 of every hour, not every 5 minutes

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `scheduler_job_metadata.py` | Keep | `ScheduledJob` attributes |
| `scheduler_cancel_job.py` | Keep | Basic cancellation |
| `scheduler_management_patterns.py` | Keep | cancel_group, list_jobs, is_running, cancel_null markers |
| `scheduler_self_cancel.py` | Keep | Self-cancelling pattern |
| `scheduler_overlapping_jobs.py` | Keep | asyncio.Lock guard |
| `scheduler_naming.py` | Keep | Job naming (brief reminder) |
| `scheduler_error_handler_app.py` | Keep | App-level error handler |
| `scheduler_error_handler_per_job.py` | Keep | Per-registration error handler |

No new snippets needed.

## Cross-Links

- **Links to:** Scheduling Methods (registration, `if_exists`, per-job options), Apps lifecycle (shutdown cleanup)
- **Linked from:** Scheduler overview, Recipes (motion lights — job cancellation)
