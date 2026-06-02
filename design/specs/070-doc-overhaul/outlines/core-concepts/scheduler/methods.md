# Scheduling Methods

**Status:** Rewrite from blank
**Voice mode:** Reference — terse, system-as-subject, code-heavy
**Page type:** Reference
**Reader's job:** Find the right method for a scheduling task, understand its parameters, and handle edge cases.

The existing page is a comprehensive reference and mostly well-organized. The main problems: (1) Job Groups, Jitter, and Idempotent Registration are on both this page and the overview, creating overlap — consolidate them here since they're per-method options. (2) The parameter tables repeat the same 6 common parameters for every method, which is noisy. Extract shared parameters to one table, then show only method-specific parameters per method. (3) `run_minutely` and `run_hourly` are thin wrappers around `run_every` — collapse them into one subsection instead of giving each a full parameter table.

## What was cut (and where it goes)

- **Job Groups, Jitter, Idempotent Registration** — removed from Overview, consolidated here. These are per-method `schedule()` parameters.
- **Error handling** (`on_error=`, `timeout=`, `timeout_disabled=`) — stays here as "Per-Job Options" since they're method parameters. The Management page covers the error handler registration pattern (`scheduler.on_error()`) and `SchedulerErrorContext`.

## Outline

### H2: Shared Parameters
One table listing the parameters common to all scheduling methods: `name`, `group`, `jitter`, `timeout`, `timeout_disabled`, `if_exists`, `args`, `kwargs`. Each with type, default, and one-line description. This table is defined once; individual methods reference it.

### H2: `schedule(func, trigger)`
The generic entry point. Accepts any `TriggerProtocol`. All convenience methods delegate here. Parameter table showing only `func` and `trigger` (plus a link to shared parameters). Snippet.

### H2: Delay and One-Shot Methods
#### H3: `run_in(func, delay)`
Run once after N seconds. Method-specific parameter: `delay` (float, seconds). Snippet.

#### H3: `run_once(func, at)`
Run once at a wall-clock time. Method-specific parameter: `at` (str `"HH:MM"` or `ZonedDateTime`). Note: past `"HH:MM"` times defer to tomorrow with a WARNING; `ZonedDateTime` inputs fire immediately if past. Snippet.

### H2: Repeating Methods
#### H3: `run_every(func, hours, minutes, seconds)`
Fixed interval, drift-resistant. The three time-component parameters are additive. Snippet.

#### H3: `run_minutely` / `run_hourly`
Shorthands for `run_every(minutes=N)` and `run_every(hours=N)`. One combined snippet showing both.

#### H3: `run_daily(func, at)`
Once per day at a fixed wall-clock time. Cron-backed for DST correctness. Method-specific parameter: `at` (str `"HH:MM"`, default `"00:00"`). Snippet.

#### H3: `run_cron(func, expression)`
Arbitrary cron schedule. 5-field or 6-field (with seconds). Cron field reference table. Snippet.

### H2: Job Groups
`group=` parameter for organizing related jobs. `cancel_group()` for bulk cancellation. `list_jobs(group=)` for inspection. Snippet.

### H2: Jitter
`jitter=` parameter — random offset applied at enqueue time. Affects dispatch order, not the trigger's interval grid. Snippet.

### H2: Idempotent Registration
`if_exists=` parameter: `"error"` (default), `"skip"` (same config required), `"replace"` (cancel old, register new). Essential for `on_initialize` which re-runs on reload. Snippet showing both `"skip"` and `"replace"`.

### H2: Passing Arguments to Handlers
`args=` and `kwargs=` — pass data without capturing mutable state in closures. Snippet.

### H2: Synchronous Scheduling
`self.scheduler.sync` (`SchedulerSyncFacade`) mirrors all methods as blocking calls for `AppSync` hooks.

### H2: Custom Triggers
Implementing `TriggerProtocol` for scheduling patterns the built-ins don't cover. Six-method protocol table: `first_run_time`, `next_run_time`, `trigger_label`, `trigger_detail`, `trigger_db_type`, `trigger_id`. Snippet showing a custom trigger class and its usage with `schedule()`.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `scheduler_schedule_examples.py` | Keep | `schedule()` usage |
| `scheduler_run_in.py` | Keep | `run_in` example |
| `scheduler_run_once.py` | Keep | `run_once` example |
| `scheduler_run_every.py` | Keep | `run_every` example |
| `scheduler_run_minutely.py` | Keep | Combined with `run_hourly` |
| `scheduler_run_hourly.py` | Keep | Combined with `run_minutely` |
| `scheduler_run_daily.py` | Keep | `run_daily` example |
| `scheduler_run_cron.py` | Keep | `run_cron` with cron syntax |
| `scheduler_job_groups.py` | Keep | Group management |
| `scheduler_jitter.py` | Keep | Jitter usage |
| `scheduler_idempotent_registration.py` | Keep | `if_exists` patterns |
| `scheduler_args_kwargs.py` | Keep | Passing arguments |
| `scheduler_custom_trigger.py` | Keep | `TriggerProtocol` implementation |

No new snippets needed.

## Cross-Links

- **Links to:** Job Management (cancellation, errors, ScheduledJob object), Scheduler overview
- **Linked from:** Scheduler overview, Recipes
