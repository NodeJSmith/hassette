# Design: Stateless dispatch-mode bridge for bus and scheduler

**Date:** 2026-06-20
**Status:** archived
**Scope-mode:** hold

## Problem

The bus (`HandlerInvoker`) and the scheduler (`SchedulerService` / `ScheduledJob`)
each hand-roll the same non-parallel dispatch glue around the shared
`ExecutionModeGuard`. Both independently implement: the per-invocation
`pending_done` completion-future bridge, the `run_and_track` factory that spawns a
stall-watched child, the await-the-bridge logic, the stall watchdog
(`invocation_with_stall_watch` + a `warn_stalled*` callback), and the drain that
unhangs `QUEUED_ACCEPTED` triggers on release. The two
`invocation_with_stall_watch` methods and the two `STALL_THRESHOLD_SECONDS`
constants are structurally identical, kept equal only by a fragile sync test
(`tests/unit/core/test_stall_threshold_sync.py`).

This duplication is a maintenance hazard: a fix to one path (e.g. the
`pending_done` hang fix) must be hand-mirrored to the other, and the
cross-referencing line-number comments in both files drift as the files change.
The recently-investigated `drain_next`/`release` interleave caveat is documented
on the scheduler side only, even though the bus has identical exposure — exactly
the "fix one, forget the other" failure this duplication invites.

## Goals

- Extract the duplicated dispatch glue into stateless free functions in
  `src/hassette/execution_mode.py` — the dependency-free leaf both subsystems can
  import without a cycle — and migrate both call sites to use them.
- Unify `STALL_THRESHOLD_SECONDS` to a single source of truth, removing the sync
  test and its drift surface.
- Preserve behavior exactly. This is a refactor: the runtime semantics of every
  overlap mode, the stall watchdog, and the drain must be unchanged, proven on
  the real surface (`nox -s system` + `nox -s e2e`).
- Keep `execution_mode.py` a dependency-free leaf (stdlib + `hassette.types.enums`
  only) so the hard bus/scheduler decoupling is preserved structurally.

## Non-Goals

- **Not fixing the `drain_next`/`release` interleave edge.** That evaluation and
  any fix is deferred to issue #1099. This refactor only relocates its caveat
  into the shared docstring.
- **Not unifying the invocation mechanism.** Bus DI (`InvokeHandler` +
  `ParameterInjector`) vs scheduler pre-bound `ExecuteJob` stay divergent — the
  bridge only ever sees an opaque `invoke()` callable.
- **Not changing `ExecutionModeGuard`.** The overlap state machine
  (`run`/`release`/`drain_next`) is reused unmodified.
- **Not touching** the rate-limiter, the once-guard ordering, `mark_registered`,
  or error routing — all sit outside the shared glue (see Key Constraints).
- **No stateful owner object** (`DispatchModeRunner` and friends) — rejected by
  the hard import constraint; see Alternatives.

## User Scenarios

### Framework maintainer: fixes or extends non-parallel dispatch behavior
- **Goal:** change the completion-future bridge, the stall watchdog, or the drain
  without introducing a bus/scheduler divergence.
- **Context:** maintaining `execution_mode.py`, `bus/listeners.py`, or
  `scheduler_service.py`.

#### Single-point change to shared dispatch glue

1. **Locates the dispatch glue**
   - Sees: one shared implementation in `execution_mode.py` (`run_through_guard`,
     `run_with_stall_watch`, `drain_pending_done`) with one docstring covering
     both consumers, including the `drain_next`/`release` interleave caveat and
     the #1099 reference.
   - Decides: edit the shared function once.
   - Then: both the bus and scheduler pick up the change; no second copy to
     mirror, no sync test to keep equal.

2. **Verifies behavior is unchanged**
   - Sees: characterization tests for both surfaces (bus and scheduler
     stall-watch, queued-cancel drain) pass.
   - Then: ships with confidence the extraction was behavior-preserving.

## Functional Requirements

- **FR#1** `execution_mode.py` exposes `run_with_stall_watch(invoke, warn, threshold)`
  that runs one invocation and invokes `warn` if the invocation holds longer than
  `threshold` seconds, cancelling the watchdog when the invocation settles
  (normally or via cancellation).
- **FR#2** `run_with_stall_watch` passes the armed `threshold` to `warn`, so the
  value the warn callback reports always equals the value the watchdog fired at.
- **FR#3** `execution_mode.py` exposes `run_through_guard(...)` that routes one
  non-parallel invocation through a caller-supplied `ExecutionModeGuard`, bridging
  completion via a future it adds to (and resolves on) the caller-owned
  `pending_done` set, and settling immediately on `SUPPRESSED`/`DROPPED`.
- **FR#4** `run_through_guard` spawns the stall-watched child via a caller-supplied
  spawn callable (not a `TaskBucket` object), keeping `execution_mode.py` free of
  any `bus`/`core`/`scheduler` import.
- **FR#5** `execution_mode.py` exposes `drain_pending_done(pending_done)` that
  resolves every unresolved future in the supplied set.
- **FR#6** `STALL_THRESHOLD_SECONDS` is defined once in `execution_mode.py`; both
  `bus/listeners.py` and `scheduler_service.py` import it and pass it explicitly
  as `threshold=` at each call site using their own module-local imported name.
- **FR#7** The bus call sites (`HandlerInvoker.run_with_mode`, `release_guard`) use
  the shared functions; the local `invocation_with_stall_watch` method and the
  inline bridge/drain bodies are removed.
- **FR#8** The scheduler call sites (`SchedulerService.run_job_with_guard`, the
  three `drain_pending_done` call sites) use the shared functions; the local
  `invocation_with_stall_watch` and standalone `drain_pending_done` methods are
  removed.
- **FR#9** The parallel fast-path stays in each caller (the helper handles only the
  non-parallel path).
- **FR#10** Every overlap-mode behavior observable today is unchanged: SINGLE
  suppression, RESTART cancel-and-replace, QUEUED serialization + newest-drop at
  cap, PARALLEL fire-and-forget, the `QUEUED_ACCEPTED`-releases-without-hang path,
  and the stall WARNING content (job/listener name + mode).

## Edge Cases

- **`QUEUED_ACCEPTED` then release before drain.** The accepted factory never
  spawns a child; its `pending_done` future must be resolved by
  `drain_pending_done` on release so the outer dispatch task unwinds (no hang).
- **`SUPPRESSED` / `DROPPED`.** The factory is never called, so `run_through_guard`
  must resolve the future inline before returning.
- **Patched threshold.** A test patches the *module-local* `STALL_THRESHOLD_SECONDS`;
  because the call site reads that name at call time and passes it explicitly,
  the patched value must reach the watchdog (no def-time default capture).
- **Parallel mode.** Must never enter `run_through_guard`; the caller awaits the
  invocation inline (bus: `await invoke_fn()`; scheduler: `await self.run_job(job)`).
- **Stall watchdog under cancellation.** The watchdog is cancelled in `finally`
  whether the invocation completes or is cancelled.
- **`drain_next`/`release` interleave.** Out of scope (#1099); behavior carried
  verbatim. The caveat moves into the shared docstring.

## Acceptance Criteria

- **AC#1** All existing bus execution-mode tests
  (`tests/integration/bus/test_execution_modes.py`,
  `tests/unit/bus/test_execution_mode_guard.py`) pass unchanged in behavior.
- **AC#2** All existing scheduler mode tests (`tests/integration/test_scheduler_mode.py`)
  pass, with only the assertion adaptation required by FR#2 (warn receives the
  threshold argument).
- **AC#3** A new bus stall-watch characterization test asserts the watchdog fires
  `warn_stalled` with the patched threshold for a non-parallel listener (mirrors
  the scheduler's `test_stall_watchdog_emits_warning_for_non_parallel`). This test
  exists and passes **before** the bus migration commit.
- **AC#4** `tests/unit/core/test_stall_threshold_sync.py` is deleted and no longer
  referenced.
- **AC#5** Patching `bus.listeners.STALL_THRESHOLD_SECONDS` and
  `scheduler_service.STALL_THRESHOLD_SECONDS` each still changes the value the
  watchdog arms at (verified by the stall-watch tests actually firing at the
  patched value, not reasoned about).
- **AC#6** `execution_mode.py`'s import list contains no `bus`, `core`, or
  `scheduler` import (verified by the existing module-boundary linter and by grep).
- **AC#7** `nox -s system` and `nox -s e2e` pass locally (core-change pre-ship gate).
- **AC#8** `uv run pyright` is clean for the changed files.

## Key Constraints

- **Scheduler must not import from `bus.*`** (hard). The shared helpers live in
  `execution_mode.py`, the leaf reachable from both subsystems without a cycle; a
  bus-resident helper would force a forbidden scheduler→bus import. Note:
  `scheduler_service.py` does **not** currently import from `execution_mode` (only
  `scheduler/classes.py:11` does), so the migration **adds a new import line** to
  `scheduler_service.py`; the bus side extends its existing `execution_mode`
  import at `bus/listeners.py:13`.
- **Stateless free functions only** — no shared owner object holding `pending_done`
  or the guard. State stays owned by `HandlerInvoker` / `ScheduledJob`; the helper
  receives it as parameters. Note (Finding 3): `run_through_guard` is *not*
  side-effect-free — it installs a live done-callback that mutates the caller's
  `pending_done` set after it returns; "stateless" means it owns no state between
  calls, not that it has no ongoing effects. The docstring must say this plainly.
- **Preserve legitimate divergence.** The invocation mechanism (bus DI via
  `InvokeHandler`, scheduler pre-bound `ExecuteJob`), `mark_registered`
  first-call-wins, error routing, the sync-vs-async adapter timing, and the
  outer-task fan-out models are NOT part of the shared glue and must not be folded
  in (full map in the research brief's appendix).
- **No `assert` statements in the new helpers.** PR #1088 added `-O`-sensitive
  wiring guards elsewhere; the dispatch path itself has none, and the extraction
  must not introduce any that would vanish under `python -O`.
- **Project style:** functions-over-methods, flat hierarchy, immutability, no
  `from __future__ import annotations`, `X | None` not `Optional`, top-level
  imports only, line length 120.

## Dependencies and Assumptions

- `ExecutionModeGuard` (`execution_mode.py:34-161`) is reused unmodified.
- `task_bucket.spawn(coro, *, name=...) -> asyncio.Task` is the spawn signature
  both callers wrap into the `spawn` callable (FR#4).
- `pending_done` lives on `HandlerInvoker` (`bus/listeners.py:203`) and
  `ScheduledJob` (`scheduler/classes.py:245`) and stays there.
- Issue #1099 owns the interleave evaluation/fix; this design only relocates the
  caveat.

## Architecture

The recommended approach is the research brief's **Option A**: callback-parameterized
free functions in `execution_mode.py`. **The code block below is authoritative** —
it supersedes the brief's Option A sketch (which used a `task_bucket` parameter;
Finding 6 replaces that with a bare `spawn` callable).

### New functions in `execution_mode.py`

```python
STALL_THRESHOLD_SECONDS: float = 60.0
"""Single source of truth. Imported by both subsystems and passed explicitly as
``threshold=`` at each call site — never used as a helper default argument (a
default binds at definition time and would defeat test patches)."""

async def run_with_stall_watch(
    invoke: Callable[[], Awaitable[None]],
    warn: Callable[[float], None],
    threshold: float,
) -> None:
    """Run one invocation; call ``warn(threshold)`` if it holds past ``threshold`` seconds.

    ``warn`` receives the same ``threshold`` the watchdog armed at, so a logged stall
    message can never disagree with when the watchdog fired.
    """
    watchdog = asyncio.get_running_loop().call_later(threshold, warn, threshold)
    try:
        await invoke()
    finally:
        watchdog.cancel()


async def run_through_guard(
    guard: ExecutionModeGuard,
    spawn: Callable[..., "asyncio.Task[None]"],
    pending_done: "set[asyncio.Future[None]]",
    invoke: Callable[[], Awaitable[None]],
    warn: Callable[[float], None],
    spawn_name: str,
    threshold: float,
) -> None:
    """Route one non-parallel invocation through ``guard``, bridging completion via a future.

    Caller handles the ``parallel`` fast-path first — this is the single/restart/queued
    path only. Installs exactly one done-callback on ``pending_done`` per call; that
    callback fires when the spawned task completes, which may be after this function
    returns. Caller must call ``drain_pending_done(pending_done)`` after every
    ``guard.release()`` to resolve futures whose factory was dropped without running.

    Note: the ``drain_next``/``release`` interleave edge (a task spawned by ``drain_next``
    concurrently with ``release()`` may detach rather than cancel) applies to every caller
    that reaches release through a detached spawn — both the bus and the scheduler. Not
    fixed here; tracked in issue #1099.
    """
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()
    pending_done.add(done)

    def resolve_done() -> None:
        pending_done.discard(done)
        if not done.done():
            done.set_result(None)

    def run_and_track() -> "asyncio.Task[None]":
        task = spawn(run_with_stall_watch(invoke, warn, threshold), name=spawn_name)
        task.add_done_callback(lambda _t: resolve_done())
        return task

    outcome = await guard.run(run_and_track)
    if outcome in (Outcome.SUPPRESSED, Outcome.DROPPED):
        resolve_done()
        return
    await done


def drain_pending_done(pending_done: "set[asyncio.Future[None]]") -> None:
    """Resolve every unresolved completion future. Call after ``guard.release()``."""
    for done in list(pending_done):
        pending_done.discard(done)
        if not done.done():
            done.set_result(None)
```

`spawn` is passed as a bare callable (Finding 6), not a `TaskBucket` object, so
`execution_mode.py` needs no `TYPE_CHECKING` import of `TaskBucket` and stays a
pure leaf. `run_through_guard` calls it as `spawn(coro, name=spawn_name)`, so each
caller wraps its bucket with a keyword-only `name` to match
`TaskBucket.spawn(coro, *, name=...)`: `spawn=lambda coro, *, name: self.task_bucket.spawn(coro, name=name)`.

### Bus call site (`bus/listeners.py`)

`HandlerInvoker.run_with_mode` collapses to the parallel fast-path plus one
`await run_through_guard(...)` call, passing `spawn` (wrapped `task_bucket.spawn`),
`pending_done=self.pending_done`, `invoke=invoke_fn`, `warn=self.warn_stalled`,
`spawn_name="bus:mode_invocation"`, `threshold=STALL_THRESHOLD_SECONDS` (imported
into `bus.listeners`). `release_guard` becomes
`await self.guard.release(); drain_pending_done(self.pending_done)`. The local
`invocation_with_stall_watch` method is deleted. `warn_stalled` stays but its
signature becomes `warn_stalled(self, threshold: float)` and it logs the passed
value (its message still uses `handler_short_name` + `mode`).

### Scheduler call site (`core/scheduler_service.py`)

`run_job_with_guard` collapses symmetrically, passing `invoke=lambda: self.run_job(job)`,
`warn=lambda secs: self.warn_stalled_job(job, secs)`, `pending_done=job.pending_done`,
`spawn_name="scheduler:mode_invocation"`, `threshold=STALL_THRESHOLD_SECONDS`
(imported into `scheduler_service`). `warn_stalled_job` becomes
`warn_stalled_job(self, job, threshold: float)` and logs the passed value. The
imported `drain_pending_done(job.pending_done)` replaces the local method at all
three call sites (`_remove_jobs_by_owner`, `_remove_job`, `dequeue_job`'s
`_release_and_drain`). The local `invocation_with_stall_watch` method is deleted.
`scheduler_service.py` gains a **new** top-level import (it imports nothing from
`execution_mode` today):
`from hassette.execution_mode import STALL_THRESHOLD_SECONDS, drain_pending_done, run_through_guard, run_with_stall_watch`.
The bus adds the same names to its existing `execution_mode` import at
`bus/listeners.py:13`.

### Implementation Sequence

Sequenced as verifiable units (`sequence-verifiable-units.md`); each step ends
green so the commit trail is the proof of a behavior-preserving refactor.

1. **Pin (RED-first).** Add the missing characterization tests — the bus
   stall-watch test (AC#3) and the explicit bus `release_guard` → `pending_done`
   drain test. These pass against the *current* code. The bus stall-watch pin is a
   **HARD prerequisite gating step 3** (the bus has no such test today).
2. **Add shared code.** Add `run_with_stall_watch`, `run_through_guard`,
   `drain_pending_done`, and the hoisted `STALL_THRESHOLD_SECONDS` to
   `execution_mode.py`. Both subsystems still use their own copies — purely
   additive, all tests green.
3. **Migrate the bus.** Rewrite `run_with_mode`/`release_guard` onto the helpers,
   change `warn_stalled`'s signature, delete the bus-local stall/bridge/drain. Bus
   pins from step 1 stay green.
4. **Migrate the scheduler.** Rewrite `run_job_with_guard`, repoint the three drain
   call sites, change `warn_stalled_job`'s signature, delete the scheduler-local
   methods, and adapt the scheduler stall-test assertion (Test Strategy).
5. **Remove the sync test** and confirm both patch points fire at the patched
   value by *running* the stall-watch tests (AC#5), not by inspection.

## Replacement Targets

- `bus/listeners.py` — `STALL_THRESHOLD_SECONDS` constant, `invocation_with_stall_watch`
  method, inline bridge body in `run_with_mode`, inline drain in `release_guard`.
  **Remove** (replaced by shared functions + import).
- `core/scheduler_service.py` — `STALL_THRESHOLD_SECONDS` constant,
  `invocation_with_stall_watch` method, standalone `drain_pending_done` method,
  inline bridge body in `run_job_with_guard`. **Remove** (replaced by shared
  functions + import).
- `tests/unit/core/test_stall_threshold_sync.py` — **Remove** outright; the sync
  invariant is vacuous once there is one constant.
- Cross-referencing line-number comments between the two files
  ("mirrors HandlerInvoker.run_with_mode", "mirrors release_guard (...)") —
  **Remove**, replaced by the single shared docstring.

## Convention Examples

### Stall-watch characterization test (mirror for the new bus test)

**Source:** `tests/integration/test_scheduler_mode.py:960`

```python
async def test_stall_watchdog_emits_warning_for_non_parallel() -> None:
    started = asyncio.Event()
    gate = asyncio.Event()
    # ... app with a non-parallel job whose task sets started then awaits gate ...
    with (
        unittest.mock.patch.object(scheduler_service_module, "STALL_THRESHOLD_SECONDS", 0.05),
        unittest.mock.patch.object(scheduler_service, "warn_stalled_job") as mock_warn,
    ):
        dispatch_task = asyncio.create_task(scheduler_service.dispatch_and_log(job))
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await asyncio.sleep(0.2)
        assert not dispatch_task.done()
        mock_warn.assert_called_once_with(job)   # <-- becomes assert_called_once_with(job, 0.05) after FR#2
```

The new bus test patches `bus.listeners.STALL_THRESHOLD_SECONDS`, spies on
`HandlerInvoker.warn_stalled`, dispatches a non-parallel listener that blocks,
and asserts the spy fired with the patched threshold.

### Deterministic gate pattern (no tick-racing)

**Source:** CLAUDE.md "Regression test patterns" + the test above. Use
`asyncio.Event` gates and `wait_for(started.wait())` to reach the blocked state
deterministically — never `await asyncio.sleep(0)`.

## Alternatives Considered

- **Option B — extract only the bridge + drain, leave stall-watch inline per caller.**
  De-dups the bridge but leaves the two `invocation_with_stall_watch` methods
  duplicated and still needs `spawn_name` as a param. The stall-watch wrapper is
  the cheapest, lowest-risk piece to unify (three identical lines), so leaving it
  duplicated forfeits the easiest win for almost no signature savings. Rejected.
- **Option C — stateful `DispatchModeRunner` owner.** Would have to live in/near
  the bus, forcing a forbidden scheduler→bus import, and re-introduces an object
  lifecycle that duplicates `ExecutionModeGuard`. Rejected by the hard constraint.
- **Protocol/mixin shapes.** No polymorphism is needed (both callers want the same
  behavior, not two implementations); a mixin would couple two unrelated
  dataclasses through inheritance. Free functions dominate.
- **Do nothing.** Leaves the drift hazard, the fragile sync test, and the
  one-sided interleave caveat in place. Rejected — the duplication is the issue.

## Test Strategy

### Existing Tests to Adapt
- `tests/integration/test_scheduler_mode.py:999` — `test_stall_watchdog_emits_warning_for_non_parallel`
  asserts `mock_warn.assert_called_once_with(job)`; under FR#2 `warn_stalled_job`
  is called with `(job, threshold)`, so the assertion becomes
  `assert_called_once_with(job, 0.05)` (the patched value). The patch target
  (`scheduler_service_module.STALL_THRESHOLD_SECONDS`) stays valid.
- `tests/integration/test_scheduler_mode.py:1006` — `test_parallel_mode_has_no_stall_watchdog`
  patches the threshold but parallel never arms the watchdog; verify it still
  passes (patch target unchanged).
- Any test importing `STALL_THRESHOLD_SECONDS` from `scheduler_service` or
  `bus.listeners` keeps working (the name is re-exported via the module-local
  import); confirm by running, not by inspection.

### New Test Coverage
- **Bus stall-watch characterization** (FR#1, FR#2; AC#3) — **HARD prerequisite**
  for the bus migration commit. The bus has no equivalent of the scheduler's
  stall-watch test today. Mirrors `test_stall_watchdog_emits_warning_for_non_parallel`.
- **Bus `release_guard` → `pending_done` drain unit/integration test** (FR#3, FR#5)
  — currently only covered indirectly via
  `test_cancelling_queued_listener_releases_pending` (`test_execution_modes.py:366`).
  Add an explicit assertion that a `QUEUED_ACCEPTED` future is resolved by release.

### Tests to Remove
- `tests/unit/core/test_stall_threshold_sync.py` (AC#4) — vacuous after FR#6.

## Documentation Updates

- **Docstrings** on the three new functions in `execution_mode.py`, including the
  `drain_next`/`release` interleave caveat and the #1099 reference (Finding 5).
- **No docs-site (`docs/pages/`) or frontend changes.** Per
  `design-completeness.md`, this is internal framework plumbing with no
  user-facing API change — app authors never call the dispatch glue directly. The
  exemption applies (internal refactor, no behavior change). No `CHANGELOG.md`
  edit (release-please owns it; commit as `refactor:`).

## Impact

### Changed Files
<!-- Gap check 2026-06-20: 2 gaps included — tests/unit/core/test_scheduler_service_dequeue.py (spies run_job_with_guard) and tests/unit/core/test_scheduler_service_reschedule.py (mocks run_job_with_guard) → T04 Focus + Verify (run to confirm; method name/signature preserved, low risk). -->
- `src/hassette/execution_mode.py` — **modify** (additive): add three free
  functions + the hoisted constant. Highest-leverage shared file.
- `src/hassette/bus/listeners.py` — **modify**: rewrite `run_with_mode` /
  `release_guard`, change `warn_stalled` signature, delete local stall/bridge/drain.
- `src/hassette/core/scheduler_service.py` — **modify**: rewrite `run_job_with_guard`,
  change `warn_stalled_job` signature, delete local stall/bridge/drain methods,
  repoint the three drain call sites.
- `tests/integration/bus/test_execution_modes.py` — **modify**: add bus stall-watch
  test + explicit drain test.
- `tests/integration/test_scheduler_mode.py` — **modify**: adapt the warn assertion.
- `tests/unit/core/test_stall_threshold_sync.py` — **delete**.

### Behavioral Invariants
- Every overlap-mode outcome (SINGLE/RESTART/QUEUED/PARALLEL), the
  `QUEUED_ACCEPTED`-no-hang path, and the newest-drop-at-cap behavior must be
  unchanged.
- Stall WARNING level (WARNING) and message shape (name + mode) are unchanged.
  **Exception, by design (Finding 1):** the logged *duration* now reflects the
  threshold the watchdog actually armed at, sourced from the `threshold` argument
  rather than re-read from the module constant. Under production (default 60.0s)
  this is byte-identical output; the values can differ only when a non-default
  threshold is supplied, which today happens only in tests via `patch.object`.
  This is the intended correction of a latent mismatch where the old log could
  report 60.0s while the watchdog fired at a patched value — not a regression.
- The bus/scheduler import boundary (`execution_mode.py` is a leaf; scheduler
  never imports `bus.*`) must hold.
- The `drain_next`/`release` interleave behavior is carried verbatim — not changed.

### Blast Radius
- `run_with_mode` is on the hot path for every non-parallel bus event; the rewrite
  is mechanical but the blast radius is the entire event-dispatch flow, hence the
  system + e2e gate (AC#7), which exercise the boundaries unit tests mock.
- The scheduler dispatch path for every non-parallel job.

## Open Questions

None. The brief's open questions are resolved: `spawn` is a bare callable
(Finding 6); the parallel fast-path stays in each caller (FR#9); naming is
`run_through_guard` / `run_with_stall_watch` / `drain_pending_done`.
