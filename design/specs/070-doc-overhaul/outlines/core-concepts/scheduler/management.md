# Scheduler — Job Management

**Status:** Exists (155 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: The ScheduledJob Object
What `schedule()` returns. Fields: `db_id`, `name`, `group`, `next_run`, `fire_at` (actual dispatch time after jitter, distinct from `next_run`). Note: no public `cancelled` field — cancellation state is checked via methods.

### H2: Cancelling Jobs
`job.cancel()`, `cancel_group()`, `list_jobs()`, checking cancellation state.

### H2: Automatic Cleanup
Jobs cancelled automatically on app shutdown.

### H2: Self-Cancelling Job Pattern
Job that cancels itself based on a condition.

### H2: Error Handling
#### H3: App-Level Error Handler — `Scheduler.on_error()`
#### H3: Per-Registration Error Handler — `error_handler=`
#### H3: What `SchedulerErrorContext` Contains
Fields: `exception`, `traceback` (from `ErrorContext` base), `job_name`, `job_group`, `args`, `kwargs`.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~7 files from `scheduler/snippets/` | Review | Management-specific examples |

## Cross-Links

- **Links to:** Scheduling Methods, Apps lifecycle (shutdown cleanup)
- **Linked from:** Scheduler overview, Recipes (motion lights — job cancellation)
