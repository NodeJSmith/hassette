# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: The exit watchdog can block in logging before it reaches `os._exit`

Status: open
Recorded: 2026-10-29 (3395)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/server.py

Issue:
`start_exit_watchdog()`'s `watch()` logs an ERROR, each live thread's stack, then runs `hard_exit()`, which calls `logging.shutdown()` before `os._exit`. After LoggingService shuts down, these are synchronous writes to stdout. When the stdout reader stalls, a write blocks and `os._exit` never runs. `watch()` also has no `try/finally`, so an exception escaping it would end the thread silently. The second-Ctrl+C path logs before its `os._exit(1)` the same way.

Why deferred:
It takes a stuck exit and a blocked log sink together. When it bites, the process hangs until the supervisor's kill, which is how exit behaved before this change.

Recommended follow-up:
If a stalled log pipe at exit is ever seen (the add-on's s6, a Docker log driver), wrap `watch()` in `try/finally: os._exit(code)` and run `hard_exit()`'s logging on a helper thread joined for about 1s before an unconditional `os._exit`.

Acceptance criteria:
- An exit_child scenario whose log sink blocks still ends by the watchdog within its deadline plus the join bound.

## KI-002: A task spawned during the exit cancellation is neither cancelled nor named

Status: open
Recorded: 2026-10-29 (3395)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/server.py

Issue:
`cancel_remaining_tasks()` cancels one snapshot of `asyncio.all_tasks()`. A task created by another task's cancellation cleanup is not in it. If that task then ignores cancellation, only the watchdog ends the process, and the log shows the main thread blocked in a gather instead of the task's name.

Why deferred:
It takes two coincidences, the process still ends about 1s later, and only the diagnostic is lost. HA core's final cancel also takes a single snapshot.

Recommended follow-up:
If user apps are seen spawning follow-up tasks from cleanup, re-snapshot `all_tasks()` after each wait and cancel newcomers until none appear or the deadline passes.

Acceptance criteria:
- An exit_child scenario whose cancellation cleanup spawns a swallowing task names that task in the task half's ERROR.

## KI-003: On a loop stalled past the deadline, the watchdog can exit before survivors are named

Status: open
Recorded: 2026-10-29 (3395)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/server.py

Issue:
The task half names survivors only after `asyncio.wait` returns. A synchronous callback that blocks the loop for more than `EXIT_WATCHDOG_MARGIN_SECONDS` (1s) at the deadline lets the watchdog fire first, so a surviving task shows only as the main thread's stack, and nothing orders the two hard exits.

Why deferred:
The watchdog's main-thread stack shows the stall, which is the more useful diagnostic, and a wider margin would only move the threshold while shrinking D4's grace margin.

Recommended follow-up:
If exit-time loop stalls of a known, bounded length show up, widen the margin and update D4 and the operating docs.

Acceptance criteria:
- A stalled-loop scenario of the stated length names the surviving task before the watchdog fires.

## KI-004: The wire `pending_tasks` docstring names a core-owned task-name format

Status: open
Recorded: 2026-10-29 (3395)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- wire/src/hassette_wire/apps.py
- src/hassette/resources/lifecycle.py

Issue:
`NeedsRestart.pending_tasks` documents its entries as including `resource:initialize:<unique name>`, a literal in core's `lifecycle.py`. A rename in core leaves the released wire docs and the generated schemas stale, and no check catches it.

Why deferred:
D1 made the format deliberately greppable, so documenting it helps users, and no rename is planned.

Recommended follow-up:
If the initializer task's name changes, update the wire docstring and regenerate the schemas, or reword it to describe entries as opaque display labels.

Acceptance criteria:
- The wire docstring matches the task name core produces, or promises no format.
