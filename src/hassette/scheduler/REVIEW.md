# REVIEW.md — scheduler/

## Collision Parity with Bus
Bus uses `_resolve_collision()` in `src/hassette/bus/bus.py` with `if_exists`
supporting `error`/`skip`/`replace`. Scheduler uses `_add_job()` in
`src/hassette/scheduler/scheduler.py` with the same three policies. Does
`Job.matches()` in `src/hassette/scheduler/classes.py` compare the same set of
configuration fields as `Listener.config_matches()` in
`src/hassette/bus/listeners.py`, or has one grown new fields the other missed?

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
futures after releasing the guard (via `drain_pending_done` from
`src/hassette/execution_mode.py`), or does one subsystem skip the drain?
