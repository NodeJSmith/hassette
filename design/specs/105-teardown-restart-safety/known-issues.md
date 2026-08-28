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


## KI-005: `test_budget_reset_on_recovery(_confirmed)` fail -- a real regression from this branch's own restart-safety logic, not pre-existing on `main`

Status: resolved
Run: discovered while verifying KI-004's fix, fixed in this session
Source: this session

Issue:
`test_budget_reset_on_recovery` and `test_budget_reset_on_recovery_confirmed` failed due to two
independent causes, both introduced by this branch. Confirmed via a disposable worktree checked out
at `main`: both tests pass cleanly on `main` (`2 passed`).

**Cause 1 -- cleanup conflation (production code gap):** `Resource.cleanup()` awaited
`self._init_task` with only `suppress(asyncio.CancelledError)`. When a service's `on_initialize()`
raised (e.g. `RuntimeError`), the done `_init_task` re-raised that stored exception during cleanup.
`_run_post_hook_shutdown_stage()`'s outer `except Exception` caught it and classified it as
`TeardownCause.CLEANUP_FAILED`, making `restart_safety == UNSAFE` and raising
`RestartRefusedError`. The classification was wrong: a service that failed during init has nothing
to clean up -- the init exception was already recorded by `handle_failed()`, and re-raising it
during cleanup was a leak, not a cleanup failure.

Fix: `cleanup()` now skips re-awaiting a done `_init_task` entirely -- the exception was already
observed, and there is no pending work to cancel or join.

**Cause 2 -- PROTECT_TASK leaked into test bodies (test infra interaction with KI-003 fix):** The
`watcher` fixture sets `context.PROTECT_TASK = True` (KI-003 fix, commit acc6c147) to prevent
pytest-asyncio's synthetic task from being tracked/cancelled by the root TaskBucket. pytest-asyncio
propagates contextvars from the fixture task into the test body's task, so `PROTECT_TASK` remained
`True` during the test. This caused `ServiceWatcher.on_service_running()`'s internally spawned
readiness-check task to be created but not tracked in the task bucket (the task factory sees
`PROTECT_TASK=True` and excludes the task). `on_running_and_await()`'s `pending_tasks()` diff
therefore found no new tasks and didn't wait for the readiness check, so `budget.reset()` never ran
before the assertion.

Fix: the two budget-reset tests clear `context.PROTECT_TASK.set(False)` at the start of their body.
These tests don't trigger `hassette.shutdown()`, so they don't need the protection -- they just need
ServiceWatcher's internally-spawned tasks to be properly tracked.

Acceptance criteria:
- Both tests pass. Met.
- Full file (`test_service_watcher.py`, 21 tests) passes with no cascades. Met.
- `test_task_bucket.py` (12 tests) still passes. Met.
- Full unit+integration suite (7078 tests) passes. Met.

## KI-006: files touched outside any task's declared Target Files list

Status: open
Run: 117
Source: impl-review
Reason not fixed now: out-of-scope
Observed in: T03, T04
Affected files:
- src/hassette/context.py
- src/hassette/test_utils/fixtures.py
- src/hassette/test_utils/harness.py
- src/hassette/test_utils/helpers.py

Issue:
The full-branch implementation review found four files modified during orchestration that were not
listed in any task's `## Target Files` section: `src/hassette/context.py` (a small addition
supporting `context.PROTECT_TASK`, part of the KI-003 fix) and three `src/hassette/test_utils/*.py`
files (part of the KI-002/KI-003 test-infrastructure deadlock fix in T04's scope). Each change is
individually justified and documented in this file's own KI-002/KI-003 entries, but the original
task decomposition never anticipated them, so they weren't tracked as declared scope at plan time.

Why deferred:
This is a documentation/traceability gap in the plan, not a code defect — every change is already
justified in KI-002/KI-003 with root-cause evidence, and re-litigating scope after the fact would
not change any code. Fixing this would mean retroactively editing already-shipped task files, which
provides no future value once the branch merges.

Recommended follow-up:
None required. This entry exists purely as a durable record that these four files were touched
outside declared scope, in case a future audit of this branch's diff needs that context. No action
needed unless a reviewer specifically asks why these files changed.

Acceptance criteria:
- N/A — informational record, no follow-up action defined.

## KI-007: `_shutdown_children()` duplicated between `Resource` and `Hassette`

Status: open
Run: 117
Source: impl-review
Reason not fixed now: out-of-scope
Observed in: T04, T06
Affected files:
- src/hassette/resources/base.py
- src/hassette/core/core.py

Issue:
`Resource._shutdown_children()` (`base.py`, T04) and `Hassette._shutdown_children()` (`core.py`,
T06) share a near-identical per-child classification loop: gather child teardown reports, merge
causes, add `CHILD_SHUTDOWN_FAILED`/`CHILD_SHUTDOWN_TIMED_OUT`/`CHILD_RESTART_UNSAFE` evidence, and
track affected-resource identity. The design's Key Constraints explicitly limits scope to "one
initialization task and one shutdown task per resource" without introducing a new lifecycle
controller object, and neither task's Target Files or Prompt called for a shared helper module —
Hassette's version also has root-specific concerns (dependency-wave ordering, total-timeout
merging) that a naive extraction would need to accommodate carefully.

Why deferred:
Extracting a shared helper is a real structural improvement but requires touching both `base.py`
and `core.py` together, verifying the extraction preserves each caller's distinct child-set
iteration order (reverse insertion for `Resource`, reverse dependency-wave for `Hassette`), and was
not scoped or budgeted into T04/T06's task boundaries. Doing it now, post-hoc, in the final review
pass risks a subtle behavioral regression in code this design treats as load-bearing for restart
safety, with no corresponding task-level test plan to pin it first.

Recommended follow-up:
A follow-up `topic:code-quality` issue (or `topic:architecture` if the extraction proves more
involved than expected) to factor the shared per-child classification loop into one helper
function, called by both `Resource._shutdown_children()` and `Hassette._shutdown_children()`, with
a characterization test pinning both callers' current behavior before refactoring.

Acceptance criteria:
- A shared helper exists and both `_shutdown_children()` implementations call it.
- `tests/unit/resources/lifecycle/test_shutdown.py` and
  `tests/unit/resources/lifecycle/test_total_timeout.py` (both callers' existing regression
  coverage) pass unchanged.

## KI-008: `Resource._shutdown_children()`'s `asyncio.gather()` can orphan sibling coroutines when the TaskBucket seals mid-iteration

Status: open
Run: 117
Source: cross-file-review
Reason not fixed now: out-of-scope
Affected files:
- src/hassette/resources/base.py (`Resource._shutdown_children()`, `asyncio.gather()` call)
- pyproject.toml (`filterwarnings`, the `PytestUnraisableExceptionWarning` entry added this run)

Issue:
`Resource._shutdown_children()` builds the list of `child.shutdown()` coroutines eagerly and passes
them to `asyncio.gather(*[child.shutdown() for child in children], return_exceptions=True)`.
`gather()` wraps each coroutine via `ensure_future()`/`create_task()` one at a time as it iterates
the argument list, not all at once up front. If the TaskBucket seals mid-iteration — a real scenario
a forced-shutdown test can trigger (see `test_run_forever_cleans_up_detectors_when_db_start_fails`)
— the not-yet-wrapped sibling coroutines are abandoned mid-creation. Because they were never
awaited, they later trigger a "coroutine was never awaited" `RuntimeWarning` when the garbage
collector finally reclaims them, which pytest surfaces as a `PytestUnraisableExceptionWarning`
session-level error unrelated to the test that actually exercised the sealed-bucket rejection path.

This run's `pyproject.toml` already added a `filterwarnings` entry to downgrade
`"Exception ignored while finalizing coroutine <coroutine object Resource.shutdown"` so this GC
artifact doesn't abort otherwise-passing test sessions. The filter's own comment states the
intent plainly: it does not mask the sealed-rejection `RuntimeError` itself (that is still
raised/logged), and the underlying `gather()` orphaning is "a separate, pre-existing base.py issue
to track and fix independently, not something a test-side filter should paper over long-term."

Why deferred:
The fix belongs in `Resource._shutdown_children()`'s child-coroutine construction — e.g. wrapping
each child's `shutdown()` in a task via `TaskBucket`-aware creation before handing them to
`gather()`, so a mid-iteration seal cannot leave any coroutine un-wrapped and un-awaited. That is a
production-code change to shared teardown machinery this design already treats as load-bearing for
restart safety (see KI-007), was not in scope for any of T01-T08's Target Files, and needs its own
regression test pinning the mid-iteration-seal race before touching the gather call. The
`pyproject.toml` filter is an intentional, explicitly-labeled stopgap, not a fix.

Recommended follow-up:
File a separate `topic:code-quality` (or `topic:architecture`, if the fix requires restructuring how
child shutdown tasks are created rather than a local wrap) issue to make
`Resource._shutdown_children()`'s child-coroutine dispatch resilient to a TaskBucket sealing
mid-iteration — e.g. by pre-wrapping each child's `shutdown()` call as a tracked task before passing
it to `asyncio.gather()` — with a regression test that reproduces the mid-iteration seal
deterministically. Once fixed, remove the now-unnecessary `filterwarnings` entry from
`pyproject.toml`.

Acceptance criteria:
- `Resource._shutdown_children()` no longer leaves any sibling coroutine unwrapped/unawaited when
  the TaskBucket seals mid-iteration through `asyncio.gather()`.
- A regression test reproduces the mid-iteration seal race and passes against the fix.
- The `pyproject.toml` `filterwarnings` entry for
  `"Exception ignored while finalizing coroutine <coroutine object Resource.shutdown"` is removed
  once the underlying orphaning can no longer occur.

## KI-009: `TeardownCause.COORDINATOR_FAILED` is undocumented in design.md and the docs site

Status: resolved — fixed during known issues walkthrough
Run: 117
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: commit f68a709f
Affected files:
- design/specs/105-teardown-restart-safety/design.md
- docs/pages/core-concepts/internals/lifecycle.md
- src/hassette/resources/teardown.py (`TeardownCause.COORDINATOR_FAILED`)
- src/hassette/resources/lifecycle.py (`_run_shutdown_coordinator`'s new `except Exception` block)

Issue:
`TeardownCause.COORDINATOR_FAILED` (added in f68a709f to close a ship-time challenge finding) has
no corresponding entry in design.md's cause enumeration, FR list, or Edge Cases, and
`docs/pages/core-concepts/internals/lifecycle.md`'s "Inspecting a report" / restart-refusal
narrative does not mention it either. Every other `TeardownCause` value has at least a design.md
docstring-level mention or an FR referencing the scenario that produces it; this one does not,
which makes it discoverable only by reading `teardown.py`'s enum docstring or the code path in
`lifecycle.py` directly. No production behavior is missing or wrong — `TeardownReport()` is
still correctly constructed and stored before the exception is re-raised (verified by reading
`_run_shutdown_coordinator`'s new `except Exception` block, `src/hassette/resources/lifecycle.py`
lines ~482-497) — this is a documentation-completeness gap, not a code defect.

Why deferred:
Not a clean-code (llm-checker/lazy-checker/nitpicker) finding — it surfaced while checking the
rename-consistency of this run's newly-added code per the dispatch's special note. Fixing it
requires drafting new design.md prose (an Edge Case entry and doc-site mention) rather than a
mechanical string fix, and doing that well means understanding when a coordinator can actually
raise outside the shutdown body (observing the initializer, requesting shutdown, reading config)
well enough to describe it accurately — judgment call, not a same-shape find-and-replace.

Recommended follow-up:
Add `COORDINATOR_FAILED` to design.md's cause list/Edge Cases (mirroring how `TOTAL_TIMEOUT` and
`FORCED_TERMINAL` are documented) and a short mention in `docs/pages/core-concepts/internals/lifecycle.md`'s
report-inspection section, describing what triggers it and that the exception still propagates to
the shutdown caller after the report is stored.

Acceptance criteria:
- design.md's cause enumeration and Edge Cases section mention `COORDINATOR_FAILED` and what
  produces it.
- `docs/pages/core-concepts/internals/lifecycle.md` mentions it alongside the other documented
  causes.

Result: Added `COORDINATOR_FAILED` to design.md's `TeardownCause` code block and a new Edge Cases
bullet describing when the coordinator raises outside the shutdown body. Added a short paragraph
to `docs/pages/core-concepts/internals/lifecycle.md`'s report-inspection section. Fixed directly
during the known issues walkthrough rather than deferred, since the author of this KI entry
(the same session) already had full context on why the cause exists.
