# Context: Stateless dispatch-mode bridge for bus and scheduler

## Problem & Motivation

The bus (`HandlerInvoker`) and scheduler (`SchedulerService`/`ScheduledJob`) each
hand-roll the same non-parallel dispatch glue around the shared
`ExecutionModeGuard`: the per-invocation `pending_done` completion-future bridge,
the `run_and_track` spawn factory, the stall watchdog
(`invocation_with_stall_watch` + a `warn_stalled*` callback), and the drain that
unhangs `QUEUED_ACCEPTED` triggers on release. The two `STALL_THRESHOLD_SECONDS`
constants are kept equal only by a fragile sync test. This duplication forces every
fix to be hand-mirrored across both files and lets cross-referencing comments
drift. The work extracts the glue into stateless free functions in
`execution_mode.py` (the dependency-free leaf both subsystems can import without a
cycle) and migrates both call sites — a pure behavior-preserving refactor.

## Visual Artifacts

None.

## Key Decisions

1. **Option A — callback-parameterized free functions** in `execution_mode.py`:
   `run_with_stall_watch`, `run_through_guard`, `drain_pending_done`, plus a hoisted
   `STALL_THRESHOLD_SECONDS`. No stateful owner object (would force a forbidden
   scheduler→bus import).
2. **Warn callback receives the armed threshold** (`warn: Callable[[float], None]`,
   `call_later(threshold, warn, threshold)`) so the logged stall duration can never
   disagree with when the watchdog fired (resolved HIGH Finding 1).
3. **`threshold` is a required parameter, never a module-constant default** — a
   default binds at definition time and would defeat `patch.object` in tests. Each
   call site passes `threshold=STALL_THRESHOLD_SECONDS` via its own module-local
   imported name, so existing patches keep working (resolved HIGH Finding 2).
4. **`spawn` is a bare callable**, not a `TaskBucket` object, so `execution_mode.py`
   stays a pure leaf (Finding 6). `run_through_guard` calls `spawn(coro, name=...)`;
   callers wrap with `lambda coro, *, name: self.task_bucket.spawn(coro, name=name)`.
5. **The parallel fast-path stays in each caller** — the helper is strictly the
   single/restart/queued path.
6. **`run_through_guard` is not side-effect-free** — it installs a live done-callback
   that mutates the caller's `pending_done` after returning; the docstring must say
   this plainly ("stateless" = owns no state between calls, not no ongoing effects).
7. **Pin-first commit sequence** (verifiable units): pin → add shared code → migrate
   bus → migrate scheduler → delete sync test. Each step ends green.

## Constraints & Anti-Patterns

- **Scheduler must NOT import from `bus.*`** (hard). Helpers live in
  `execution_mode.py`. Note: `scheduler_service.py` imports nothing from
  `execution_mode` today — the migration ADDS a new import there; the bus extends
  its existing import at `bus/listeners.py:13`.
- **Do NOT fix the `drain_next`/`release` interleave edge** — out of scope, tracked
  in issue #1099. Only relocate its caveat into the shared docstring.
- **Do NOT unify the invocation mechanism** (bus DI/`InvokeHandler` vs scheduler
  pre-bound `ExecuteJob`), `mark_registered`, error routing, the sync/async adapter,
  or the outer-task fan-out — all sit outside the shared glue.
- **Do NOT change `ExecutionModeGuard`** — reuse unmodified.
- **No `assert` statements in the new helpers** (`-O`-stripping safety).
- This is a refactor: no smuggled behavior changes. Prove unchanged on the real
  surface (`nox -s system` + `nox -s e2e`), not unit tests alone.
- Project style: functions-over-methods, flat hierarchy, immutability, no
  `from __future__ import annotations`, `X | None` not `Optional`, top-level imports,
  line length 120, no blanket `# type: ignore`.

## Design Doc References

- `## Architecture` — authoritative function signatures + call-site rewrites (the
  code block supersedes the brief's sketch).
- `## Architecture → Implementation Sequence` — the 5-step verifiable commit order.
- `## Test Strategy` — existing tests to adapt, new coverage, tests to remove.
- `## Impact → Behavioral Invariants` — what must not change (incl. the Finding-1
  WARNING-duration nuance).
- `## Key Constraints` — the scheduler-import and statelessness constraints.

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
        mock_warn.assert_called_once_with(job)   # after Finding 1: assert_called_once_with(job, 0.05)
```

### Deterministic gate pattern (no tick-racing)

Use `asyncio.Event` gates and `wait_for(started.wait())` to reach the blocked state
deterministically — never `await asyncio.sleep(0)` to "let the task reach the block"
(per CLAUDE.md regression-test patterns). The `await asyncio.sleep(0.2)` above is a
threshold-elapse wait against a patched 0.05s threshold, not a scheduler-tick race.
