# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A task that swallows cancellation at exit doesn't trigger the hard exit

Status: open
Recorded: 2026-10-23 (3104)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/core.py
- src/hassette/server.py

Issue:
A `TaskBucket` task that swallows `CancelledError` outlives its cancel stage and is reported as
`TASKS_PENDING`/`SERVE_TASK_PENDING`, but nothing records it as force-terminated work. The hard exit
doesn't fire, and `asyncio.run()`'s final cancel-and-await waits on the task until the supervisor kills
the process, after the snapshot has been written.

Why deferred:
Rare, loses no data, and the fix would widen D19's ratified hard-exit trigger.

Recommended follow-up:
If supervisor-killed exits show up, add the merged root report's `pending_tasks` to
`record_force_terminated()` after the foundation stage, or switch the trigger to "what is still alive".

Acceptance criteria:
- A task that swallows cancellation at exit ends in a hard exit, not a supervisor kill.

## KI-002: A runtime stop in flight when exit begins is outside both deadline owners

Status: open
Recorded: 2026-10-23 (3104)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_start_stop.py
- src/hassette/core/app_handler.py

Issue:
A runtime stop or reload unregisters its instances before stopping them, so exit's `shutdown_all()` and
`AppHandler._force_terminal()` never see them. If exit finishes before that stop's own entry deadline,
nothing records it, and `asyncio.run()` can wait on a cancellation-swallowing hook that is now running
against services the stop stage already shut down.

Why deferred:
Needs a SIGTERM during a stop of an app with a cancellation-swallowing hook; the fix adds cross-component
tracking state to `AppLifecycleService`.

Recommended follow-up:
If hung exits appear after reload-heavy sessions, track in-flight runtime stop tasks and tighten them to
the stop stage's deadline at exit.

Acceptance criteria:
- A runtime stop in flight at SIGTERM is bounded by the stop stage and recorded if walked away from.

## KI-003: `restart()` and the service watcher shut down with no deadline owner

Status: open
Recorded: 2026-10-23 (3104)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/resources/operations.py
- src/hassette/resources/lifecycle.py

Issue:
The shutdown coordinator no longer bounds itself, and `restart()` sets no deadline before calling
`shutdown()`. A restarted framework service whose shutdown hangs (or a foundation service, whose hooks are
unbounded without a deadline) blocks the watcher's restart indefinitely with no log.

Why deferred:
Framework services only, rare, and milestone D17 deletes in-process restarts; a fix would be throwaway.

Recommended follow-up:
Delete the path with D17. If D17 slips out of the milestone, give `restart()` an entry deadline and a
walk-away.

Acceptance criteria:
- No supervised restart can wait on a shutdown without a bound.

## KI-004: A full-cap foundation stage ends in its own walk-away

Status: open
Recorded: 2026-10-23 (3104)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/config/models.py
- src/hassette/core/core.py

Issue:
`FOUNDATION_SHUTDOWN_BUDGET_SECONDS` is exactly the sum of the finalize, drain and join caps, leaving no
room for task-cancel, `cleanup()` or `close_connections`. When the finalize and the drain both hit their
caps, the stage logs a "gave up" ERROR and the process hard-exits.

Why deferred:
Takes two simultaneous failures (a busy SQLite file and stuck executor threads); the outcome is an extra
ERROR and a hard exit, not data loss.

Recommended follow-up:
If slow-storage installs hit the drain cap routinely, add a small fixed slack to the foundation budget.

Acceptance criteria:
- A finalize and drain that both run to their caps still let the join and cleanup finish inside the stage.

## KI-005: A shutdown hook that blocks the event loop loses the session's fatal reason

Status: open
Recorded: 2026-10-23 (3104)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/core.py

Issue:
The session finalize now runs in the foundation stage, after the stop stage. A synchronous blocking call
in a shutdown hook stops every timer, the supervisor kills the process, and the session row never gets its
final status, drop counters or fatal reason. The orphan detector marks the row on the next start.

Why deferred:
D19 already accepts that a loop-blocking hook defeats every deadline; covering it would need a second,
provisional session write at shutdown start.

Recommended follow-up:
If the session row's fatal reason is relied on to diagnose crash loops, write it and a provisional status
when shutdown starts.

Acceptance criteria:
- A process killed during a blocked stop stage leaves its fatal reason in the session row.

## KI-006: Stop-stage expiry skips LoggingService's flush

Status: open
Recorded: 2026-10-23 (3104)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/core.py
- src/hassette/core/logging_service.py

Issue:
When a hung app uses up the stop stage, later waves are force-terminated without running their hooks.
D19 accepts this for bus and scheduler teardown; it also skips `LoggingService.on_shutdown`, so the last
log records (possibly the stage-expiry ERROR itself) may not reach the database log table. stdout still has
them.

Why deferred:
A fix reserves part of the stop stage per wave, close to the per-wave allocation this change removed, and
reopens D19's accepted starvation.

Recommended follow-up:
If the web UI's log view becomes the main post-mortem tool for hung shutdowns, give the app wave an earlier
deadline than the stage so later waves keep a floor.

Acceptance criteria:
- After a stop-stage expiry, the stage-expiry ERROR appears in the persisted log table.
