# Context: Break Three Subpackage Import Cycles via Dependency Inversion

## Problem & Motivation
Hassette's subpackages are meant to form a layered DAG, but the runtime import graph still contains cycles, which blocks full DAG / cycle enforcement (#633) and leaves banned-pattern workarounds in place. PRs #1097 and #1103 already broke most cycles; both `check_module_boundaries.py` and `check_lazy_imports.py` pass clean today. Three runtime cycles remain with a clear, low-risk fix: `core ↔ scheduler`, `core ↔ state_manager`, and `resources ↔ task_bucket`. The two core cycles are live top-level imports that resolve only by load-order luck; the resources one is a lazy function-body import (the project bans these outside annotated cycle-breaks). Breaking all three makes the intended layering mechanically checkable and retires the `resources/base.py` lazy import.

## Visual Artifacts
None.

## Key Decisions
1. **Protocol inversion for the two core cycles.** Define `SchedulerServiceProtocol` and a read-only `StateReader` in the `types` leaf layer. Consumers (`Scheduler`, `StateManager`/`DomainStates`) depend on the protocol; `SchedulerService`/`StateProxy` stay in `core` and satisfy it structurally. Chosen over relocating the classes because `SchedulerService`/`StateProxy` each import 3–4 `core` sibling services that cannot move down — relocation would convert two clean cycles into several new upward violations.
2. **Both consumers already import `hassette.types` at runtime** (`scheduler.py:76`, `state_manager.py:15`), so adding the protocol to that import introduces no new edge. The concrete class was only imported for the type annotation; the instance already flows through `self.hassette.scheduler_service` / `self.hassette.state_proxy`.
3. **Factory/marker inversion for `resources ↔ task_bucket`.** Replace the `type(self) is TaskBucket` identity check with an `is_task_bucket` ClassVar marker, and replace the in-`__init__` `TaskBucket(...)` construction with a factory that `task_bucket` registers on `Resource` at import. The high layer injects into the low layer instead of the low layer reaching up.
4. **Each fix is self-proving.** Each cycle gets a rule in `tools/check_module_boundaries.py` (`scheduler-no-core`, `state_manager-no-core`, `resources-no-task_bucket`) so reverting the fix fails the guard.
5. **Protocols are plain `Protocol`** (not `@runtime_checkable`) — nothing does `isinstance` against them, unlike `TriggerProtocol`.

## Constraints & Anti-Patterns
- **No `from __future__ import annotations`** (project ban — breaks Pydantic/pyright). Annotations evaluate at definition time, so the protocol must be a real runtime name in each consumer.
- **No runtime lazy (function-body) imports.** `TYPE_CHECKING`-guarded imports are the sanctioned mechanism for annotation-only needs and are exempt from the boundary checker.
- **This is a refactor — no smuggled behavior changes.** `TaskBucket` ownership, scheduler dispatch, and state-read semantics must be unchanged.
- **Out of scope:** `conversion ↔ models` (#892 — independent, on the hot path, has open design questions), full DAG enforcement (#633), and the non-cycle lazy imports in `__main__.py`, `conversion/validation.py`, `app/utils.py`, `utils/app_utils.py`.

## Design Doc References
- `## Architecture` — the protocol home (`types/types.py`), Step 1 (resources↔task_bucket), Step 2 (the two core cycles); includes the exact protocol stubs.
- `## Convention Examples` — `TriggerProtocol` shape, the boundary `Rule` pattern, the type-via-protocol/instance-via-accessor pattern.
- `## Test Strategy` — which tests to adapt (the boundary-checker stand-in test), new coverage (protocol conformance, `DomainStates` against a fake `StateReader`, the rule tests).
- `## Impact → Changed Files` — the file inventory (note: also update `state_manager/state_manager.pyi`, found in the plan gap check).

## Convention Examples

### Protocol defined in the `types` leaf layer
**Source:** `src/hassette/types/types.py`
```python
@runtime_checkable
class TriggerProtocol(Protocol):
    """Protocol for defining triggers."""
    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime: ...
    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime | None: ...
    # ...
```
The new protocols follow this shape but stay plain `Protocol` (no `@runtime_checkable`) since nothing isinstance-checks them.

### Boundary rule (append to `RULES`)
**Source:** `tools/check_module_boundaries.py`
```python
Rule(
    name="api-no-core",
    applies=lambda layer: layer == "api",
    forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
    reason="api must not import core at runtime; core sits above the service layer (#1079)",
),
```
`scheduler-no-core` and `state_manager-no-core` are exact copies with the layer name and reason swapped; `resources-no-task_bucket` swaps the `forbids` target to `hassette.task_bucket`.

### Type via protocol, instance via accessor
**Source:** `src/hassette/scheduler/scheduler.py`
```python
class Scheduler(Resource):
    scheduler_service: SchedulerService  # → SchedulerServiceProtocol

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.scheduler_service = self.hassette.scheduler_service  # instance from the accessor, not the import
```
The annotation is the only reason the concrete class is imported; the runtime value already flows through `self.hassette`. This is why dropping the import is safe.
