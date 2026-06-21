# Design: Break the bus→core→bus runtime import cycle

**Date:** 2026-06-20
**Status:** archived
**Scope-mode:** hold
**Issue:** #1089 (the `#1089` citations in the boundary-tool `reason=` string and
docstring refer to this tracking issue)

## Problem

`core/commands.py` and `bus/invocation.py` form a runtime import cycle at the
subpackage level:

- `core/commands.py:7,8,9` runtime-imports `Listener` (from `bus`), `Event`
  (from `events`), and `ScheduledJob` (from `scheduler`) to type the
  `InvokeHandler.listener` / `InvokeHandler.event` / `ExecuteJob.job` dataclass
  fields → `core → bus`, `core → events`, `core → scheduler`. All three are
  demoted to `TYPE_CHECKING` by this change.
- `bus/invocation.py:10` runtime-imports `InvokeHandler` back from
  `core.commands` → `bus → core`.

`bus → core` is the wrong direction: `core` sits above the service layer
(`api`/`bus`/`scheduler`/`state_manager`), the same layering that
`api-no-core` and `web-no-core` already enforce. The cycle resolves today only
because neither module references the other's names at import-evaluation time —
it is one module-level expression away from an `ImportError`. The
boundary-guard tool documents this cycle in a comment but cannot enforce
against it while it exists.

This is the blocking prerequisite for #1091 (which re-enables the `core↔bus`
boundary rule and adds the broader `hassette._*` lint ratchet) and feeds the
larger DAG-enforcement effort in #1079. The 2026-06-19 design audit's headline
framing is "missing ratchet": boundary smells recur across subsystems because
nothing in the build stops them.

## Goals

- No runtime `bus → core` import remains anywhere under `src/hassette/bus/`.
- The subpackage import graph no longer contains the `bus ↔ core` cycle.
- The break is locked in by a `bus-no-core` rule in
  `tools/check_module_boundaries.py`, so it cannot silently re-accrete before
  #1091 lands.
- No behavior change: telemetry, dispatch, timeout, and error-handler
  resolution are byte-for-byte identical.

## Non-Goals

- The broader `hassette._*` private-attribute import lint (owned by #1091).
- Breaking the other documented runtime cycles — `scheduler ↔ core`
  (`SchedulerService`), `state_manager ↔ core` (`StateProxy`) — which import
  real core logic, not data, and are tracked under #1079.
- Adopting `pytest-archon` or encoding the full layer DAG (#1079/#633).

## User Scenarios

### Framework maintainer: works on bus or core internals
- **Goal:** add or move code without silently reintroducing a layer violation
- **Context:** editing dispatch, invocation, or command-executor code

#### Maintainer adds a runtime `bus → core` import

1. **Adds `from hassette.core.X import Y` to a file under `bus/`**
   - Sees: `check_module_boundaries.py` fails in pre-push/CI with a
     `bus-no-core` violation naming the file, line, and reason.
   - Decides: relocate the dependency below the boundary, or use a
     `TYPE_CHECKING` import if it is type-only.
   - Then: the cycle stays broken; the violation never reaches `main`.

## Functional Requirements

- **FR#1** `InvokeHandler` and `ExecuteJob` are importable from a new neutral
  leaf module whose only runtime `hassette.*` import is `hassette.types`.
- **FR#2** No production or test code imports `InvokeHandler`/`ExecuteJob` from
  `hassette.core.commands`; that module no longer exists.
- **FR#3** No file under `src/hassette/bus/` performs a runtime (non-`TYPE_CHECKING`)
  import of `hassette.core` or any `hassette.core.*` submodule.
- **FR#4** `tools/check_module_boundaries.py` flags a runtime `bus → core`
  import as a `bus-no-core` violation.
- **FR#5** `tools/check_module_boundaries.py` exits clean (zero violations) on
  the post-fix tree.

## Edge Cases

- **Import form is uniform.** Verified: all consumers — the 4 production files
  and all ~18 test files — use the absolute form `from hassette.core.commands
  import ...` today. There are no relative `from .commands import ...` forms to
  special-case, so the migration is a uniform literal substitution
  `hassette.core.commands` → `hassette.commands`.
- **`TYPE_CHECKING` annotations must stay string-form.** `InvokeHandler.listener`
  / `ExecuteJob.job` / `InvokeHandler.event` become string annotations backed by
  `TYPE_CHECKING` imports. These dataclasses are plain `@dataclass(frozen=True)`
  (no Pydantic, no `get_type_hints()` at runtime — verified), so unresolved
  string annotations are safe.
- **The `__init__.py` re-export surface.** If `hassette/__init__.py` or
  `hassette/core/__init__.py` re-exports `InvokeHandler`/`ExecuteJob`, the
  re-export must follow the symbol to its new home (or be removed if unused).
- **Boundary-tool self-test drift.** `test_other_cross_layer_imports_not_yet_governed`
  currently asserts `bus → core` is allowed; the new rule flips that assertion.

## Acceptance Criteria

- **AC#1** `python tools/check_module_boundaries.py` exits 0 on the post-fix
  tree, reporting one additional rule. (maps FR#3, FR#5)
- **AC#2** Reverting only the `invocation.py` import fix (leaving the new
  `bus-no-core` rule) makes the guard fail with a `bus-no-core` violation —
  the rule is self-proving. (maps FR#4)
- **AC#3** `grep -rn "core.commands" src/ tests/` returns no production or test
  hits after migration. (maps FR#2)
- **AC#4** A fresh `python -c "import hassette"` and the full unit+integration
  suite pass — no `ImportError`, no behavior change. (maps FR#1, FR#2)
- **AC#5** `uv run pyright` is clean. (maps FR#1)

## Key Constraints

- **Do not introduce a compatibility shim.** Per "Migrate Callers Then Delete
  Legacy APIs", migrate all consumers and delete the old `core/commands.py` in
  the same change. No re-export stub left in `core` for back-compat.
- **The neutral module must remain a dependency-free leaf.** Its only runtime
  `hassette.*` import is `hassette.types`. It must not runtime-import `bus`,
  `scheduler`, `core`, `events`, `app`, or `web` — mirroring the
  `execution_mode.py` leaf contract. (`events` is currently a runtime import
  for the `Event` annotation; it is demoted to `TYPE_CHECKING`.)
- **No behavior change.** This is a relocation + annotation-form change only.
  Field order, defaults, docstrings, and dataclass semantics stay identical.

## Dependencies and Assumptions

- Assumes `hassette.types` (`AsyncHandlerType`, `SourceTier`) stays the lowest
  layer — already true; it has no `hassette.*` runtime imports.
- No external systems, services, or teams. Pure internal structural change.

## Architecture

### The move

Create `src/hassette/commands.py` — a new root-level neutral leaf, sibling to
the existing `src/hassette/execution_mode.py`. Move `InvokeHandler` and
`ExecuteJob` there verbatim, with one change: the field-type imports for
`Listener` (bus), `ScheduledJob` (scheduler), and `Event` (events) move into a
`TYPE_CHECKING` block, and their field annotations become string literals.

The file already demonstrates this exact pattern: `BusErrorHandlerType` /
`SchedulerErrorHandlerType` are `TYPE_CHECKING`-imported (lines 12-13) and used
as string annotations (lines 45, 86). The change extends that established
pattern to the remaining three types. After the move, the module's only runtime
`hassette.*` import is `hassette.types`.

**Why root-level leaf, not the issue's literal options.** The issue proposed
"move to a neutral module (e.g. `execution/commands.py`)" *or* "relocate
`bus/invocation.py` into `core/`". Both are weaker:

- A neutral `commands.py` that *still* runtime-imports `Listener`/`ScheduledJob`
  does not break the cycle — it relocates it (`bus → newmodule → bus/scheduler`).
  The `TYPE_CHECKING` demotion is the actual fix; the module location is
  secondary. Placing it at root as a leaf (like `execution_mode.py`) makes the
  leaf contract obvious and matches the precedent PR #1102 set.
- Relocating `bus/invocation.py` into `core/` fails, because
  `bus/duration_hold.py:131` calls `build_tracked_invoke_fn` — moving the
  builder to `core` would create a fresh `bus → core` edge from `duration_hold`.

`build_tracked_invoke_fn` therefore stays in `bus/invocation.py`; only its
`InvokeHandler` import source changes to `hassette.commands` (a downward import,
allowed). This is the minimal diff that respects the layer DAG.

### The lock-in guard

Reconnaissance confirmed `bus/invocation.py:10` is the **only** runtime
`bus → core` import in the entire `bus/` subpackage. So once the move lands, a
`bus-no-core` rule passes immediately. Add it to `RULES` in
`tools/check_module_boundaries.py`, structured identically to the existing
`api-no-core` rule:

```python
Rule(
    name="bus-no-core",
    applies=lambda layer: layer == "bus",
    forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
    reason="bus must not import core at runtime; core sits above the service layer (#1089)",
)
```

Update the module docstring (lines 13-24): move `bus`↔`core` out of the
"remaining runtime cycles" paragraph into the enforced-boundaries list, and
reference #1089.

### Consumers to migrate (import-path only — symbol names unchanged)

Production:
- `bus/invocation.py:10` — `InvokeHandler`
- `core/command_executor.py:21` — `ExecuteJob, InvokeHandler`
- `core/scheduler_service.py:13` — `ExecuteJob`
- `test_utils/harness.py:25` — `ExecuteJob, InvokeHandler`

Tests (~18 files importing `core.commands`): mechanical literal substitution
`hassette.core.commands` → `hassette.commands`. This is a pure module-path
string swap (the symbols `InvokeHandler`/`ExecuteJob` do not rename), suitable
for a single bulk find/replace across `src/` and `tests/`, verified by AC#3's
grep returning zero hits.

## Replacement Targets

- `src/hassette/core/commands.py` — **deleted** after its two dataclasses move
  to `src/hassette/commands.py`. No shim, no re-export left behind. Any
  `core/__init__.py` or `hassette/__init__.py` re-export of these symbols is
  re-pointed to the new module or removed if it has no external consumers.

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

The fix extends this to `Listener`, `ScheduledJob`, and `Event` — moving their
imports under `TYPE_CHECKING` and quoting their annotations.

### Neutral leaf-module contract

**Source:** `src/hassette/execution_mode.py` (module docstring)

```
The module stays a dependency-free leaf (stdlib + hassette.types.enums)
so neither subsystem has to import the other.
```

`src/hassette/commands.py` adopts the same contract: stdlib + `hassette.types`
only at runtime.

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

The new `bus-no-core` rule mirrors this exactly.

## Test Strategy

### Existing Tests to Adapt
- `tests/unit/tools/test_check_module_boundaries.py:133`
  (`test_other_cross_layer_imports_not_yet_governed`) — currently asserts
  `check_source("from hassette.core import Hassette\n", "bus") == []`. The new
  rule flips this. Re-point the "not yet governed" example to a layer that
  stays ungoverned by this PR — `state_manager` importing `core` (the
  `state_manager ↔ core` cycle is tracked under #1079 and is explicitly out of
  scope here, so it remains a valid "allowed today" stand-in at merge time).
- The ~18 test files importing `core.commands` (e.g.
  `tests/unit/bus/test_invocation.py`, `tests/unit/core/test_command_executor.py`,
  `tests/integration/test_command_executor.py`) — import-path swap only;
  assertions unchanged.

### New Test Coverage
- `test_check_module_boundaries.py`: add a positive `bus-no-core` test asserting
  a runtime `from hassette.core import X` under layer `bus` is flagged with the
  `bus-no-core` message (maps FR#4) — mirroring `test_production_import_of_test_utils_flagged`.
- `test_check_module_boundaries.py`: add a `TYPE_CHECKING`-exempt case for a
  `bus → core` import to confirm type-only imports are not flagged (maps FR#3) —
  the existing `test_type_checking_import_exempt` covers the mechanism; one
  `bus`-layer variant pins the new rule's exemption.
- `test_real_src_files_pass` (existing parametrized test) already asserts the
  guard stays green on every real `src/` file — it covers AC#1 with no change
  once `invocation.py` is migrated.

### Tests to Remove
No tests to remove. The boundary-tool self-test is adapted, not deleted.

## Documentation Updates

- `tools/check_module_boundaries.py` module docstring — move `bus`↔`core` from
  the "remaining runtime cycles" list to the enforced-boundaries list; cite
  #1089. (Already covered under Architecture.)
- No `docs/` site pages, README, or CLI help reference `InvokeHandler` /
  `ExecuteJob` / `core.commands` — these are internal framework plumbing with no
  user-facing surface (verified: not in `PUBLIC_MODULES`). No docs-site update
  required.

## Impact

### Changed Files
- `src/hassette/commands.py` — **create**: new root-level leaf holding
  `InvokeHandler` + `ExecuteJob` with `TYPE_CHECKING` field-type imports.
- `src/hassette/core/commands.py` — **delete**: contents moved out.
- `src/hassette/bus/invocation.py` — **modify**: import `InvokeHandler` from
  `hassette.commands`; removes the last runtime `bus → core` edge.
- `src/hassette/core/command_executor.py` — **modify**: import path swap.
- `src/hassette/core/scheduler_service.py` — **modify**: import path swap.
- `src/hassette/test_utils/harness.py` — **modify**: import path swap.
- `src/hassette/core/__init__.py` / `src/hassette/__init__.py` — **modify (if
  applicable)**: re-export re-pointed or removed.
- `tools/check_module_boundaries.py` — **modify**: add `bus-no-core` rule;
  update docstring.
- `tests/unit/tools/test_check_module_boundaries.py` — **modify**: adapt the
  "not yet governed" test; add `bus-no-core` positive + TYPE_CHECKING-exempt
  tests.
- ~18 `tests/**` files importing `core.commands` — **modify**: import path swap.

### Behavioral Invariants
- Dispatch, telemetry recording, timeout resolution, and error-handler fallback
  all behave identically — the command dataclasses' fields, defaults, and order
  are unchanged. All existing `command_executor`, `bus`, and `scheduler` tests
  must keep passing unmodified (aside from the import-path line).
- `hassette.commands.InvokeHandler` / `ExecuteJob` remain plain frozen
  dataclasses constructed positionally/by-keyword exactly as before.

### Blast Radius
- Internal only. No public API, CLI, HTTP, or DB surface changes. App authors
  never import these symbols. Limited to framework-internal dispatch plumbing
  and the boundary-guard tooling.

## Open Questions

None.
