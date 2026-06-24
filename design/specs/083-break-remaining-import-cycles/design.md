# Design: Break Three Subpackage Import Cycles via Dependency Inversion

**Date:** 2026-06-22
**Status:** archived
**Scope-mode:** reduce
**Research:** design/research/2026-06-22-break-import-cycles/research.md

## Problem

Hassette's subpackages are meant to form a layered DAG (`types` at the bottom, `core` above the service layer, `app`/`web` on top). `tools/check_module_boundaries.py` enforces individual edges of that DAG, but it cannot enforce the full layer map or add cycle detection while the runtime import graph still contains cycles. Issue #633 (full DAG enforcement) is blocked on removing those cycles; this work removes three of the four remaining ones.

PRs #1097 and #1103 already broke the `bus`/`api`/`web ↔ core` and `utils ↔ events` cycles. Both `check_module_boundaries.py` and `check_lazy_imports.py` pass clean today. Four runtime cycles remain; this design addresses the three with a clear, low-risk fix:

- `core ↔ scheduler` — `scheduler/scheduler.py:74` imports `SchedulerService` from `core` (a live top-level import, not even lazy — one module-level reference away from `ImportError`).
- `core ↔ state_manager` — `state_manager/state_manager.py:10` imports `StateProxy` from `core` (same shape).
- `resources ↔ task_bucket` — `resources/base.py:145` lazy-imports `TaskBucket` inside `Resource.__init__`.

The fourth cycle, `conversion ↔ models` (#892), is intentionally **out of scope** — see Non-Goals. It is independent of these three and carries real design uncertainty that warrants its own focused pass.

Each in-scope cycle represents either a banned-pattern workaround (the project forbids runtime lazy imports outside annotated cycle-breaks) or a latent fragility (a top-level cross-package import that only resolves by load-order luck).

## Goals

- The three runtime cycles above are broken; the production runtime import graph between `scheduler`/`state_manager`/`resources` and their targets is acyclic.
- The two core cycles are broken by **protocol inversion**: a `SchedulerServiceProtocol` and a read-only `StateReader` live in the `types` leaf layer; consumers depend on the protocol while `SchedulerService`/`StateProxy` stay in `core` and satisfy it structurally.
- The `resources ↔ task_bucket` cycle is broken by **factory/marker inversion**: `task_bucket` injects its constructor and identity into `resources` instead of `resources` reaching up.
- The cycle-related `# lazy-import:` annotation at `resources/base.py:145` is removed.
- Each newly-cleaned edge is locked in by a self-proving rule in `check_module_boundaries.py` (`scheduler-no-core`, `state_manager-no-core`, `resources-no-task_bucket`) so the break cannot silently re-accrete.
- `check_module_boundaries.py`, `check_lazy_imports.py`, `pyright`, and the unit/integration suite all pass.

## Non-Goals

- **`conversion ↔ models` (#892).** Out of scope. `models/states/base.py:10` imports the conversion registry, used at two real runtime sites: per-subclass self-registration (`__init_subclass__`, line 137) and scalar value coercion in a validator (`TYPE_REGISTRY.convert`, line 175). Breaking it requires inverting registration to a post-load scan (no such scan exists today) and relocating or inverting the scalar conversion — two open design questions that need their own investigation. It is independent of the three cycles here and is tracked under #892. The cycle-breaking lazy imports in `conversion/annotation_converter.py:38,40` and `conversion/state_registry.py:90` stay until #892 is done.
- **Full DAG / cycle-detector enforcement (#633).** Expanding `RULES` to the entire L0–L9 map and adding a graph cycle detector is tracked separately. This work is one of its blockers, not its delivery.
- **Removing the other non-cycle lazy imports.** `__main__.py:9` (CLI startup deferral), `conversion/validation.py:77` (post-load validation note), `app/utils.py:8,31,95`, and `utils/app_utils.py:199,354` are out of scope.
- **Changing the public app-author API.** App authors never reference `SchedulerService` or `StateProxy` directly; the protocols are internal wiring types.
- **Changing TaskBucket construction semantics.** Each `Resource` still gets its own default `TaskBucket` exactly as today; only the path by which the base class reaches the class changes.

## User Scenarios

### Framework maintainer: adds an edge that would re-introduce a cycle
- **Goal:** keep the subpackage graph acyclic without having to remember the layer map.
- **Context:** editing `scheduler/`, `state_manager/`, or `resources/` and reaching for a higher-layer symbol.

#### Re-introducing `scheduler → core`
1. **Adds `from hassette.core.scheduler_service import SchedulerService` back to `scheduler/`.**
   - Sees: `check_module_boundaries.py` fails locally (pre-push) and in CI with `scheduler-no-core: imports hassette.core.scheduler_service`.
   - Decides: route through `SchedulerServiceProtocol` instead.
   - Then: the guard stays green only when the protocol is used.

### CI guard: validates the graph on every push
- **Goal:** fail any runtime upward import on the now-clean edges.
- **Context:** `lint.yml` runs `check_module_boundaries.py` and `check_lazy_imports.py`.

#### Verifying a clean tree
1. **Runs both checkers.**
   - Sees: `no module-boundary violations across N import rule(s)` (N raised by the three new rules) and `no un-annotated lazy imports`.
   - Then: the `resources/base.py` lazy annotation no longer exists to be counted.

## Functional Requirements

- **FR#1** `types` defines `SchedulerServiceProtocol` describing the surface `Scheduler` consumes from the scheduler service: `task_bucket` (attribute), `add_job`, `dequeue_job`, `register_removal_callback`, `deregister_removal_callback`, `mark_job_cancelled`, `remove_jobs_by_owner`.
- **FR#2** `types` defines a read-only `StateReader` protocol describing the surface `StateManager`/`DomainStates` consume from the state proxy: `get_state`, `num_domain_states`, `yield_domain_states`, `__contains__`.
- **FR#3** `scheduler/scheduler.py` no longer imports any `hassette.core.*` module at runtime; `Scheduler.scheduler_service` is typed as `SchedulerServiceProtocol` and the instance is still obtained from `self.hassette.scheduler_service`.
- **FR#4** `state_manager/state_manager.py` no longer imports any `hassette.core.*` module at runtime; `DomainStates`/`StateManager` are typed against `StateReader` and the instance is still obtained from `self.hassette.state_proxy`.
- **FR#5** `resources/base.py` no longer imports `hassette.task_bucket` at runtime; the lazy import at line 145 is removed.
- **FR#6** `Resource` still assigns each non-`TaskBucket` instance its own default `TaskBucket` when none is passed, and a `TaskBucket` instance is still its own `task_bucket`.
- **FR#7** `check_module_boundaries.py` gains a `scheduler-no-core` rule and a `state_manager-no-core` rule; both fail when the corresponding package runtime-imports `hassette.core.*`.
- **FR#8** `check_module_boundaries.py` gains a `resources-no-task_bucket` rule that fails when `resources` runtime-imports `hassette.task_bucket`.

## Edge Cases

- **Annotation evaluation.** Without `from __future__ import annotations`, class- and method-level annotations evaluate at definition time. `Scheduler.scheduler_service: SchedulerServiceProtocol` (class body) and `StateManager._state_proxy(self) -> StateReader` (property return type) therefore need the protocol available at runtime — both consumer modules already import `hassette.types` at runtime (`scheduler.py:76`, `state_manager.py:15`), so adding the protocol to that import introduces no new edge.
- **`task_bucket` factory load order.** `Resource.__init__` must reach the `TaskBucket` constructor without importing it. The factory is registered when `hassette.task_bucket` is imported; `Resource` instances are only constructed at Hassette runtime, long after all imports complete. A `Resource` constructed before the factory registers must fail loudly (clear `RuntimeError`), not silently produce a `None` bucket.
- **`TaskBucket` self-identity for subclasses.** `type(self) is TaskBucket` is exact-class today. Replacing it with a `ClassVar` marker (`is_task_bucket`) makes any future `TaskBucket` subclass self-bucket too. No `TaskBucket` subclasses exist in the tree, so behavior is unchanged in practice and the marker semantics are arguably more correct.
- **Protocols are not `runtime_checkable`.** Neither consumer does `isinstance(x, Protocol)` — `SchedulerServiceProtocol` and `StateReader` are plain `Protocol`s (unlike `TriggerProtocol`, which is `@runtime_checkable` because `Scheduler.schedule()` isinstance-checks triggers).

## Acceptance Criteria

- **AC#1** `python tools/check_module_boundaries.py` reports zero violations, with the rule count reflecting the three new rules (FR#7, FR#8).
- **AC#2** `python tools/check_lazy_imports.py` reports no un-annotated lazy imports, and `grep -rn "lazy-import" src/hassette/` no longer lists `resources/base.py` (FR#5).
- **AC#3** `grep` confirms `scheduler/scheduler.py` and `state_manager/state_manager.py` contain no runtime `hassette.core` import (TYPE_CHECKING-only imports are acceptable) (FR#3, FR#4).
- **AC#4** `pyright` passes — `SchedulerService` structurally satisfies `SchedulerServiceProtocol` and `StateProxy` satisfies `StateReader` with no `# pyright: ignore` added for the protocol seams (FR#1, FR#2).
- **AC#5** The full unit/integration suite passes, including a `DomainStates` test that drives a dict-backed fake `StateReader` (proving the public state-access path no longer depends on the concrete `StateProxy`).
- **AC#6** Reverting any one of the new rules' target imports (re-adding the upward import) makes `check_module_boundaries.py` fail — verified by the updated rule tests in `tests/unit/tools/test_check_module_boundaries.py` (FR#7, FR#8).
- **AC#7** A `Resource` subclass still receives its own `TaskBucket`, and a `TaskBucket` is still its own `task_bucket`, verified by existing resource/task-bucket tests passing unchanged (FR#6).

## Key Constraints

- No `from __future__ import annotations` (project ban — breaks Pydantic/pyright runtime introspection). The protocol must be a real runtime name in each consumer, not a stringized escape hatch.
- Runtime lazy (function-body) imports are the debt being removed, not a sanctioned tool. `TYPE_CHECKING`-guarded imports remain the correct mechanism for annotation-only needs and are exempt from the boundary checker.
- This is a refactor: no behavior change may be smuggled in. `TaskBucket` ownership, scheduler dispatch, and state-read semantics must be unchanged.

## Dependencies and Assumptions

- Assumes `hassette.task_bucket` is always imported before the first non-`TaskBucket` `Resource` is constructed at runtime (true: `core` imports the task-bucket package during startup, and `Resource` instances require a live `Hassette`).
- Assumes `SchedulerService`/`StateProxy` import nothing from their consumer packages (`scheduler`/`state_manager`) at runtime — verified: their only references are `TYPE_CHECKING`-guarded.
- Depends on no external systems. #633 depends on this (plus #892); the two are independent of each other.

## Architecture

Sequenced simplest-first so each later step lands on a cleaner base.

### Protocol home: `types/types.py`

Both protocols live in `types/types.py` beside `TriggerProtocol` (`class` at `types.py:154`, `@runtime_checkable` at 153), the existing precedent for a protocol in the leaf layer. `types/types.py` already `TYPE_CHECKING`-imports from `events.base`, `models.states.base`, `scheduler.error_context`, etc. (lines 11–17), so the new protocols add three more names to that same `TYPE_CHECKING` block — `ScheduledJob` (from `scheduler.classes`), `TaskBucket` (from `task_bucket`), and `HassStateDict` (from `events`; not currently imported). No new runtime edge from `types`. Export both from `types/__init__.py` alongside `TriggerProtocol`.

`SchedulerServiceProtocol` — plain `Protocol` (no `isinstance` use):

```python
class SchedulerServiceProtocol(Protocol):
    task_bucket: "TaskBucket"
    async def add_job(self, job: "ScheduledJob") -> None: ...
    def dequeue_job(self, job: "ScheduledJob") -> bool: ...
    def register_removal_callback(self, owner_id: str, callback: "Callable[[ScheduledJob], None]") -> None: ...
    def deregister_removal_callback(self, owner_id: str) -> None: ...
    async def mark_job_cancelled(self, db_id: int) -> None: ...
    def remove_jobs_by_owner(self, owner: str) -> "asyncio.Task[None]": ...
```

`task_bucket` is inherited from `Resource` (`resources/base.py:116`), not declared on `SchedulerService` itself; the protocol relies on that inherited attribute, which is fine because every `SchedulerService` is a `Resource`.

`StateReader` — plain read-only `Protocol`:

```python
class StateReader(Protocol):
    def get_state(self, entity_id: str) -> "HassStateDict | None": ...
    def num_domain_states(self, domain: str) -> int: ...
    def yield_domain_states(self, domain: str) -> "Generator[tuple[str, HassStateDict], Any, None]": ...
    def __contains__(self, entity_id: str) -> bool: ...
```

Signatures are transcribed from the concrete classes (`core/scheduler_service.py`, `core/state_proxy.py`); pyright validates the structural match.

### Step 1 — `resources ↔ task_bucket` (factory/marker inversion)

`Resource.__init__` references the `TaskBucket` class twice at runtime: the identity check `type(self) is TaskBucket` (line 158) and the default construction `TaskBucket(self.hassette, parent=self)` (line 162). Remove the lazy import (line 145) by inverting both:

- **Identity:** add `is_task_bucket: ClassVar[bool] = False` to `Resource`; override `is_task_bucket = True` on `TaskBucket`. Replace the check with `if self.is_task_bucket:`.
- **Construction:** add a class-level factory slot and registrar to `Resource`:
  ```python
  _default_task_bucket_factory: ClassVar["Callable[[Hassette, Resource], TaskBucket] | None"] = None

  @classmethod
  def register_task_bucket_factory(cls, factory: "Callable[[Hassette, Resource], TaskBucket]") -> None:
      cls._default_task_bucket_factory = factory
  ```
  `task_bucket/task_bucket.py` registers at import: `Resource.register_task_bucket_factory(lambda h, owner: TaskBucket(h, parent=owner))`. `Resource.__init__` calls the factory (guarded — raise a clear `RuntimeError` naming the missing import if it is `None`). `TaskBucket` is then referenced in `resources/base.py` only under `TYPE_CHECKING`.

This is the same dependency-inversion shape as the protocol work: the high layer (`task_bucket`) injects its constructor into the low layer (`resources`) instead of the low layer reaching up. Add the `resources-no-task_bucket` rule to lock it in.

### Step 2 — the two core cycles (protocol inversion)

**`core ↔ scheduler`.** In `scheduler/scheduler.py`: drop `from hassette.core.scheduler_service import SchedulerService` (line 74); add `SchedulerServiceProtocol` to the existing `from hassette.types import ...` (line 76); retype the class attribute `scheduler_service: SchedulerServiceProtocol` (line 95). The instance still comes from `self.hassette.scheduler_service` (line 116); every call site is unchanged because `Protocol` is structural. Add the `scheduler-no-core` rule.

**`core ↔ state_manager`.** In `state_manager/state_manager.py`: drop `from hassette.core.state_proxy import StateProxy` (line 10); add `StateReader` to the existing `from hassette.types import ...` (line 15); retype `DomainStates.__init__(self, state_proxy: "StateReader", ...)` (line 64, including the stored `self._state_proxy` attribute) and `StateManager._state_proxy(self) -> StateReader` (line 242). The instance still comes from `self.hassette.state_proxy` (line 244). The four call sites (`get_state`, `yield_domain_states`, `num_domain_states`, `in`) are unchanged. Add the `state_manager-no-core` rule.

## Replacement Targets

- **`resources/base.py:145` lazy `TaskBucket` import** → replaced by the `is_task_bucket` marker + registered factory. Remove the lazy import.
- **`scheduler/scheduler.py:74` runtime `SchedulerService` import** → replaced by the `SchedulerServiceProtocol` annotation. Remove the import.
- **`state_manager/state_manager.py:10` runtime `StateProxy` import** → replaced by the `StateReader` annotation. Remove the import.
- **`tools/check_module_boundaries.py` module docstring (lines 20–24)** — currently states the scheduler/state_manager cycles are "deferred to an ADR". Replace with the resolved-via-protocol-inversion description and the new rule names. (Note: the docstring's mention of `conversion ↔ models` stays — that cycle is still open under #892.)

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

## Alternatives Considered

- **Relocate `SchedulerService`/`StateProxy` into their consumer packages.** Rejected. `SchedulerService` runtime-imports three `core` siblings (`database_service`, `registration`, `sync_executor_service`); `StateProxy` imports four (`api_resource`, `bus_service`, `scheduler_service`, `websocket_service`). Moving the classes to L5 would convert two clean single-line cycles into several new L5→core upward violations. The classes import nothing from their consumers, so the protocol seam is a single-line back-edge to remove. (This is the decision the user settled before design — recorded here, not re-litigated.)
- **`from __future__ import annotations` to stringize the offending annotations.** Rejected — project-wide ban (breaks Pydantic/pyright runtime introspection).
- **Bundle `conversion ↔ models` (#892) into this work.** Rejected — it is independent of these three cycles, sits on the typed-state-read hot path, and has unresolved design questions (registration-scan trigger, scalar-conversion relocation). Splitting it keeps this wave mechanical and self-proving; #892 gets its own design.
- **Adopt `pytest-archon` / `import-linter` for cycle detection.** Deferred to #633; the house pattern is hand-written `tools/check_*.py` AST checks.
- **Do nothing.** Rejected — the latent top-level cross-package imports remain a load-order fragility, and #633 stays further from unblocked.

## Test Strategy

### Existing Tests to Adapt
- `tests/unit/tools/test_check_module_boundaries.py::test_state_manager_import_of_core_not_yet_governed` (line 144) — currently asserts `check_source(src, "state_manager") == []` for a `state_manager → core` import. Flip it to assert the `state_manager-no-core` violation is now produced, and rename accordingly. Add a parallel `scheduler-no-core` test and a `resources-no-task_bucket` test (the file has no scheduler/resources stand-in today).
- Integration tests that construct real `StateProxy`/`SchedulerService` (`tests/integration/test_states.py`, `tests/unit/test_scheduler_resource.py`, etc.) need **no** changes — the concrete classes still satisfy the protocols structurally.

### New Test Coverage
- **FR#1/FR#2 structural conformance:** a typing-level assertion (assignment to a protocol-typed variable, or a small conformance test) that `SchedulerService` satisfies `SchedulerServiceProtocol` and `StateProxy` satisfies `StateReader`. Pyright is the primary gate; a runtime smoke assert is optional.
- **AC#5 testability upside:** a unit test that constructs `DomainStates` with a dict-backed fake implementing `StateReader` (`get_state`/`num_domain_states`/`yield_domain_states`/`__contains__`) — proving the public state path no longer needs the concrete `StateProxy` or `core`.
- **FR#7/FR#8 self-proving rules:** `check_source` unit tests for each new rule (violation present → flagged; TYPE_CHECKING import → clean).
- **FR#6 TaskBucket inversion:** a test asserting a non-`TaskBucket` `Resource` gets its own bucket and a `TaskBucket` is its own bucket, plus the guarded-`RuntimeError` path when the factory is unregistered.

### Tests to Remove
No tests to remove.

## Documentation Updates
- `tools/check_module_boundaries.py` module docstring (lines 13–25) — update the enforced-rules list and replace the "deferred to an ADR" paragraph for the scheduler/state_manager cycles with the protocol-inversion resolution and the new rule names. Leave the `conversion ↔ models` mention (still open under #892).
- No docs-site (`docs/pages/`) changes — these are internal framework-plumbing types app authors never reference (`design-completeness.md` "no corresponding docs page" exception applies).
- Commit type: `chore:` (internal architecture, no user-visible behavior change) so it stays out of the release-please changelog.

## Impact

### Changed Files
- `src/hassette/types/types.py` (modify) — add `SchedulerServiceProtocol` and `StateReader`; add `ScheduledJob`, `TaskBucket`, and `HassStateDict` to the `TYPE_CHECKING` block (none are imported there today).
- `src/hassette/types/__init__.py` (modify) — export the two new protocols.
- `tools/check_module_boundaries.py` (modify) — add `scheduler-no-core`, `state_manager-no-core`, `resources-no-task_bucket` rules; update docstring. (Higher risk — shared guard.)
- `src/hassette/resources/base.py` (modify) — `is_task_bucket` ClassVar, factory slot + registrar, drop lazy import (line 145). (Higher risk — base class.)
- `src/hassette/task_bucket/task_bucket.py` (modify) — set `is_task_bucket = True`; register the factory at import.
- `src/hassette/scheduler/scheduler.py` (modify) — drop core import (line 74); retype `scheduler_service`.
- `src/hassette/state_manager/state_manager.py` (modify) — drop core import (line 10); retype against `StateReader`.
- `src/hassette/state_manager/state_manager.pyi` (modify) — retype `DomainStates`/`StateManager` stub members from `StateProxy` to `StateReader` (lines 28, 37, 43, 60).
- `tests/unit/tools/test_check_module_boundaries.py` (modify) — flip the stand-in; add new rule tests.
- New test file(s) under `tests/unit/` for protocol conformance and the `DomainStates`-against-fake test.

<!-- Gap check 2026-06-22: 1 gap included — state_manager/state_manager.pyi (lines 28,37,43,60, types DomainStates/StateManager against StateProxy) → T04. All other SchedulerService/StateProxy references are in core/ (allowed) or test_utils/ (allowed) or TYPE_CHECKING-only; each offending runtime import is the sole one in its package, so the three new rules pass once each fix lands. -->


### Behavioral Invariants
- `TaskBucket` ownership: every non-`TaskBucket` `Resource` gets its own default bucket; a `TaskBucket` is its own bucket.
- Scheduler dispatch, job lifecycle, and removal-callback behavior unchanged.
- State-read semantics (stale-cache reads, `ResourceNotReadyError` on cold start, retry) unchanged.
- `hassette.scheduler_service` / `hassette.state_proxy` public accessors keep returning the concrete instances.

### Blast Radius
- `Resource` base-class change touches every resource (Bus, Scheduler, Api, StateManager, services) — the highest-fan-in edit; covered by the full suite.
- The `types` additions are purely additive.
- `scheduler`/`state_manager` changes are annotation-only retypes plus import removal — no runtime behavior touched.

## Open Questions

None. (The two open questions for `conversion ↔ models` — the registration-scan trigger and the scalar-conversion relocation — move with that cycle to #892, which is out of scope here.)
