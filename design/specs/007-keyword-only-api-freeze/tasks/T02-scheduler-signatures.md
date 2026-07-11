---
task_id: "T02"
title: "Lock scheduler registration signatures to keyword-only with required name"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#4", "AC#1", "AC#2", "AC#4"]
---

## Summary
Move the `*` separator before `name` on all 8 Scheduler methods, change `name` from optional to required (`name: str`, no default), add runtime checks for empty name on both `schedule()` and `add_job()`, fix the internal `state_proxy.py` call site, update the module-level docstring examples, and add ~115 missing `name=` kwargs to scheduler test call sites.

## Target Files
- modify: `src/hassette/scheduler/scheduler.py`
- modify: `src/hassette/core/state_proxy.py`
- modify: `tests/unit/test_scheduler_job_names.py`
- modify: `tests/unit/test_scheduler_resource.py`
- modify: `tests/unit/scheduler/test_scheduler_where.py`
- modify: `tests/unit/scheduler/test_scheduler_error_handler.py`
- modify: `tests/unit/scheduler/test_scheduler_coroutine_conversion.py`
- modify: `tests/unit/scheduler/test_scheduler_timeout_threading.py`
- modify: `tests/unit/scheduler/test_scheduled_job_lifecycle.py`
- modify: `tests/integration/test_scheduler.py`
- modify: `tests/integration/test_scheduler_mode.py`
- modify: `tests/integration/test_scheduler_error_handler.py`
- modify: `tests/system/test_scheduler.py`
- read: `src/hassette/exceptions.py` (SchedulerNameRequiredError from T01)
- read: `src/hassette/bus/bus.py` (Bus.add_listener name guard pattern)

## Prompt
In `src/hassette/scheduler/scheduler.py`, make these changes to all 8 scheduling methods (`schedule`, `run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `run_cron`):

1. **Move `*`** from its current position (after `timeout_disabled`, before `mode`) to before `name`. This makes `name`, `group`, `jitter`, `timeout`, `timeout_disabled` keyword-only. For `run_once`, also move `if_past` after `*`.

2. **Change `name` type** from `name: str = ""` to `name: str` (required, no default).

3. **Add runtime check** at the top of `Scheduler.schedule()` (the primary — all convenience methods delegate here):
```python
if not name:
    raise SchedulerNameRequiredError(func.__name__ if hasattr(func, "__name__") else str(func), str(trigger))
```
Import `SchedulerNameRequiredError` from `hassette.exceptions`.

4. **Add symmetric check to `add_job()` / `_add_job()`** — this entry point takes a pre-built `ScheduledJob` and bypasses `schedule()`:
```python
if not job.name:
    raise SchedulerNameRequiredError(job.job.__name__ if hasattr(job.job, "__name__") else str(job.job), str(job.trigger))
```
Mirror `Bus.add_listener()`'s guard at `bus.py:256`.

5. **Update docstrings** on all 8 methods: remove "If empty, an auto-name is derived from the callable and trigger ID" language. Document `name` as required.

6. **Update module-level docstring** (~lines 10-59): ~10 usage examples omit `name=`. Add `name="descriptive_name"` to each example.

7. **Fix internal call site** `src/hassette/core/state_proxy.py` (~lines 102-107): `self.scheduler.run_every(self.load_cache, ...)` needs explicit `name="state_proxy_poll"`.

8. **Add new tests** to `tests/unit/test_scheduler_job_names.py`:
   - Test `SchedulerNameRequiredError` raised when `name=""` passed to `schedule()` and each convenience method
   - Test `SchedulerNameRequiredError` raised when `add_job()` called with `job.name == ""`
   - A few representative tests that positional `name`, `group`, `jitter`, `timeout`, `timeout_disabled` raise `TypeError`

9. **Bulk test update**: Add `name="test_xyz"` (descriptive, derived from test context) to scheduler test call sites that currently omit `name=`. The grep `grep -rn 'scheduler\.\(schedule\|run_in\|run_once\|run_every\|run_daily\|run_cron\|run_minutely\|run_hourly\)(' tests/ | grep -v 'name='` gives ~115 hits, but many are false positives from multi-line calls where `name=` appears on a following line. For each hit, read the full call (may span multiple lines) before editing — only add `name=` to calls that genuinely omit it. The actual count is closer to ~96.

## Focus
The `*` currently sits at different positions depending on the method:
- `schedule`: `func, trigger, name, group, jitter, timeout, timeout_disabled, *, mode, on_error, ...`
- `run_in`: `func, delay, name, group, jitter, timeout, timeout_disabled, *, mode, on_error, ...`
- `run_once`: `func, at, name, group, jitter, timeout, timeout_disabled, if_past, *, mode, on_error, ...`
- `run_every`: `func, hours, minutes, seconds, name, group, jitter, timeout, timeout_disabled, *, mode, on_error, ...`

After the change, all should have `func, <method-specific-arg(s)>, *, name, group, jitter, ...` with `name` immediately after `*`.

The `SchedulerSyncFacade` in `sync.py` is auto-generated — do NOT edit it. T04 handles regeneration.

The bulk test update is mechanical: each call gets a `name="descriptive_label"` kwarg. Derive names from test function name or context (e.g., `name="test_cancellation_job"`, `name="poll_job"`).

## Verify
- [ ] FR#1: Calling `scheduler.run_in(func, 5, "positional_name")` raises `TypeError` (name is keyword-only)
- [ ] FR#4: `SchedulerNameRequiredError` raised when `name=""` passed to `schedule()`, and when `add_job()` called with empty `job.name`
- [ ] AC#1: `uv run pyright` reports error when `scheduler.run_in(func, 5, handler=h)` omits `name=`
- [ ] AC#2: Positional `name`, `group`, `jitter`, `timeout`, `timeout_disabled` raise `TypeError`
- [ ] AC#4: `SchedulerNameRequiredError` raised for empty name on all scheduling methods
