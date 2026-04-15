# Scheduler API Redesign Proposal

**Status**: approved
**Date**: 2026-04-14
**Scope**: Full rewrite of `src/hassette/scheduler/`
**Prior art**: `design/research/2026-04-14-scheduler-api-ergonomics/research.md`
**Brainstorm**: `design/brainstorms/2026-04-14-scheduler-api/brainstorm.md`

---

## Problem Summary

The current scheduler has five issues worth a full redesign:

1. **Method proliferation** — `run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `run_cron` will keep growing as new trigger types are requested.
2. **`run_daily` is silently wrong** — uses a 24-hour `IntervalTrigger`. On restart, the next fire is 24 hours after the last run, not at the original wall-clock time.
3. **`ScheduleStartType` is a 7-type union** — parsed by a 7-branch function; different methods use different subsets with no type-level enforcement.
4. **No job group lifecycle** — automations that reconfigure schedules dynamically must manually track every handle.
5. **`TriggerProtocol` is private** — users cannot write custom triggers without modifying the framework.

---

## Scope of Changes

This is a full rewrite of `src/hassette/scheduler/`. The following areas will change:

- **Public `Scheduler` API** — new trigger object model; `schedule(func, trigger)` replaces the existing `schedule(func, run_at, ...)` internal method (full replacement, not an overload)
- **`TriggerProtocol`** — made public; extended with `trigger_label()`, `trigger_detail()`, `trigger_db_type()`, `trigger_id()`, and `ZonedDateTime | None` return from `next_run_time()`
- **`ScheduledJob`** — adds `group` and `jitter` fields; removes `repeat` as a runtime field (retained DB-only); `matches()` updated to use `trigger_id()` and include `group`
- **`scheduler_service._enqueue_then_register`** — isinstance dispatch replaced with protocol method calls
- **`scheduler_service.reschedule_job`** — rewritten to call `trigger.next_run_time()` and remove the job when `None` is returned; `repeat` flag gate removed from this path
- **`web/utils.resolve_trigger()`** — isinstance dispatch replaced with protocol method calls
- **DB schema** — no new tables; `trigger_type` value set expands from `{"interval", "cron"}` to `{"interval", "cron", "once", "after"}`; two new columns added to `scheduled_jobs`: `trigger_label TEXT` and `trigger_detail TEXT NULL`; `make_job()` and E2E fixtures updated accordingly
- **Convenience methods** — kept as thin sugar; old parameter forms (`interval=`, keyword-per-field cron, `start=` tuple, `days=`) removed outright

---

## Core: One Entry Point, Trigger Objects as Nouns

The existing `Scheduler.schedule()` method is replaced wholesale. The new public entry point is:

```python
def schedule(
    self,
    func: JobCallable,
    trigger: TriggerProtocol,
    name: str = "",
    group: str | None = None,
    jitter: float | None = None,
    *,
    if_exists: Literal["error", "skip"] = "error",
    args: tuple[Any, ...] | None = None,
    kwargs: Mapping[str, Any] | None = None,
) -> ScheduledJob: ...
```

Usage:

```python
job = self.scheduler.schedule(self.my_callback, Every(hours=1))
job = self.scheduler.schedule(self.my_callback, Daily(at="07:00"))
job = self.scheduler.schedule(self.my_callback, Cron("0 9 * * 1-5"))
job = self.scheduler.schedule(self.my_callback, Once(at="07:00"))
job = self.scheduler.schedule(self.my_callback, After(seconds=30))
```

Convenience methods remain as thin sugar for the most common patterns:

```python
# These are thin wrappers — same behaviour, familiar names
job = self.scheduler.run_in(self.my_callback, 30)
job = self.scheduler.run_daily(self.my_callback, at="07:00")
job = self.scheduler.run_every(self.my_callback, hours=1)
job = self.scheduler.run_cron(self.my_callback, "0 9 * * 1-5")
```

---

## `TriggerProtocol` — Public, Extended

`TriggerProtocol` is re-exported from `hassette.scheduler`. Six methods:

```python
class TriggerProtocol(Protocol):
    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime: ...
    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime | None: ...
    def trigger_label(self) -> str: ...
    def trigger_detail(self) -> str | None: ...
    def trigger_db_type(self) -> Literal["interval", "cron", "once", "after", "custom"]: ...
    def trigger_id(self) -> str: ...
```

**`next_run_time` returns `ZonedDateTime | None`**. `None` signals exhaustion — the job is removed after it fires. One-shot triggers (`Once`, `After`) return `None`. Recurring triggers always return a value.

**`SchedulerService.reschedule_job` contract**: After a job fires, `reschedule_job` calls `trigger.next_run_time()`. If the return value is `None`, the job is removed immediately — no re-enqueue, no `repeat` flag consulted. If `next_run_time()` raises an exception, the job is also removed, the exception is logged with full job context (job id, callable name, trigger repr), and execution continues normally. The scheduler must never crash due to a misbehaving trigger. `ScheduledJob.repeat` is **not** consulted at runtime — `reschedule_job` delegates entirely to the `None` return to determine exhaustion.

**`trigger_db_type()`** is the stable DB/API discriminator. It returns one of five fixed literals and is used to populate `trigger_type` in `scheduled_jobs` and the REST API. This value must never change for a given trigger type — it is a DB key. Built-in triggers return their specific type; custom triggers return `"custom"`. The `Literal` return type ensures Pyright catches any new built-in trigger that omits a DB type.

**`trigger_label()`** is a free human-readable display string. It may change between versions without affecting DB rows or API consumers. It replaces all `isinstance(trigger, IntervalTrigger)` / `isinstance(trigger, CronTrigger)` dispatch in `_enqueue_then_register` and `web/utils.resolve_trigger()`.

**`trigger_id()`** returns a stable string key uniquely identifying this trigger's configuration (e.g., `"every:3600"`, `"cron:0 7 * * *"`, `"solar_poll:60"`). `ScheduledJob.matches()` uses `trigger_id()` — not `==` — to compare triggers for deduplication. Custom triggers that omit a meaningful `trigger_id()` will register duplicates under `if_exists="skip"` since their default implementation returns the same value for all instances of the same type.

**`trigger_detail()`** is an optional secondary display string (e.g., the raw cron expression). Display-only; no stability requirement.

Example built-in implementations:

| Trigger | `trigger_db_type()` | `trigger_label()` | `trigger_id()` | `trigger_detail()` |
|---------|---------------------|-------------------|----------------|--------------------|
| `Every(hours=1)` | `"interval"` | `"interval"` | `"every:3600"` | `"3600s"` |
| `Daily(at="07:00")` | `"cron"` | `"cron"` | `"cron:0 7 * * *"` | `"0 7 * * *"` |
| `Cron("0 9 * * 1-5")` | `"cron"` | `"cron"` | `"cron:0 9 * * 1-5"` | `"0 9 * * 1-5"` |
| `Once(at="07:00")` | `"once"` | `"once"` | `"once:07:00"` | `"07:00"` |
| `After(seconds=30)` | `"after"` | `"after"` | `"after:30"` | `"30s"` |

Example custom trigger:

```python
from hassette.scheduler import TriggerProtocol
from typing import Literal
from whenever import ZonedDateTime

class SolarPollTrigger:
    """Polls on a fixed interval for use with elevation-based logic in the callback."""

    def __init__(self, check_every: int = 60):
        self.check_every = check_every

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        return current_time.add(seconds=self.check_every)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        return current_time.add(seconds=self.check_every)

    def trigger_label(self) -> str:
        return f"solar_poll (every {self.check_every}s)"

    def trigger_detail(self) -> str | None:
        return f"every {self.check_every}s"

    def trigger_db_type(self) -> Literal["interval", "cron", "once", "after", "custom"]:
        return "custom"

    def trigger_id(self) -> str:
        return f"solar_poll:{self.check_every}"
```

---

## Trigger Types

All trigger types live in `hassette.scheduler.triggers` and are importable from `hassette.scheduler`.

### `After` — one-shot after a delay

```python
After(seconds=30)
After(minutes=5)
After(timedelta=TimeDelta(minutes=5))
```

`next_run_time()` returns `None` — fires once and is removed.

### `Once` — one-shot at a specific wall-clock time

```python
Once(at="07:00")                           # today at 07:00; if already past, tomorrow
Once(at="07:00", if_past="error")          # raise ValueError if construction time is after 07:00
Once(at=ZonedDateTime(...))                # specific instant
```

`next_run_time()` returns `None` — fires once and is removed.

`if_past: Literal["tomorrow", "error"] = "tomorrow"` controls behaviour when `Once` is constructed after the specified wall-clock time has already passed today. The default (`"tomorrow"`) defers to the same time tomorrow and emits a `WARNING` log: `"Once(at='07:00') constructed after the target time — deferring to tomorrow."` Set `if_past="error"` to raise `ValueError` instead, preserving the prior behaviour for automations that relied on the exception to detect scheduling errors.

### `Every` — fixed interval, drift-resistant

```python
Every(seconds=30)
Every(minutes=5)
Every(hours=1)
Every(hours=1, start=ZonedDateTime(...))  # first fire at this instant, then every N
```

`start=` accepts only `ZonedDateTime` or `None`. Wall-clock anchored scheduling (fire at 07:00, 08:00, ...) requires `Cron` or `Daily`. `Every` is elapsed-time only — this avoids the DST trap where a string `start="07:00"` would appear wall-clock anchored but use elapsed-seconds arithmetic internally.

Preserves drift-resistant `_advance_past()` anchor arithmetic from the current `IntervalTrigger`.

### `Daily` — wall-clock anchored, DST-safe

```python
Daily(at="07:00")  # every day at 07:00
```

`Daily` uses `CronTrigger` internally. This fixes the current `run_daily` bug, which used a 24-hour `IntervalTrigger` and drifted from wall-clock time on restart.

`Daily` does **not** accept an `every=N` parameter. "Every N days at 07:00" sounds like a natural extension but `*/N` in the day-of-month cron field fires on even calendar day numbers (1st, 3rd, 5th, ...), not "N days after the last fire." Use `Cron` with an explicit expression for multi-day cadences.

### `Cron` — cron expression

```python
Cron("0 9 * * 1-5")       # weekdays at 9am (5-field)
Cron("0 9 * * 1-5 0")     # weekdays at 9am, second=0 (6-field)
```

Accepts both 5-field (standard) and 6-field (seconds appended) expressions via `croniter`.

---

## Jitter

Jitter is a scheduling concern, not a trigger concern. It lives at the `schedule()` call site and is applied by `SchedulerService`:

```python
self.scheduler.schedule(
    self.midnight_check,
    Daily(at="00:00"),
    jitter=60,  # fires somewhere in the 60 seconds after midnight
)

self.scheduler.run_daily(self.midnight_check, at="00:00", jitter=60)
```

`jitter: float | None = None` (seconds). Applied as `random.uniform(0, jitter)` added to the computed fire time. Jitter is applied to **both** the initial `first_run_time()` output and each subsequent `next_run_time()` output — this ensures one-shot jobs (`Once`, `After`) with a jitter value actually fire in a randomised window, not at the exact trigger time.

**Storage and heap semantics**: `jitter` is stored as a field on `ScheduledJob`. `job.next_run` always reflects the **unjittered** logical fire time — this is the value passed as `previous_run` in subsequent `trigger.next_run_time()` calls, ensuring drift-resistant interval arithmetic is not contaminated by random jitter offsets. Jitter is added only to the heap `sort_index` at enqueue time. `reschedule_job` reads `job.jitter` and applies a fresh random offset to each re-fire.

Triggers themselves are stateless — jitter state lives in the `ScheduledJob`, not the trigger.

---

## Job Groups

Jobs accept an optional `group=` parameter. Group membership is tracked in `_jobs_by_group: dict[str, set[ScheduledJob]]` on the per-app `Scheduler` resource — not in the shared `SchedulerService` queue, ensuring cross-app isolation.

```python
async def on_initialize(self):
    self.scheduler.schedule(self.wake_lights, Daily(at="07:00"), group="morning")
    self.scheduler.schedule(self.brew_coffee, Daily(at="07:05"), group="morning")
    self.scheduler.schedule(self.morning_report, Daily(at="07:10"), group="morning")

async def disable_morning_routine(self):
    self.scheduler.cancel_group("morning")

jobs = self.scheduler.list_jobs(group="morning")
```

`cancel_group()` iterates `_jobs_by_group[group]`, sets `cancelled=True` on each member, and calls `scheduler_service.remove_job()` for eager heap removal.

**`_jobs_by_group` sync contract**: The dict must be kept in sync by all three removal paths:
- `add_job()` — adds the job to its group set (if `group` is set)
- `remove_job()` — removes the job from its group set; drops the group key when the set becomes empty
- `remove_all_jobs()` — clears `_jobs_by_group` entirely
- `reschedule_job` (via `SchedulerService`) — calls a registered removal callback on the per-app `Scheduler` when a one-shot job is auto-removed after exhaustion; the callback removes the job from its group set

Without this contract, one-shot jobs leave stale references in `_jobs_by_group` indefinitely — `cancel_group` silently no-ops on already-fired jobs and `list_jobs(group=)` returns stale entries as if active.

**Caveat**: jobs still pending in `_enqueue_then_register` at cancel time (mid-registration race) may fire once. This is a known limitation, not a bug to solve here.

`cancel_group` on a nonexistent group is a no-op.

---

## `ScheduledJob` — Updated Surface

```python
job = self.scheduler.schedule(self.my_callback, Daily(at="07:00"), group="morning")
job.cancel()    # cancel this job
job.next_run    # ZonedDateTime of unjittered logical fire time
job.trigger     # the trigger object (TriggerProtocol)
job.cancelled   # bool
job.group       # str | None — new field
job.jitter      # float | None — seconds of random offset applied at enqueue (new field)
```

**`matches()` updated** to include `group`. Two jobs with identical callable, trigger, and args but different `group` values are different logical jobs. Required for `cancel_group` and `if_exists="skip"` to behave correctly under dynamic reconfiguration.

`.cancel()` semantics unchanged — passive flag, checked before execution.

---

## Migration

### Breaking changes (all explicit)

- **`start=(7, 0)` tuple syntax removed** across all `run_*` methods. Replace with `Daily(at="07:00")` or equivalent trigger.
- **`run_daily(days=N)` removed** — replace with `Daily(at="HH:MM")` for a daily cadence, or `Cron("0 HH */N * *")` for every-N-days cadence. `Daily` does not accept an `every=N` or `days=N` parameter.
- **`run_every(interval=N)` removed** — use `hours=`/`minutes=`/`seconds=`. The internal framework caller in `state_proxy.py` is updated as part of this work.
- **`run_cron(hour=N, minute=N, ...)` keyword form removed** — positional string (`run_cron("0 9 * * 1-5")`) is the only accepted form.
- **`Scheduler.schedule(func, run_at: ZonedDateTime, ...)` replaced** — the existing internal method is rewritten as `schedule(func, trigger: TriggerProtocol, ...)`. One integration test calls the old form directly and must be updated.
- **`Once(at="07:00")` past-time behavior changed** — the current implementation raises `ValueError` when constructed after the specified wall-clock time. The new behavior fires tomorrow instead. Automations that relied on the exception to detect scheduling errors must be updated.
- **`trigger_type` DB column values expand** — `job_executions` stores `trigger_type` as `"interval"` or `"cron"` today. This rewrite adds `"once"` and `"after"` as valid values. `make_job()` and any E2E fixtures that assert on `trigger_type` must be updated. No new columns or tables.

### Unchanged

- `run_in`, `run_once`, `run_hourly`, `run_minutely` call signatures (except `start=` tuple form)
- `ScheduledJob.cancel()`, `.next_run`, `.trigger`, `.cancelled`, `.job_id`, `.db_id`
- `if_exists="error"` and `if_exists="skip"` semantics
- Source location capture
- DB schema (no new tables or columns; `trigger_type` value set expands — see Breaking Changes above)
- Job persistence, restart reconciliation, `mark_registered()`
- DI callback injection for the job callable itself

---

## Resolved Decisions

1. **`Cron` second field** — **Keep 6-field extension**. Both 5-field (standard) and 6-field (seconds appended) expressions are accepted via `croniter`. Users needing sub-minute precision use the 6th field; standard users use 5-field.

2. **`trigger_label()` / `trigger_detail()` in DB** — **Persist both columns**. `trigger_label TEXT NOT NULL` and `trigger_detail TEXT NULL` are added to `scheduled_jobs`. Populated at registration time from `trigger.trigger_label()` / `trigger.trigger_detail()`. Enables the web UI to display human-readable trigger descriptions without rehydrating the trigger object from DB.
