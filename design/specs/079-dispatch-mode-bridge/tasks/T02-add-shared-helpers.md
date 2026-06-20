---
task_id: "T02"
title: "Add shared dispatch-bridge helpers to execution_mode"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "AC#6"]
---

## Summary

Add the three stateless free functions and the hoisted `STALL_THRESHOLD_SECONDS`
constant to `src/hassette/execution_mode.py`. This step is purely additive: the bus
and scheduler still use their own copies of the glue, so all existing tests stay
green. No call sites change in this task. The code block in the design doc's
`## Architecture` section is authoritative for the signatures and bodies.

## Target Files

- modify: `src/hassette/execution_mode.py`
- read: `src/hassette/bus/listeners.py`
- read: `src/hassette/core/scheduler_service.py`
- read: `design/specs/079-dispatch-mode-bridge/design.md`
- read: `design/specs/079-dispatch-mode-bridge/tasks/context.md`

## Prompt

In `src/hassette/execution_mode.py`, add (copying the authoritative code block from
the design doc's `## Architecture` section verbatim, adjusting only imports):

1. `STALL_THRESHOLD_SECONDS: float = 60.0` with a docstring stating it is the single
   source of truth, imported by both subsystems and passed explicitly as `threshold=`
   at each call site — never used as a helper default argument (a default binds at
   definition time and would defeat test patches).
2. `async def run_with_stall_watch(invoke, warn, threshold)` —
   `warn: Callable[[float], None]`, `threshold: float` (required, no default). Arms
   the watchdog with `asyncio.get_running_loop().call_later(threshold, warn, threshold)`
   so `warn` receives the armed threshold; `await invoke()`; cancel the watchdog in
   `finally`.
3. `async def run_through_guard(guard, spawn, pending_done, invoke, warn, spawn_name, threshold)`
   — `spawn: Callable[..., asyncio.Task[None]]` (a bare callable, NOT a `TaskBucket`),
   `warn: Callable[[float], None]`, `threshold: float` required. Body: create a
   future, add to `pending_done`, define `resolve_done` (discard + set_result),
   define `run_and_track` (spawns `run_with_stall_watch(invoke, warn, threshold)` via
   `spawn(coro, name=spawn_name)` and adds a done-callback calling `resolve_done`),
   `outcome = await guard.run(run_and_track)`, resolve inline + return on
   `Outcome.SUPPRESSED`/`Outcome.DROPPED`, else `await done`.
4. `def drain_pending_done(pending_done)` — resolve every unresolved future in the
   set (iterate `list(pending_done)`, discard, `set_result(None)` if not done).

Docstrings must:
- State that `run_through_guard` installs a live done-callback that mutates
  `pending_done` after returning (it is NOT side-effect-free), and that the caller
  must call `drain_pending_done` after every `guard.release()`.
- Carry the `drain_next`/`release` interleave caveat (a task spawned by `drain_next`
  concurrently with `release()` may detach rather than cancel), note it applies to
  every caller reaching release through a detached spawn (both bus and scheduler),
  and reference that it is out of scope here, tracked in issue #1099.

Inside `run_and_track`, call the spawn callable with `name` as a **keyword**
argument — `spawn(coro, name=spawn_name)`, never `spawn(coro, spawn_name)` —
because callers wrap `TaskBucket.spawn`, whose `name` is keyword-only
(`spawn(coro, *, name=...)`). Copy the authoritative `## Architecture` code block
rather than retyping it.

Add no `assert` statements. Keep the module's imports to stdlib +
`hassette.types.enums` only — do NOT import `TaskBucket`, `bus.*`, `core.*`, or
`scheduler.*`. `run_through_guard` references `ExecutionModeGuard` (already defined in
this module) and `Outcome` (already imported).

Run the full bus and scheduler suites to confirm the additive change breaks nothing.

## Focus

- `execution_mode.py` currently imports only `asyncio`, `collections.deque`,
  `collections.abc.Callable`, `logging`, `typing.Final`, and
  `hassette.types.enums.{ExecutionMode, Outcome}` (lines 13-19). You will need
  `Awaitable` from `collections.abc` for the new signatures — add it to the existing
  `collections.abc` import, do not introduce a `typing` import for it.
- `ExecutionModeGuard` is defined in this same module (`:34`); `Outcome.SUPPRESSED` /
  `Outcome.DROPPED` already available via the enums import.
- `DEFAULT_QUEUE_DEPTH` (`:23`) already sets the precedent for a shared scalar living
  here — place `STALL_THRESHOLD_SECONDS` near it.
- This module is verified leaf-pure by the module-boundary linter
  (`tools/check_*` pre-push hooks) — keep it that way.
- Do not touch `bus/listeners.py` or `scheduler_service.py` in this task.

## Verify

- [ ] FR#1: `run_with_stall_watch(invoke, warn, threshold)` exists in
      `execution_mode.py`, runs `invoke`, and arms a `threshold`-second watchdog that
      is cancelled on settle.
- [ ] FR#2: `run_with_stall_watch` passes the armed `threshold` into `warn`
      (`call_later(threshold, warn, threshold)`; `warn: Callable[[float], None]`).
- [ ] FR#3: `run_through_guard(...)` exists, bridges completion via a future added to
      and resolved on `pending_done`, and settles inline on `SUPPRESSED`/`DROPPED`.
- [ ] FR#4: `run_through_guard` takes a bare `spawn` callable; `execution_mode.py`
      imports no `TaskBucket`/`bus`/`core`/`scheduler` symbol.
- [ ] FR#5: `drain_pending_done(pending_done)` exists and resolves every unresolved
      future in the set.
- [ ] FR#6: `STALL_THRESHOLD_SECONDS` is defined in `execution_mode.py` with no
      helper using it as a default argument.
- [ ] AC#6: `execution_mode.py`'s import list contains no `bus`, `core`, or
      `scheduler` import (grep + module-boundary linter clean); existing suites pass.
