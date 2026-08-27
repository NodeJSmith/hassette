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
