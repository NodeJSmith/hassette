# REVIEW.md — scheduler/

## Collision Field Coverage
Bus and scheduler both use `if_exists` collision policies (`error`/`skip`/
`replace`). Does `Job.matches()` in `src/hassette/scheduler/classes.py` cover
every logical constructor/options field for jobs (trigger, group, jitter, args,
predicate), and does it stay aligned with `Job.diff_fields()`? On the bus side
both methods derive from `_CONFIG_MATCH_FIELDS` in
`src/hassette/bus/listeners.py` — does that table list every logical listener
option, or was a new option added without an entry?

## EntityTime Registration-to-Listener Gap
`_add_job_and_watch_entity()` in `src/hassette/scheduler/scheduler.py` registers
the job, then creates a state-change listener, then re-reads the entity to close
the window. If the entity changes during the re-read and produces a `WAITING`
result while the job is already `SCHEDULED`, does `reschedule_job()` correctly
remove the heap entry?

## Removal Callback Identity Check
`Scheduler._on_job_removed()` in `src/hassette/scheduler/scheduler.py`
identity-checks `self._jobs_by_name.get(job.name) is job` before popping, to
handle crash-restart orphans. Does the bus `_on_listener_removed()` in
`src/hassette/bus/bus.py` apply the same identity check, or does it pop
unconditionally by natural key?

## Execution Guard Drain Parity
The bus releases guards via `Listener.cancel()` → `invoker.release_guard()` in
`src/hassette/bus/listeners.py`. The scheduler releases guards in
`SchedulerService.remove_job()` / `_remove_jobs()` in
`src/hassette/core/scheduler_service.py`. Do both paths drain `pending_done`
futures after releasing the guard (via `release_and_drain` from
`src/hassette/execution_mode.py`), or does one subsystem skip the drain?
