---
task_id: "T01"
title: "Move command dataclasses to a neutral leaf module"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#3", "AC#4", "AC#5"]
---

## Summary

Break the `bus → core` half of the runtime import cycle by relocating the
`InvokeHandler` and `ExecuteJob` command dataclasses out of `core/` into a new
root-level leaf module `src/hassette/commands.py`, and by demoting their
`bus`/`scheduler`/`events` field-type imports to `TYPE_CHECKING` string
annotations. After this task, no file under `src/hassette/bus/` imports
`hassette.core` at runtime, the cycle is gone, and `import hassette` plus the
full test suite still pass with zero behavior change.

## Target Files

- create: `src/hassette/commands.py`
- delete: `src/hassette/core/commands.py`
- modify: `src/hassette/bus/invocation.py`
- modify: `src/hassette/core/command_executor.py`
- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/test_utils/harness.py`
- modify: `tests/integration/bus/test_bus.py`
- modify: `tests/integration/telemetry/test_framework_telemetry.py`
- modify: `tests/integration/test_command_executor.py`
- modify: `tests/integration/test_command_executor_error_handler.py`
- modify: `tests/integration/test_dispatch_unification.py`
- modify: `tests/integration/test_scheduler.py`
- modify: `tests/integration/test_thread_leaked_observability.py`
- modify: `tests/unit/bus/test_invocation.py`
- modify: `tests/unit/core/test_bus_service_error_handler.py`
- modify: `tests/unit/core/test_bus_service_timeout.py`
- modify: `tests/unit/core/test_command_executor.py`
- modify: `tests/unit/core/test_command_executor_error_handler.py`
- modify: `tests/unit/core/test_command_executor_execution_id.py`
- modify: `tests/unit/core/test_command_executor_pipeline.py`
- modify: `tests/unit/core/test_execution_timeout.py`
- modify: `tests/unit/core/test_scheduler_service_error_handler.py`
- modify: `tests/unit/core/test_scheduler_service_timeout.py`
- modify: `tests/unit/test_source_tier_models.py`
- read: `src/hassette/execution_mode.py`
- read: `design/specs/080-break-bus-core-import-cycle/design.md`

## Prompt

Implement the module move and import migration described in the design doc's
`## Architecture` ("The move" and "Consumers to migrate") and
`## Replacement Targets` sections.

1. **Create `src/hassette/commands.py`.** Move the `InvokeHandler` and
   `ExecuteJob` `@dataclass(frozen=True)` classes from
   `src/hassette/core/commands.py` into this new file **verbatim** — same field
   order, same defaults, same docstrings, same `frozen=True`. The only changes:
   - Move the imports of `Listener` (`from hassette.bus.listeners import Listener`),
     `ScheduledJob` (`from hassette.scheduler.classes import ScheduledJob`), and
     `Event` (`from hassette.events.base import Event`) into the existing
     `if typing.TYPE_CHECKING:` block.
   - Convert the field annotations that use those types to string literals:
     `listener: "Listener"`, `event: "Event[Any]"`, `job: "ScheduledJob"`.
     Follow the pattern already used in the same file for
     `app_level_error_handler: "BusErrorHandlerType | None"`.
   - Keep the runtime imports of `hassette.types` (`AsyncHandlerType`,
     `SourceTier`) and stdlib (`typing`, `dataclasses`, `Any`) — these are the
     only runtime imports the module needs.
   - Update the in-body docstring on `InvokeHandler.app_level_error_handler`
     that references `bus/invocation.py` only if its wording becomes inaccurate
     (the builder location does not change, so it should stay correct).

2. **Delete `src/hassette/core/commands.py` entirely.** No re-export shim in
   `core/`. (Verified: nothing re-exports these symbols from any `__init__.py`.)

3. **Re-point every importer** from `hassette.core.commands` to
   `hassette.commands` — a pure module-path swap; the symbol names
   `InvokeHandler`/`ExecuteJob` do not change. Production consumers:
   `src/hassette/bus/invocation.py:10`, `src/hassette/core/command_executor.py:21`,
   `src/hassette/core/scheduler_service.py:13`, `src/hassette/test_utils/harness.py:25`.
   Plus the 18 test files listed in Target Files. The cleanest approach is a
   single literal substitution of `hassette.core.commands` → `hassette.commands`
   across `src/` and `tests/`, then verify.

4. **Verify the break and zero behavior change:**
   - `python -c "import hassette"` succeeds (no `ImportError`).
   - `grep -rn "core.commands" src/ tests/` returns nothing.
   - `python tools/check_module_boundaries.py` exits 0.
   - `uv run pyright` is clean.
   - Run the affected suites: `uv run pytest tests/unit/core tests/unit/bus
     tests/integration/test_command_executor.py tests/integration/test_scheduler.py
     tests/integration/bus -q` (and the broader unit/integration suites per
     CLAUDE.md before commit). All green.

Do not add the `bus-no-core` guard rule in this task — that is T02.

## Focus

- **The file already demonstrates the pattern.** `src/hassette/core/commands.py`
  lines 12-13 (`if typing.TYPE_CHECKING:` importing the error-handler types) and
  the string annotations on lines 45/86 are the exact shape to extend. You are
  generalizing what's already there to three more types.
- **Safe to use string annotations:** these are plain frozen dataclasses, not
  Pydantic, and nothing calls `get_type_hints()` on them at runtime (verified).
  Unresolved string annotations will not break anything.
- **`build_tracked_invoke_fn` stays in `bus/invocation.py`.** Only its
  `InvokeHandler` import line changes. Do not relocate the builder — `bus/duration_hold.py:131`
  calls it and a move to `core/` would recreate a `bus → core` edge.
- **All imports are absolute today** (`from hassette.core.commands import ...`),
  in both the 4 production consumers and all 18 test files — no relative-import
  forms to special-case. The literal substitution is uniform.
- **`command_executor.py` uses `match cmd: case InvokeHandler():`** — structural
  pattern matching on the class. The move preserves class identity (single
  definition), so the `match` keeps working. Just ensure there is exactly one
  definition of each dataclass after the move (the old file is deleted).
- **Blast radius:** `core/command_executor.py` and `test_utils/harness.py` are
  imported widely; a botched edit there fails many tests fast, which is good
  signal. Run the full unit+integration suite before declaring done.

## Verify

- [ ] FR#1: `InvokeHandler` and `ExecuteJob` import successfully from
  `hassette.commands`, and that module's only runtime `hassette.*` import is
  `hassette.types` (no runtime `bus`/`scheduler`/`events`/`core` import).
- [ ] FR#2: `grep -rn "core.commands" src/ tests/` returns zero hits and
  `src/hassette/core/commands.py` no longer exists.
- [ ] FR#3: no file under `src/hassette/bus/` has a runtime (non-`TYPE_CHECKING`)
  import of `hassette.core` or `hassette.core.*`. Confirm directly (the
  `bus-no-core` rule does not exist yet — it is added in T02, so a passing
  boundary tool here does NOT prove this): `grep -rn "hassette.core" src/hassette/bus/`
  shows any matches are `import` lines inside `TYPE_CHECKING` blocks only
  (ignore comment/docstring mentions of the word), and `bus/invocation.py`
  imports `InvokeHandler` from `hassette.commands`, not `hassette.core.commands`.
- [ ] AC#3: `grep -rn "core.commands" src/ tests/` returns no production or test
  hits.
- [ ] AC#4: `python -c "import hassette"` succeeds and the unit+integration
  suites pass with no failures.
- [ ] AC#5: `uv run pyright` reports no errors.
