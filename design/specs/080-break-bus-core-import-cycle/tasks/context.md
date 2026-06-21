# Context: Break the bus→core→bus runtime import cycle

## Problem & Motivation

`src/hassette/core/commands.py` and `src/hassette/bus/invocation.py` form a
runtime import cycle. `core/commands.py` runtime-imports `Listener` (bus),
`Event` (events), and `ScheduledJob` (scheduler) to type the `InvokeHandler` /
`ExecuteJob` dataclass fields (`core → bus`/`events`/`scheduler`), while
`bus/invocation.py:10` runtime-imports `InvokeHandler` back from `core.commands`
(`bus → core`). `bus → core` is the wrong direction — `core` sits above the
service layer, the same layering `api-no-core` and `web-no-core` already
enforce. The cycle resolves today only because neither module references the
other's names at import-evaluation time; it is one expression away from an
`ImportError`. This is the blocking prerequisite for #1091 (the broader
`hassette._*` lint ratchet) and feeds #1079 (full DAG enforcement). Tracking
issue: **#1089**.

## Visual Artifacts

None.

## Key Decisions

1. **Move `InvokeHandler`/`ExecuteJob` to a new root-level leaf
   `src/hassette/commands.py`** — sibling to the existing `execution_mode.py`
   leaf. Its only runtime `hassette.*` import is `hassette.types`.
2. **The actual cycle-breaker is the `TYPE_CHECKING` demotion**, not the module
   location. `Listener`, `Event`, and `ScheduledJob` move into a `TYPE_CHECKING`
   block and their field annotations become string literals. The target file
   already does exactly this for `BusErrorHandlerType`/`SchedulerErrorHandlerType`
   (lines 12-13, 45, 86) — extend that established pattern. A neutral module that
   still runtime-imports `Listener`/`ScheduledJob` would merely relocate the cycle.
3. **`build_tracked_invoke_fn` stays in `bus/invocation.py`** — only its
   `InvokeHandler` import source changes to `hassette.commands` (a downward
   import). Relocating the builder into `core/` was rejected: `bus/duration_hold.py:131`
   calls it, which would create a fresh `bus → core` edge.
4. **Lock in the break with a `bus-no-core` rule** in
   `tools/check_module_boundaries.py`, mirroring `api-no-core`. Reconnaissance
   confirmed `bus/invocation.py:10` is the *only* runtime `bus → core` import, so
   the rule passes immediately after the move. This is self-proving: revert the
   `invocation.py` fix and the guard goes red.
5. **No `__init__.py` re-exports exist** for these symbols (verified) — no
   re-export surface to re-point.

## Constraints & Anti-Patterns

- **No compatibility shim.** Migrate all consumers and delete
  `src/hassette/core/commands.py` in the same change. No re-export stub left in
  `core` (per "Migrate Callers Then Delete Legacy APIs").
- **The new module must stay a dependency-free leaf.** Runtime `hassette.*`
  imports limited to `hassette.types`. Must not runtime-import `bus`,
  `scheduler`, `core`, `events`, `app`, or `web`.
- **No behavior change.** Relocation + annotation-form change only. Field order,
  defaults, docstrings, and frozen-dataclass semantics stay identical.
- **Out of scope:** the broader `hassette._*` import lint (#1091); the
  `scheduler ↔ core` and `state_manager ↔ core` cycles (#1079); `pytest-archon`
  or full layer-DAG encoding.

## Design Doc References

- `## Architecture` — the move, the TYPE_CHECKING demotion, why the leaf is at
  root, the lock-in guard, and the consumer migration list.
- `## Replacement Targets` — `core/commands.py` is deleted, no shim.
- `## Test Strategy` — boundary-tool self-test adaptation + new `bus-no-core`
  tests; the ~18 test files needing an import-path swap.
- `## Impact` — full changed-files inventory, behavioral invariants, blast radius.

## Convention Examples

### TYPE_CHECKING string-annotation pattern (already in the target file)

**Source:** `src/hassette/core/commands.py`

```python
import typing
from dataclasses import dataclass

if typing.TYPE_CHECKING:
    from hassette.types.types import BusErrorHandlerType, SchedulerErrorHandlerType


@dataclass(frozen=True)
class InvokeHandler:
    app_level_error_handler: "BusErrorHandlerType | None" = None
```

The fix extends this to `Listener`, `ScheduledJob`, and `Event`.

### Neutral leaf-module contract

**Source:** `src/hassette/execution_mode.py` (module docstring)

```
The module stays a dependency-free leaf (stdlib + hassette.types.enums)
so neither subsystem has to import the other.
```

### Directional boundary rule

**Source:** `tools/check_module_boundaries.py`

```python
Rule(
    name="api-no-core",
    applies=lambda layer: layer == "api",
    forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
    reason="api must not import core at runtime; core sits above the service layer (#1079)",
)
```
