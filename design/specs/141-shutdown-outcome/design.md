# Design: Shutdown Outcome

**Date:** 2026-10-28
**Status:** ratified
**Mode:** sketch
**Issues:** #3395
**Parent:** design/specs/134-resource-lifecycle-outcomes/design.md

## Summary

`TeardownReport` (`src/hassette/resources/teardown.py`) is an evidence tree: the `TeardownCause` vocabulary
plus `failed_operations`, `pending_tasks` and `affected_resources`, merged up the resource tree.
After spec 134, its readers want three things. They want whether work may still be running, read through
`is_restart_safe` by the coordinator's re-init guard (`resources/lifecycle.py`), by child propagation in
`shutdown_batch()` (`resources/operations.py`) and by the app settle paths
(`core/app_lifecycle_instances.py`). They want whether a hook timed out (`SHUTDOWN_HOOK_TIMED_OUT`, read once
in `shutdown_instance()` to word a timed-out stop). They want the names of what is still running
(`pending_tasks`, used for the needs-restart record and its reason). The rest of the tree only feeds
`RestartRefusedError`'s message (`exceptions.py`). Peers keep a small outcome instead: systemd `Result=`,
HA `ConfigEntryState` plus a reason, OTP exit reasons. The peer survey is
`design/research/2026-10-28-needs-restart-convergences/prior-art.md`, called "the brief" below.

Separately, `hassette run` hard-exits only when `Hassette.force_terminated_work` (`core/core.py`), a list kept
by hand, is non-empty. It misses a flagged instance's pending tasks when no deadline owner walked away from
them, and it can name work that finished long ago. Both are recorded as KI-007 in
`design/specs/138-needs-restart-flag/known-issues.md`; the second was spec 134's sketch-challenge F7, called "F7"
below. No peer keeps such a list. They derive survivors from live tasks and threads at exit.

This change does two things:

- **Shutdown outcome.** It replaces the report with a small outcome (D1, D2) in the renamed module (D5).
  Every producer is reworked onto it:
  - the coordinator;
  - `shutdown_hook_report()`, `shutdown_batch()` and `finalize_shutdown_report()`;
  - `Resource`'s and `Service`'s shutdown bodies, and `_force_terminal()` (`resources/base.py`, `resources/service.py`);
  - the root's stages and `AppHandler`.

  Every consumer is reworked too:
  - the re-init guard, the settle paths and `describe_left_running()`;
  - `RestartRefusedError` and its docstring;
  - the docstring of the wire's `NeedsRestart.pending_tasks` (D5). The OpenAPI description changes with it, so the
    schemas and frontend types are regenerated; the field and its type are unchanged;
  - `testing/_reset.py` and the needs-restart record in `core/app_registry.py`.

  The renamed property and its backing attribute live where the report's do now, on `LifecycleMixin`
  (`resources/mixins.py`). Every annotation and docstring naming the old types or causes is updated too. That
  includes `core/app_lifecycle_start_stop.py`, the `cleanup` docstrings in `app/app.py`, `cache/wrapper.py` and
  `core/database_service.py`, and `resources/REVIEW.md`.
- **Exit trigger.** It replaces the recorded list with a bounded live check (D3, D4). Its parts are:
  - the exit function that `hassette run` calls after `main()` (D3), holding the task half;
  - the exit watchdog thread that the exit function starts before the task half;
  - the `hassette run` command (`cli/commands/run.py`), which calls the exit function after `main()`;
  - the exit budget's constants and deadline (D4).

  All but the command live in `server.py`. `force_terminated_work`, `record_force_terminated()` and their four write
  sites go. Those sites are the root's `_run_stage()` and `_run_foundation_stage()`,
  `AppLifecycleService.walk_away_from_instance()` and `AppHandler._force_terminal()`. Each site's ERROR log stays:
  in embedded and harness runs they are the only signal, since the exit check runs only on `hassette run`.

Names follow D5. Docs that describe the report, its causes or the hard-exit trigger are updated:
- the lifecycle internals page (`docs/pages/core-concepts/internals/lifecycle.md`) and its two teardown snippets;
- the operating docs' hard-exit paragraph (`docs/pages/operating/index.md`);
- `.claude/rules/resource-lifecycle.md` ("Teardown reports", "Shutdown deadlines");
- `src/hassette/core/REVIEW.md`'s `record_force_terminated()` question.

Spec 134's ledger gets an addendum entry. It records the changed D19 trigger, the replaced D18 cause
vocabulary, the narrowed D5/D15 timed-out wording (D1), and the reason this ledger supersedes them.

Out of scope: treating a stray `CancelledError` from a user hook as a hook failure (the brief's Pattern 2), and
the separately filed lifecycle cleanups (#3112, #3113, #3114).

## Posture

- **Failure handling:** loud, as the parent's. A survivor at exit gets one ERROR per kind of survivor (tasks, threads) naming them, and the process then
  hard-exits. When exit is stuck past the budget, the process ending wins over interpreter finalization. Nothing retries.
- **Compatibility:** break freely (pre-V1). `TeardownReport` and `TeardownCause` are exported from
  `hassette.resources` and documented, so a rename gets a changelog migration note. A change to the released
  wire's `NeedsRestart` follows the parent's "Applies to all" compat rule.
- **Scope:** minimal. Replace the type and the hard-exit trigger, and delete what that leaves unread; nothing else.
- **Rollout:** ship outright.
- **Hardening:** project defaults plus the parent's "no silent states" rule.
- **Altitude:** build; one pickup PR built in one session.

## Decisions

### D1: What shape replaces the evidence tree?

Supersedes parent D18's cause vocabulary, as amended by its addendum. Narrows parent D5's and D15's timed-out
wording: a stop whose hook timed out and whose evidence is also incomplete is `INCOMPLETE` and is not worded
"timed out". It is still FAILED and flagged. A walk-away at the entry deadline keeps its "timed out" wording,
because `shutdown_instance()` knows it force-terminated the instance.

**Deciding factor:** serve the three things readers branch on (may work still run, did a hook time out, what is
still running) with the fewest fields, and merge up the tree without losing what they need.

Each current cause maps to a group:

| Cause | Under A | Under B | Under C |
|---|---|---|---|
| Hook or cleanup raised; cleanup cut off at its bound | `FAILED` | `failed` | Kept as a cause |
| Hook cut off at its bound | `TIMED_OUT` | `timed_out` | Kept as a cause |
| Pending owned tasks, pending serve task | Their names in `still_running` | Same | Names in `pending_tasks` |
| Pending initializer | Its task's name in `still_running` | Same | Kept as a cause with no name |
| Body raised or was cancelled, coordinator raised, forced terminal, a child's shutdown raised, a child's shutdown timed out at a stage deadline | `INCOMPLETE` | `incomplete` | Kept as causes in the unsafe set |
| A child that is unsafe | Arrives through the merge, with no cause of its own | Same | Kept as a cause |

| | A: Ranked result + still-running names | B: Independent flags | C: Trim the current report |
|---|---|---|---|
| Fields | `result` (`DONE` < `FAILED` < `TIMED_OUT` < `INCOMPLETE`), `still_running: tuple[str, ...]`, reason (D2) | `timed_out: bool`, `failed: bool`, `incomplete: bool`, `still_running`, reason (D2) | `causes` cut to about 6 values, plus `pending_tasks`; `failed_operations` and `affected_resources` go |
| Restart-safe predicate | `result is not INCOMPLETE and not still_running` | `not incomplete and not still_running` | As today, against a smaller unsafe set |
| Merge (parent of children, stage of waves) | Worst result wins; names are a deduplicated union | OR each flag; union names | Union causes and names |
| A hook timed out, and the evidence is also incomplete | `INCOMPLETE`: the stop still fails and is flagged, but its reason says "stopped, but…" instead of "stop timed out…" | Both flags kept; the wording says timed out | Both causes kept |
| Initializer pending | Named in `still_running`, so the reason can name it | Same | A cause with no name, as today |
| Matches | systemd `Result=` (one value), HA `ConfigEntryState` | No peer; the brief's peers each carry one state | Today's design, smaller |
| What readers learn | One enum, one tuple | Three booleans whose combinations need rules | A cause vocabulary and a separate safe set, as today |

Under A, a teardown with nothing wrong but tasks still pending is `DONE` with a non-empty `still_running`, and it is
not restart-safe.

Behavior to pin:
- every current cause gives the same restart-safe verdict as today;
- a `DONE` result with a non-empty `still_running` is not restart-safe.

**Recommendation:** A, because it is the peer shape and every branch a reader takes today is a comparison on one
field. The single loss is the wording of a stop whose hook timed out and whose evidence is also incomplete, and that
stop is still reported FAILED and flagged.
**Pick B instead if** a stop that both timed out and lost its evidence must still say "timed out".
**Pick C instead if** the cause names are worth keeping for diagnosis beyond what the logs already carry.
**Reversibility:** easy (internal type; the public rename is D5's)
**Ratified:** Chose a ranked result (`DONE` < `FAILED` < `TIMED_OUT` < `INCOMPLETE`) plus still-running names over independent flags or a trimmed cause set, to match systemd/HA and make every reader's branch one comparison, accepting that a stop whose hook timed out and whose evidence is also incomplete is worded "stopped, but…" rather than "timed out". At the sketch challenge (Finding 13), chose to list a pending initializer by its raw task name (`resource:initialize:<unique_name>`) over a reworded phrase, keeping `still_running` a uniform, greppable list of task names, accepting that the UI and the reason show that internal label. At the build's pre-commit review, chose to rank a `cleanup()` cut off at its bound `FAILED` rather than `TIMED_OUT`, keeping main's behavior that a slow `cleanup()` alone leaves an app stop STOPPED (on main only `SHUTDOWN_HOOK_TIMED_OUT` made a stop time out), accepting that `TIMED_OUT` now means only a shutdown hook cut off at its bound.

### D2: Does the outcome carry a reason, and in what form?

**Deciding factor:** a needs-restart reason and a `RestartRefusedError` that say what happened without the
reader opening the logs, at the cost of the fewest fields.

When nothing is pending and nothing was force-terminated, today's reason for an incomplete teardown is generic: "its
teardown evidence is incomplete, so work may still be running" (`describe_left_running()`). The cause tree records
*which* resource and step, but only `RestartRefusedError` prints it, as raw cause names. Under R1 the reason is also
the one source for what forced a teardown, so `describe_left_running()` drops its `force_terminated` parameter.

| | R1: One reason string for the worst result | R2: Every reason, as a tuple | R3: No reason field |
|---|---|---|---|
| Field | `reason: str \| None`, e.g. "Bus shutdown body raised", "on_shutdown of MyApp timed out" | `reasons: tuple[str, ...]` | none |
| Merge | Keep the first reason recorded at the merged (worst) rank | Union, deduplicated | n/a: nothing to merge |
| Needs-restart reason for an incomplete teardown | Names the resource and step: "MyApp's shutdown body raised; work may still be running" | Names all of them, which can be long | Stays generic |
| `RestartRefusedError` message | Result, names and the reason | Result, names and every reason | Result and names only |
| Matches | HA's one `reason` per entry, systemd's one `Result=` | No peer | OTP's bare exit atom |

**Recommendation:** R1, because one string at the worst rank is what a peer carries and it turns the generic
"evidence is incomplete" into the resource and step that caused it. Lesser problems stay in the logs, which
already name them.
**Pick R2 instead if** a refused restart's message should list every problem the teardown hit.
**Pick R3 instead if** the generic wording is enough and the logs are the place to look.
**Reversibility:** easy
**Ratified:** Chose one reason string for the worst result (first recorded at that rank wins) over every reason or none, to name the resource and step behind an incomplete teardown as HA's single reason does, accepting that lesser problems are only in the logs. At the sketch challenge (Finding 7), `describe_left_running()` lost its `force_terminated` parameter: the outcome's reason is the one source for what forced a teardown. Also accepted there (Finding 12): when several siblings end `INCOMPLETE`, the reason names the first in child order, and the others are in the logs.

### D3: What triggers the hard exit at the end of `hassette run`?

Supersedes parent D19's "Process exit" trigger: "when a stage or entry deadline force-terminated something…, or
when executor threads survived the foundation stage's join". The rest of that bullet carries over (Assumed).

**Deciding factor:** stop at exit exactly when something would otherwise hold the process. Judge it at the moment
of exit, where each kind of work can actually be seen, with no list kept by hand.

| | H: Live task check plus one exit watchdog for everything else, in an exit function after `main()` | L: Live check, tasks in `main()`, threads at interpreter exit | L′: Live check, tasks and threads both in `main()` | P: Live check, tasks in `main()`, only framework pools' threads | W: Keep the list, add a fifth writer | S: No hard exit |
|---|---|---|---|---|---|---|
| Task rule | Same as L, with the watchdog started first | After `run_forever()` ends and the snapshot wait (Assumed), cancel every other live task on the loop and poll with `asyncio.sleep` until they finish or D4's budget runs out. A task still alive then is a survivor. A task that finishes within the budget after being cancelled is not a survivor and logs nothing above DEBUG. Survivors are named in one ERROR, and so is the run's error when `run_forever()` raised. Logs are then flushed and `os._exit` runs with the mapped exit code, because `asyncio.run()`'s own cancel-and-gather would otherwise wait on them forever | Same as L | Same as L | As today, plus `flag_instance_needs_restart()` records the flagged instance's pending task names | n/a: the hard exit is deleted, and the supervisor's kill is the backstop |
| Thread rule | After the snapshot wait, before the task half, the exit function (below) starts one daemon watchdog thread, on the path where `run_forever()` raised as well as the one where it returned. Its closure holds D4's deadline and the run's mapped exit code. If the process is still alive when the watchdog's time comes (D4), it logs one ERROR naming every live thread, with each one's stack (the main thread's included, which shows where a frozen loop is blocked) logged through `_log_thread_running_at_shutdown()`. It then flushes logs and calls `os._exit` with the mapped exit code. Otherwise the process exits normally: `asyncio.run()`'s own executor shutdown, the interpreter's thread join and the atexit handlers run as CPython does them, and the watchdog bounds their sum. Threads are never judged one by one, so nothing decides which threads count. The default executor and `threading._shutdown` stay stock | `main()` makes hassette's `InterruptibleThreadPoolExecutor` (`task_bucket/interruptible_executor.py`) the loop's default executor. After the task half, it shuts the pool down itself with `timeout` set to what is left of D4's budget; that join interrupts stuck workers. `asyncio.run()`'s later `shutdown_default_executor()` then finds the pool already shut down, so the executor's `shutdown()` waits for and interrupts nothing on a second call. Before returning, `main()` replaces `threading._shutdown`, the interpreter-exit join, with a bounded version, as in HA's `deadlock_safe_shutdown()`. Unlike HA's, it first runs the registered threading-atexit callbacks (`threading._threading_atexits`, in reverse order, as CPython's own `_shutdown` does) on a daemon helper thread, waiting for that helper only for what is left of D4's budget. This lets `concurrent.futures`' `_python_exit` wake the idle workers of pools nobody shut down, while its unbounded joins can't hold exit. It then joins every live non-daemon thread other than the main thread within what is left of the budget. Threads still alive afterwards are named in one ERROR, with each one's stack logged through `_log_thread_running_at_shutdown()`. They are not interrupted. The join then returns, so the interpreter finishes exiting with the mapped exit code; threads never need `os._exit`. The replacement is not restored, since `hassette run` calls `main()` once per process | Shut down the default executor and join non-daemon threads inside `main()`, then hard-exit on any survivor | Same executor swap and in-`main()` shutdown as L; hard-exit only when the default executor's or the sync executor's workers survive. Other threads aren't judged | As today | n/a: no check runs |
| Flagged instance's swallowing task (KI-007) | Same as L | Cancelled again, survives the budget, hard exit | Same | Same | Recorded, hard exit | Holds the process until the kill |
| Work that finished before exit (F7) | Same as L | Not alive, so no hard exit | Same | Same | Still recorded, hard exit with a stale name | n/a: no check runs |
| Leaked work nothing recorded (a handler task, a thread a user started) | Caught: a task is cut by the hard exit; a stuck thread is named with its stack by the watchdog, then `os._exit` | Caught: a task is cut by the hard exit; a thread gets the bounded join, then the interpreter exits | Caught | Tasks caught; user threads hold the process until the kill | Missed | Holds the process |
| Idle AnyIO workers (Starlette's `StaticFiles`/`FileResponse`), idle stdlib pools nobody shut down | Stopped before the deadline (AnyIO's by the root task's done-callback, idle stdlib pools by CPython's `_python_exit`), so the watchdog never fires (probe) | Never judged (Assumed) | AnyIO workers are false survivors on every exit after the UI served a file | Not judged | Not seen | n/a: no check runs |
| Stuck default-executor worker on 3.11 | Bounded by the watchdog (probe) | Bounded by the interruptible executor's shutdown (Assumed) | `shutdown_default_executor()` joins without a timeout and blocks the loop | Bounded, as L | Holds the process | Holds the process |
| Loop frozen by a blocking call in cancellation cleanup; an atexit handler that hangs | Bounded by the watchdog; the main thread's stack names the blocking call (probe) | Holds the process until the kill (probe) | Same as L | Same as L | Same as L | Same as L |
| User atexit handlers when a thread is stuck past the deadline | Skipped by `os._exit` (probe) | Run after the bounded join (probe) | Skipped by `os._exit` | Hold with the thread | Hold with the thread | Hold with the thread |
| A framework task that outlives a clean shutdown | Same as L | Cancelled and waited for; hard exit only if it survives, with the exit code unchanged and one ERROR naming it | Same | Same | Not seen | n/a: no check runs |
| State kept | The deadline and the exit code, in the watchdog's closure | The budget's deadline, one module-level value in `server.py` that `main()` sets and the `_shutdown` replacement reads, plus the patched private `threading._shutdown`, both only on the `hassette run` path | The deadline only | The deadline only | A list on `Hassette` and five write sites | None |
| Private CPython internals | None | `threading._shutdown`, `threading._threading_atexits`, and `_shutdown`'s main-thread bookkeeping, which differs between 3.11 and 3.14 | None | None | None | None |
| Matches | Task half as HA (the brief, Pattern 4). The thread half moves a supervisor's stop timeout and kill (systemd `TimeoutStopSec=`, Docker's stop grace; the brief, Pattern 5) inside the process, so the ERROR is written first. It leaves HA's `deadlock_safe_shutdown()` | HA: `runner.py` sets an `InterruptibleThreadPoolExecutor` as the default executor and replaces `threading._shutdown` with `deadlock_safe_shutdown()` (`util/thread.py`); its task wait is on the loop (the brief, Pattern 4) | No peer judges threads inside the main coroutine | Partly HA | No peer (the brief, anti-patterns) | systemd, Docker, Celery (the brief, Pattern 5) |

The snapshot wait, the watchdog and the task half are one exit function in `server.py`. Only the `hassette run`
path (`cli/commands/run.py`, inside its `asyncio.run()`) calls it, after `main()` ends on either path. `main()` itself
never cancels tasks or arms the watchdog, because unit tests call it in-process on the session-scoped loop, where
either would hit the whole xdist worker. How `main()` hands the core and the run's error to the exit function is a
build call. The real exit is proven by the subprocess pin (re-challenge, Finding 3).

"Probe" rows were observed by `exit-probe/run.py` (beside this ledger) on CPython 3.11.15 and 3.14.5, with identical
results on both. It models today's exit, L, and H's watchdog without its task half (its `W` column), in a subprocess per scenario; `exit-probe/out.txt` is the run.

Embedded and test-harness loops never run either half (Assumed).

Behavior to pin:
- a pending task left by a flagged instance either finishes within the budget or triggers the hard exit;
- work that finished before exit doesn't trigger it;
- a non-daemon thread still alive when the watchdog fires is named with its stack, and the process exits by
  `os._exit` with the mapped code: 0 after a clean stop, 1 when `run_forever()` raised a `FatalError` (re-challenge,
  Finding 4);
- daemon threads, idle AnyIO workers and idle workers of a stdlib `ThreadPoolExecutor` nobody shut down never make
  the watchdog fire, and a stuck worker in such a pool is named without holding exit past the watchdog's time (D4);
- a loop frozen by a blocking call in cancellation cleanup, and an atexit handler that hangs, end by the watchdog
  with the main thread's stack logged;
- a task survivor is named by the task half's ERROR, not only by the watchdog's thread list;
- the shutdown snapshot is waited for, not cancelled;
- a task that takes about 1s to finish its cancellation exits 0 with no ERROR;
- the hard exit and the watchdog behave as above at a real process exit, on every supported Python (sketch
  challenge, Finding 14);
- a force-terminated descendant makes the root's outcome `INCOMPLETE`. In the harness, where the check never runs, that
  is the observable that replaces `force_terminated_work` being empty. Tests that asserted a specific name in it,
  including `test_core_coverage.py`'s surviving `hassette-sync_0` thread, assert the stage's ERROR log instead
  (re-challenge, Finding 8, restoring the sketch challenge's Finding 6 resolution).

**Recommendation:** H, because it answers KI-007 and F7 at once and deletes the list like L, and one owner bounds
every wait after the task half, including the frozen loop and hung atexit handler L leaves to the kill, with no
private CPython hooks. L doesn't keep finalization either: it already `os._exit`s on a surviving task.
**Pick L instead if** running the user's atexit handlers when a thread is stuck matters more than bounding a frozen
loop or hung atexit, and the per-version `threading._shutdown` mirroring is acceptable. **Pick a watchdog with no
task half instead if** one exit path matters more than naming surviving tasks: the watchdog alone sees only threads,
so a swallowing task shows up as the main thread idling (probe). **Pick L′ instead if** threads must be judged by name inside `main()`, with a thread-identity filter for idle pool
workers, rather than by whether the process actually exits. **Pick P instead if** only framework pools' threads should
ever trigger the hard exit, and leaving user and AnyIO threads to the supervisor is fine. **Pick W instead if** the exit path must stay as D19 ratified it, with only the
known gap closed. **Pick S instead if** `hassette run` always runs under a supervisor with a kill timeout, and an
unsupervised terminal run hanging until Ctrl+C is acceptable.
**Reversibility:** easy (local to `server.py`'s exit path and the `hassette run` startup)
**Ratified:** Chose a bounded live check of tasks and non-daemon threads at exit over keeping the recorded list with a fifth writer or dropping the hard exit, to close KI-007 and F7 the way HA does and delete the list, accepting that a framework task outliving a clean shutdown would hard-exit with an ERROR. At the sketch challenge (Finding 1, converging Findings 2, 4 and 9), chose L, HA's placement of the thread half (an interruptible default executor plus a bounded `threading._shutdown` join that logs survivors and lets the interpreter exit), over P (framework pools only) or dropping the thread half. It accepts patching a private CPython hook on the `hassette run` path, and that a user's non-daemon thread still running after the join is abandoned at interpreter exit, with an ERROR and the mapped exit code, as in HA. At Finding 3, it also accepts that a cancelled task whose cleanup makes a blocking sync call freezes the loop. The task budget then never runs out, and the supervisor's kill is the backstop, as D19 already accepts for a hook that blocks the loop. It also accepts (Finding 10) that when LoggingService's shutdown was abandoned, the survivor ERROR may be lost to the logging queue before `os._exit`. Re-ratified after the challenge, including the auto-applied pins from Findings 5, 6 and 8 and Finding 14's real-surface proof. Before the re-challenge, chose to have the `threading._shutdown` replacement run the registered threading-atexit callbacks on a daemon helper bounded by the remaining budget, over skipping them as HA does (idle un-shut stdlib pools would be false survivors on every exit) or running them inline (`_python_exit`'s unbounded join would hang exit on a stuck worker), accepting one helper thread and a read of the private `threading._threading_atexits`. At the re-challenge (Finding 1, converging Findings 2, 5, 6, 7, 9 and 12), after a subprocess probe of H, L and today's exit on 3.11 and 3.14 (`exit-probe/`), ratified the rule that settles this axis: when exit is stuck past the budget, hassette guarantees the process ends, not that interpreter finalization runs. So chose H, a single daemon watchdog that names every live thread with its stack and `os._exit`s with the mapped code, over L's thread half, keeping L's task half to name surviving tasks. This supersedes the thread-half choices above (the interruptible default executor, the `threading._shutdown` replacement and its atexit helper), and with them the frozen-loop limitation accepted at Finding 3. It accepts that when a thread is stuck past the deadline the user's atexit handlers don't run, as under the supervisor's kill, and that the thread half no longer matches HA's `deadlock_safe_shutdown()`. Finding 10's lost-ERROR limitation still holds for the watchdog's line. Earlier rounds flipped on this axis because each settled the objection in front of it (false survivors, user-thread cleanup, private hooks) without this rule; a later challenge that would reopen it should argue against the rule. Also at the re-challenge: the exit step moved out of `main()` into an exit function only `hassette run` calls (Finding 3), the watchdog is armed on the raise path too (Finding 4), and round 1's "assert the stage's ERROR log" pin was restored (Finding 8). It accepts (Finding 11) that a sync worker the foundation stage already found stuck makes that exit wait for the watchdog, up to about 6s, and logs its stack twice, over passing the stage's findings to the exit step.

### D4: How long does the exit check wait, and does the supervisor grace change?

**Deciding factor:** a bound short enough to fit the supervisor grace D19 sized, so the survivor ERROR gets
written before a kill, without a new setting.

D19 sized the Docker compose `stop_grace_period` at 60s: `total_shutdown_timeout_seconds` (45s) plus a 15s
snapshot allowance. Each wait in D3 waits only while something is still alive. A clean exit's tasks finish in one
loop turn, and its idle pool and AnyIO workers stop before the deadline (Assumed). Under D3's H, one deadline is set after the snapshot wait. The task
half polls until it, and the watchdog fires 1s after it (the watchdog margin, a code constant in `server.py` beside the budget), so that a surviving
task is named by the task half's own ERROR before the watchdog, which sees only threads, could fire. Everything after
the task half (`asyncio.run()`'s executor shutdown, the interpreter's thread join, the atexit handlers) runs inside
that window, however many waits it takes.

| | F5: One 5s budget, grace stays 60s | F5′: 5s per wait, grace stays 60s | F5+: One 5s budget, grace rises to 66s | T: Reuse `task_cancellation_timeout_seconds` | N: New setting |
|---|---|---|---|---|---|
| Bound | One 5s exit budget (a code constant in `server.py`; 5s is HA's task timeout): one deadline, set after the snapshot wait, that the task half and the watchdog both read | 5s for the task wait and 5s more for the watchdog | Same as F5 | The `TaskBucket`-wide setting, reused | `exit_check_timeout_seconds` |
| Worst case with survivors | 45s + snapshot + 6s (the watchdog's 1s margin), which passes 60s only when the snapshot takes more than 9s | 45s + snapshot + 10s (the 5s task wait, then the watchdog's own 5s) | Covered | Depends on the setting | Depends on the setting |
| Cost of passing the grace | The kill lands before the survivor ERROR is written; the outcome is the same kill | Same as F5, far more often | n/a: within the grace | Same as F5 | Same as F5 |
| State | One deadline, held in the watchdog's closure and read by the task half (D3, State kept) | None | Same as F5 | Same as F5 | Same as F5 |
| Touches | The budget and margin constants | Two budget constants and the margin | The compose file, the Docker stop-grace test constant, the operating and add-on docs again | One reference | Config, schema, docs |
| Matches | HA's fixed constant | HA's per-wait constants (5s tasks, 10s threads) | HA | No peer found | No peer found |

**Recommendation:** F5, because it is one fixed budget like HA's and only a slow snapshot plus a survivor together
lose the ERROR line, while the process still exits by the kill.
**Pick F5′ instead if** the work after the task half needs its own full 5s even when the task half used the budget.
**Pick F5+ instead if** the survivor ERROR must always be written under Docker.
**Pick T instead if** one cancellation bound for the whole framework matters more than a fixed exit wait.
**Pick N instead if** operators need to tune it.
**Reversibility:** easy
**Ratified:** Chose a fixed 5s code constant with the 60s grace unchanged over a raised grace, the cancellation setting or a new setting, to match HA's fixed bound with one constant, accepting that a snapshot over 10s plus a survivor lets the supervisor's kill land before the survivor ERROR is written. When D3's thread half moved to interpreter exit (sketch challenge, Finding 1), the comb found two more waits after the task wait. Chose F5's one shared budget over F5′'s 5s per wait, to keep that margin, accepting one deadline value carried from `main()` across the `asyncio.run()` boundary. Reaffirmed at the sketch challenge (Finding 11): the check still waits for the snapshot before naming survivors, so a kill during a slow snapshot leaves no record of them. At the re-challenge, when D3 moved to H, the deadline moved into the watchdog's closure, so nothing crosses the `asyncio.run()` boundary as module state (Finding 7). The watchdog fires 1s after the deadline so a surviving task is named by the task half first; the threshold for a slow snapshot losing the ERROR moves from 10s to 9s.

### D5: What are the new names, and does the wire change?

**Deciding factor:** names that say what the type now is, with no wire churn a released client gains nothing from.

The wire's `NeedsRestart.pending_tasks` already means "names of the tasks still pending" (`wire/src/hassette_wire/apps.py`).
Under D1 it also carries a pending initializer's name.

| | K: Rename Python, keep the wire | A: Rename everything | O: Keep the old names |
|---|---|---|---|
| Type, enum, property | `ShutdownOutcome`, `ShutdownResult`, `resource.shutdown_outcome`; module `resources/shutdown_outcome.py` | Same | `TeardownReport`; `TeardownCause` becomes the result enum; `teardown_report` |
| Restart predicate | `is_restart_safe` stays (parent addendum, D18) | Same | Same |
| `RestartRefusedError` attribute | `.report` becomes `.outcome` | Same | `.report` |
| Wire `NeedsRestart.pending_tasks` | Unchanged; docstring mentions the initializer | Renamed `still_running`; OpenAPI diff and compat ignore entries, `MIN_API_SCHEMA_VERSION` and frontend types | Unchanged |
| Changelog | Migration note for the renamed exports and `RestartRefusedError.outcome` | Migration notes for the exports and the wire field | Migration note for `TeardownCause`'s changed values |
| Reader fit | "Outcome" matches what it is; "report" implied evidence | Same, plus a consistent wire name | Old name, new meaning |

**Recommendation:** K, because the type is no longer a report of evidence, and the wire field already says what
it carries, so renaming it buys a client nothing.
**Pick A instead if** the Python and wire names must match.
**Pick O instead if** the rename's churn across docs and about 20 test files outweighs a clearer name.
**Reversibility:** easy (pre-V1 names)
**Ratified:** Chose renaming the Python surface (`ShutdownOutcome`, `ShutdownResult`, `shutdown_outcome`) and keeping the wire's `pending_tasks` over renaming everything or nothing, to name what the type now is without wire churn, accepting a migration note and a Python/wire name mismatch. At the sketch challenge (Finding 7), `RestartRefusedError.report` was renamed to `.outcome` and added to the migration note, over keeping `.report` with the new type.

## Assumed

- Carried from parent D5 and D12: a hook that raised or timed out and has ended leaves the instance reloadable.
  A stop that timed out is FAILED with an `AppRegistry` failure entry, even when nothing is left running.
  Evidence: `settle_failed_stop()` (`core/app_lifecycle_instances.py`).
- Carried from parent D18 as amended by its 2026-10-27 and 2026-10-28 addendum entries: one restart-safety predicate named
  `is_restart_safe`. Work may still be running when tasks are pending or the evidence is incomplete. A shutdown
  body that raised or was cancelled counts as incomplete. Evidence: spec 134's Addendum; `TeardownReport.is_restart_safe`.
- Carried from parent D19: the snapshot is waited for before any hard exit. An exit whose only problem is abandoned
  work exits 0. Embedded and test-harness loops never hard-exit. Evidence: `exit_now_if_work_force_terminated()`
  (`server.py`), called only from `main()`.
- The exit function (D3) runs only under `hassette run`, via `asyncio.run()`, once per process. `main()` is also
  called in-process by about ten unit tests on the session-scoped loop, which is why the exit step lives outside it.
  Evidence: `cli/commands/run.py`; `tests/unit/core/test_server.py`; `pyproject.toml`
  (`asyncio_default_test_loop_scope = "session"`).
- The SIGINT wait thread, the logging `QueueListener` thread and aiosqlite's threads are daemon threads, so they
  never hold exit. Sync executor workers and AnyIO's worker threads are not daemon, but on a clean exit CPython and
  AnyIO stop them before the watchdog's deadline: the root task's done-callback stops AnyIO's workers, and
  `concurrent.futures`' `_python_exit`, run by `threading._shutdown`, wakes idle pool workers. Evidence: `server.py`
  (`daemon=True`), stdlib `QueueListener`, `utils/aiosqlite_utils.py`, `anyio/_backends/_asyncio.py` (`WorkerThread`,
  and `run_sync`'s `root_task.add_done_callback(worker.stop)`), `concurrent/futures/thread.py`, and `exit-probe/`'s
  `idle_anyio` and `idle_stdlib_pool` runs on 3.11.15 and 3.14.5. Which task is the root for the web server's calls is
  a library detail, so D3's real-exit pin is what proves it in hassette.
- Python 3.11 is supported, and its `loop.shutdown_default_executor()` ends in a `thread.join()` with no timeout,
  which blocks the loop if a worker is stuck. Under H the watchdog bounds it. Evidence: `pyproject.toml`
  `requires-python`; CPython 3.11 `asyncio/base_events.py` `shutdown_default_executor`; `exit-probe/`'s
  `stuck_default_executor` run.
- Nothing outside tests reads `force_terminated_work`. Evidence: grep of `src/`, where `server.py` is the only reader.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
- How `main()` hands the core and the run's error to the exit function (D3): `main()` is split into `create_core()` and `serve()`, and `hassette run` calls a new `run()` that serves, then calls `exit_after_run(core, exc)` on either path. Unit tests call `serve(create_core(...))` in-process, so nothing on their path runs the exit check, with no parameter that only one caller passes.
- The task half waits with `asyncio.wait(tasks, timeout=<remaining budget>)`, not a poll on `asyncio.sleep`: same deadline and same survivors, without the lint-flagged sleep loop.
- `ShutdownResult` is an `IntEnum`, so the merge's worst result is `max()`. `incomplete(reason, still_running)` builds the `INCOMPLETE` outcomes the producers record.
- Reason formats: a hook gives `"<unique_name>: shutdown hook <hook> timed out after <bound>"` (the `ShutdownHookTimedOutError` text) or `"<unique_name>: a shutdown hook raised <type>"`; `cleanup()` gives `"<unique_name>: cleanup() timed out after <s>"` or `"... raised <type>"`; the body, the coordinator and a child's raised `shutdown()` give `"<unique_name>'s shutdown body raised <type>"` (or `was cancelled`), `"... shutdown coordinator raised <type>"` and `"<child>'s shutdown raised <type>"`; a forced terminal gives `"<unique_name> was force-terminated"`; a stage walk-away adds `"<unique_name>: the shutdown <stage> stage gave up after its deadline passed"` after its children's outcomes, so a force-terminated child's reason wins.
- `describe_left_running()` takes only the outcome: an `INCOMPLETE` reason is followed by the still-running names, or "work may still be running" when there are none. The generic "teardown evidence is incomplete" wording remains only for a raised shutdown with no stored outcome.
- `RestartRefusedError`'s message is the result's name, then the reason, then the still-running names.
- The watchdog names every live thread, daemon threads included, since any of them can explain a stuck exit; each stack goes through `log_thread_running_at_shutdown()`, made public for this. The hung-atexit pin found that it printed the *caller's* stack for a thread with no Python frame (`traceback.format_stack(None)`); it now logs "(no Python frames)" for one.
- The real-exit pins run `tests/integration/exit_child.py` as a subprocess with a 0.5s budget; CI's per-Python `tests` sessions run them on every supported Python.
- Spec 138's KI-007 is marked resolved.
- `exit-probe/` keeps its code verbatim as D3's evidence; it carries file-level lint and pyright exemptions instead of edits.
