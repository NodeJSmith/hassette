---
task_id: "T03"
title: "Convert scheduler methods to def -> Coroutine"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#9", "FR#10", "AC#2"]
---

## Summary

Convert every public Scheduler scheduling method from `async def -> T` to
`def -> Coroutine[Any, Any, T]` returning a `RegistrationHandle`. `add_job` is the Shape A primary
(its inline async body is extracted to a private `_add_job` coroutine wrapped by `guard_await`);
`schedule` and every `run_*` are Shape B delegates returning the downstream handle. Awaiting any of
them behaves exactly as today (`job.db_id` valid on return). This is a two-level chain
(`run_in → schedule → add_job`) that collapses to one handle at `add_job`.

## Prompt

Per the design doc's `## Architecture` → "Converting the protected methods" (Shape A / Shape B and
the "Multi-level chains are fine" note), convert the methods in `src/hassette/scheduler/scheduler.py`.

**Shape A primary — `add_job`:** today it does inline async work (validation, DB registration via
`await`). Extract its body into a private `async def _add_job(self, job, *, if_exists) -> ScheduledJob`,
then:
```python
def add_job(self, job, *, if_exists="error") -> Coroutine[Any, Any, ScheduledJob]:
    # Coroutine supertype annotation is deliberate (see design/071 / context.md).
    src = capture_registration_source(limit=...)   # capture in the public def
    return guard_await(self._add_job(job, if_exists=if_exists), owner=self.parent, source_location=src)
```

**Shape B delegates — `schedule`, `run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`,
`run_daily`, `run_cron`:** each does synchronous setup (build trigger / build `ScheduledJob`) then
returns the callee's handle directly. `schedule` builds the `ScheduledJob` and returns
`self.add_job(job, ...)`'s handle; each `run_*` builds its trigger and returns `self.schedule(...)`'s
handle. Example:
```python
def run_in(self, func, delay, ...) -> Coroutine[Any, Any, ScheduledJob]:
    trigger = After(seconds=float(delay))    # synchronous setup, unchanged
    return self.schedule(func, trigger, ...) # returns the handle threaded up from add_job
```
Building a `ScheduledJob` in `schedule` is synchronous setup — it stays Shape B (its only `await`
today is the delegation to `add_job`).

Move the `capture_registration_source()` call currently inside `schedule` (scheduler.py:380) so the
single capture happens at `add_job` (the primary). Attribution walks past all `hassette.*` frames to
the user, so capturing once at `add_job` correctly attributes calls made via `run_in`/`schedule`/
`add_job` alike. Add `Coroutine` to the `collections.abc` import in `scheduler.py`.

Update/add unit tests: awaiting each method still schedules a job (db_id set); a forgotten `await` on
`add_job`, `schedule`, AND a `run_*` method each emit `HassetteForgottenAwaitWarning`; awaited calls
emit no warning. Run the affected scheduler test files locally and confirm they pass.

## Focus

- Method anchors (verify by symbol): `add_job` (~169), `schedule` (~316, `return await self.add_job(...)`
  at ~403), `run_in` (~405), `run_once` (~454), `run_every` (~509), `run_minutely` (~562),
  `run_hourly` (~613), `run_daily` (~664), `run_cron` (~716).
- `add_job` is the ONLY scheduler method that needs body extraction — it does the real DB
  registration inline (`job.db_id` set before return). `schedule` and `run_*` are pure delegates.
- Existing internal awaiters: `src/hassette/core/state_proxy.py` (`await self.scheduler.run_every(...)`),
  `service_watcher.py`. Awaiting the handle is identical — verify they still pass.
- `cancel_job`, `cancel_group`, `list_jobs`, etc. are NOT in the protected set (not
  registration/fire-and-forget) — do not convert them.
- Do NOT change the `Coroutine[...]` annotation to `ScheduledJob`/`Awaitable`.

## Verify

- [ ] FR#3: `await self.scheduler.run_in(...)` / `schedule(...)` / `add_job(...)` returns a `ScheduledJob` with `db_id` set, exactly as today.
- [ ] FR#9: `add_job`, `schedule`, and all `run_*` methods are converted to `def -> Coroutine[...]`; no public scheduling method remains `async def`; the single `guard_await` is at `add_job`.
- [ ] FR#10: a forgotten `await` on `run_in` (a two-hop delegate) emits the same `HassetteForgottenAwaitWarning` as `add_job`, attributed to the user's call site.
- [ ] AC#2: a test awaits a converted scheduler method, asserts the returned `ScheduledJob` and `db_id`, and asserts no `HassetteForgottenAwaitWarning` (nor native inner-coroutine warning) fires.
