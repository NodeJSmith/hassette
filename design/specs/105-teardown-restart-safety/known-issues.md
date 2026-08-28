# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: `test_interruptible_executor.py` leaves the interpreter hung at exit outside xdist

Status: open
Run: 117
Source: T03
Reason not fixed now: out-of-scope
Observed in: T03 (full-suite test-gate re-run), reproduced independently on base_commit cb39d6af
Affected files:
- tests/unit/task_bucket/test_interruptible_executor.py
- tests/unit/conftest.py (`busy_loop_worker` / C-blocked-thread test helpers)

Issue:
`TestInterruptibleThreadPoolExecutorShutdown::test_shutdown_completes_within_timeout_for_c_blocked_thread`
deliberately proves that `InterruptibleThreadPoolExecutor` shutdown returns within its budget even
when a worker thread is blocked in C code and cannot be asynchronously interrupted
(`PyThreadState_SetAsyncExc` only fires at Python bytecode boundaries). The test passes, but the
real, non-daemon `ThreadPoolExecutor` worker thread it starts keeps running forever afterward —
this is definitionally the behavior under test, not a bug in the test's own assertions. When this
test file is invoked as the last (or only) work item in a non-xdist pytest process, the leftover
thread keeps the interpreter alive at shutdown. The repo's own diagnostic safety net
(`tests/system/conftest.py`'s `force_exit_if_stalled`, loaded because pytest walks that conftest
during collection) detects this after a 60s grace period, dumps thread tracebacks, and calls
`os._exit()` — but in the T03 re-run this either fired well past its own budget or the process
otherwise did not exit promptly; I killed it manually after ~13 minutes total.

Reproduction: `uv run pytest tests/unit/task_bucket/test_interruptible_executor.py -v -p no:randomly`
hangs (exit code 124 under a 60s external timeout) both on this branch and on base_commit
`cb39d6af` in an isolated worktree — confirmed via direct side-by-side reproduction, not inference.
This proves the underlying straggler-thread behavior is pre-existing, not introduced by T01-T03.

Why deferred:
This is test-infrastructure behavior, not a defect in Hassette's own lifecycle/teardown code —
the affected files are outside every task's Target Files list in this design (T01-T08), and
design.md's Non-Goals/Key Constraints explicitly exclude sync-executor-thread ownership and
termination proof from this PR's scope ("The report must not claim that sync executor threads or
arbitrary untracked tasks stopped"). Fixing it would mean redesigning this specific test's
straggler-thread handling (e.g., marking the pool's worker threads daemon for this test only, or
running this file in its own xdist-isolated process by default) — a change to test tooling
unrelated to the restart-safety design this PR implements. It did not block T03: the full-suite
FAILED-test evidence (11 failures, all in T04/T07-owned files) was captured from the verbose log
before the hang, and lint gates passed independently, so T03's actual regression-detection needs
were met without a clean full-suite exit.

Recommended follow-up:
File a separate issue to either (a) make this test's C-blocked-thread worker a daemon thread (if
that doesn't weaken what the test proves) or (b) confirm/harden `force_exit_if_stalled`'s
`os._exit()` path so a leftover straggler from this test can never block CI beyond the intended
60s+small-margin budget, and investigate why it apparently exceeded that budget by an order of
magnitude in this run.

Acceptance criteria:
- `uv run pytest tests/unit/task_bucket/test_interruptible_executor.py` exits cleanly within a few
  seconds of the last test completing, in isolation and as part of the full suite.
- `uv run nox -s dev` (or the CI-equivalent full-suite command) never requires manual process
  termination.

## KI-002: `test_service_watcher.py` cascades 474 pre-existing errors after its first shutdown test

Status: resolved (cascade eliminated; one confined failure remains — see KI-003)
Run: 117, fixed in commits 872e38ad, bc652d54, 618ac075
Source: T04
Observed in: T04 (full-`tests/integration/` test gate baseline, `1 failed, 884 passed, 1 skipped,
474 errors in 254.24s`), confirmed pre-existing on base_commit via a fix-and-revert investigation.

Issue (as originally observed):
`test_always_failing_service_stops_after_max_attempts` (later also
`test_permanent_exhaustion_triggers_shutdown`) calls `hassette.shutdown()` inline against a
module-scoped `Hassette` harness fixture shared by every other test in the file. Once that test
shuts the shared instance down, every subsequent test in `test_service_watcher.py` errored — the
same underlying mechanism as the single reported failure, just multiplied across the file (21
errors from this one file accounted for the bulk of the 474 total).

Root cause found and fixed (commit 872e38ad): yield-based async-generator harness fixtures had
their teardown resumed by pytest-asyncio creating a new `Task` on the shared session-scoped loop.
Once a test sealed the shared `TaskBucket` (via `hassette.shutdown()`), that `Task` creation was
rejected by the loop's still-installed bucket-routing task factory before the fixture's own
teardown or factory restore could run — poisoning every later test in the pytest-xdist worker,
regardless of file. Fixed by converting the affected fixtures (and the `watcher` fixture in
`test_service_watcher.py`) from `yield`-based teardown to `request.addfinalizer()`, mirroring the
existing `hassette_instance` pattern, plus suppressing a related cross-`contextvars.Context`
`ValueError` in `HassetteHarness.stop()`.

This also surfaced two further bugs along the way, each root-caused and fixed independently:
- The wrong patch target in `test_forces_all_children_terminal_when_super_shutdown_times_out`,
  which made that test hang rather than exercise the total-shutdown-timeout path it was meant to
  test (commit bc652d54) — a test bug, not a production defect.
- `Hassette._shutdown_children()` returning a plain `bool` instead of the `TeardownReport` every
  other `_shutdown_children()` override returns, causing
  `AttributeError: 'bool' object has no attribute 'restart_safety'` inside the shared
  `_run_post_hook_shutdown_stage()` (commit 618ac075).

Result: `tests/integration/test_service_watcher.py` full-file error count dropped from 21 to 19,
and the broader `tests/integration/` cascade dropped from 474 to 0 outside this one file — a
full-suite `nox -s dev` run now shows all remaining errors confined to
`test_service_watcher.py` itself. One failure remains in that file after all three fixes; see
KI-003 for why it's a distinct, still-open issue.

## KI-003: `CancelledError` race in the harness's `TaskBucket` routing during real shutdown

Status: resolved
Run: commit 618ac075 (discovered) → fixed in commits acc6c147, dccb7323
Source: T04 fixer dispatch

Issue (as originally observed):
`HassetteHarness.start()` installs a custom event-loop task factory
(`make_task_factory(self.hassette.task_bucket)`) that attributes every new task created via
`loop.create_task()` to the root `TaskBucket` when no `ctx.CURRENT_BUCKET` is set. pytest-asyncio
creates each test function's own top-level coroutine via `loop.create_task()`, so the test's own
task gets attributed to that same root bucket. When a test drives a real `hassette.shutdown()`,
`_run_task_bucket_shutdown_stage()` calls `TaskBucket.cancel_all()` on the root bucket, which
excludes only `asyncio.current_task()` at that call site (the dedicated shutdown-body/coordinator
task, which already bypasses the factory) — not the test's own, different task. The test's own
task is cancelled as a side effect, and its assertions never run. Triage (see below) found this
hits 6 tests in `test_service_watcher.py`, not just the 1 originally reported.

First fix attempt (reverted, not landed): a "scratch bucket" approach — give the harness's whole
module-scoped lifetime a detached `TaskBucket` via `context.CURRENT_BUCKET.set()`, so pytest-
asyncio's own task would land there instead of the root bucket. This worked for its narrow goal
but broke `tests/integration/test_task_bucket.py`'s "rogue task capture" contract (5 tests that
deliberately create a task with no bucket context and assert the harness's root bucket picks it
up via the factory's fallback-to-global default) — eliminating the ambient "no bucket claimed"
signal globally makes an intentional rogue-task test indistinguishable from pytest-asyncio's own
synthetic task creation. This is the same wall an earlier (pre-this-session) investigation
already hit and reverted from when KI-002 was first written.

Fix landed (commit acc6c147): a new `PROTECT_TASK` contextvar (`src/hassette/context.py`),
checked at task-*creation* time inside `make_task_factory()` — not at cancellation time
(`Task.get_context()`, which would allow that, requires Python 3.12+; this project supports
3.11+). If set, the factory returns the task without ever registering it in any bucket, so no
`cancel_all()` anywhere can touch it. Because this changes creation-time exclusion rather than
the `CURRENT_BUCKET` fallback default, it cannot conflict with `test_task_bucket.py`'s rogue-task
tests (verified unaffected, still 12/12). `test_service_watcher.py`'s `watcher` fixture (commit
dccb7323) sets it via a bare `.set()` (not a scoped context manager — the fixture's own task
finishes before the test body's task is even created, and pytest-asyncio's own contextvar-
propagation machinery is what carries the value forward; a context manager would reset it first).

A second, related bug was found and fixed in the same commit (dccb7323): the `watcher` fixture's
own teardown (introduced by this session's KI-002 fix, commit 872e38ad) unconditionally restored
the loop's task factory back to the one routing through `hassette.task_bucket` once cleanup
finished — even when that bucket had just been confirmed permanently sealed by a real shutdown.
Since a completed shutdown is not reversible, this meant the *next* test's own setup immediately
hit the sealed bucket and errored. Fixed by not restoring in that case.

Result: all 6 tests that previously failed with `CancelledError` now pass in isolation. Running
shutdown-triggering tests back-to-back in file order no longer errors at setup. See KI-004 for
what still happens in a full-file run.

## KI-004: shutdown-triggering tests in `test_service_watcher.py` share one module-scoped `Hassette` instance

Status: resolved
Run: fixed in this session (uncommitted at time of writing — see report at
`/tmp/hassette-ki004-fix-report.md`)
Source: discovered while verifying KI-003's fix (commit dccb7323)

Issue (as originally observed):
6 tests in `test_service_watcher.py` each drive a real, complete `hassette.shutdown()`
(restart-budget exhaustion or a fatal error). `reset_hassette_lifecycle()` correctly refuses to
revive an instance that has already fully shut down (by design — see its docstring: "must not be
used to revive a Hassette that has been completely shut down... construct a fresh instance
instead"). All 6 tests pass individually in isolation, but because they share one module-scoped
`hassette_with_bus` instance with every other test in the file, running the file in its normal
order still produces real, distinct failures downstream of whichever shutdown-triggering test ran
first — confirmed via triage that these are not new independent bugs and not a
`reset_hassette_lifecycle()` defect, just an inherent consequence of one dead shared instance
serving tests that expect a live one.

Fix: each of the 6 shutdown-triggering tests now uses a new `isolated_watcher()` async context
manager (local to `test_service_watcher.py`) that builds its own private `Hassette` instance via
`build_harness()`, used directly inline in the test body rather than as a pytest fixture — see the
full report for the design rationale (`skip_global_set=True`, a fresh `HassetteConfig` per
isolated instance, and why `context.PROTECT_TASK` is not needed for this pattern). The other 15
tests are unchanged and continue to share the module-scoped `watcher` fixture.

Result: `uv run pytest tests/integration/test_service_watcher.py -p no:randomly -v` (full file,
normal order) no longer cascades — the 6 previously-cascading tests and every test after them in
file order now pass. Two pre-existing, order-independent failures remain in this file
(`test_budget_reset_on_recovery`, `test_budget_reset_on_recovery_confirmed`) — confirmed via a
disposable `git stash` to reproduce identically on this branch's pre-fix code, and to fail even
when run alone with no other tests in the process. This is a separate, unrelated defect, not a
KI-004 cascade symptom; see the report for detail and a recommendation to track it as a new
follow-up issue.

Acceptance criteria:
- `uv run pytest tests/integration/test_service_watcher.py` (full file, normal order) produces
  zero failures/errors *caused by the shared-instance cascade this issue describes*. Met: the
  file's failure count no longer grows past the two pre-existing, independently-reproducible
  failures once the 6 shutdown-triggering tests are isolated.

## KI-005: `test_budget_reset_on_recovery(_confirmed)` fail — a real regression from this branch's own restart-safety logic, not pre-existing on `main`

Status: open
Run: discovered while verifying KI-004's fix
Source: this session

Issue:
`test_budget_reset_on_recovery` and `test_budget_reset_on_recovery_confirmed` fail deterministically,
in isolation and regardless of file order:
```
AssertionError: assert 2 == 0
 +  where 2 = budget_entries(<ServiceWatcher ...>, '_Dummy:service')
```
Both build a dummy service with `fail=True` (its `on_initialize` always raises), accumulate 2
restart attempts, then manually call `mark_ready()` and fire a synthetic RUNNING event expecting
the restart budget to reset to 0. The captured logs show the underlying restart attempts hitting
`"Restart refused for '_Dummy...': teardown was not proven restart-safe (cleanup_failed)"` — a
message from this branch's own restart-safety design (cleanup-failure detection introduced in
T01-T04).

**Confirmed via a disposable worktree checked out at `main` (not inferred): both tests pass
cleanly on `main` (`2 passed`).** This is a real regression introduced by this branch's own new
restart-safety semantics, in the same category as KI-002/KI-003/KI-004 — not a pre-existing,
someone-else's-problem bug that happens to predate this work. It was invisible until now only
because KI-002's cascade prevented these two tests (positioned after other shutdown-triggering
tests in file order) from ever actually running.

Why deferred (for now):
Root-causing this means understanding whether the test's `fail=True` + manual `mark_ready()`
combination is now testing a scenario this branch's restart-safety design correctly refuses (i.e.
the test's own expectations are stale relative to the new cleanup-failure-blocks-restart
guarantee, and the test needs updating), or whether there's a genuine gap in the design (recovery
should be possible even after a cleanup failure, and isn't). That's a production-semantics
question, not a mechanical test-infra fix — it needs its own investigation before landing a fix,
the same way KI-003's "narrow vs broad" design question did.

Recommended follow-up:
Investigate whether `_run_task_bucket_shutdown_stage()`/`cleanup()`'s cleanup-failure detection is
correctly refusing restart in this dummy's specific failure mode (a `Service` whose
`on_initialize()` raises synchronously — check what "cleanup" even means for an instance that
never finished initializing), or whether the refusal is overly broad and these two tests are
catching a real design gap in T01-T04's restart-safety logic. Fix production code or update the
tests' expectations accordingly, whichever the investigation concludes is correct — do not "fix"
this by loosening the restart-safety guarantee without confirming that's actually right.

Acceptance criteria:
- `uv run pytest tests/integration/test_service_watcher.py::test_budget_reset_on_recovery
  tests/integration/test_service_watcher.py::test_budget_reset_on_recovery_confirmed` pass, with a
  clear understanding of whether the fix was a test update or a production-code change, and why.
