---
task_id: "T01"
title: "Define SchedulerServiceProtocol and StateReader in types"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "AC#4"]
---

## Summary
Add two protocols to the `types` leaf layer that describe the surfaces the service-layer consumers need from `core`: `SchedulerServiceProtocol` (the 7-member surface `Scheduler` uses) and a read-only `StateReader` (the 4-member surface `StateManager`/`DomainStates` use). These protocols are the foundation the two core-cycle fixes (T03, T04) depend on. The concrete `SchedulerService` and `StateProxy` classes stay in `core` and satisfy the protocols structurally — no changes to them. This task is purely additive: it defines the protocols, exports them, and pins structural conformance with a test.

## Target Files
- modify: `src/hassette/types/types.py`
- modify: `src/hassette/types/__init__.py`
- read: `src/hassette/core/scheduler_service.py`
- read: `src/hassette/core/state_proxy.py`
- create: `tests/unit/types/test_service_protocols.py`

## Prompt
Add two protocols to `src/hassette/types/types.py`, beside the existing `TriggerProtocol` (class at line 154). Follow the `TriggerProtocol` shape but make these **plain** `Protocol`s — do NOT add `@runtime_checkable` (nothing does `isinstance` against them).

Transcribe the member signatures from the concrete classes (read them to get exact signatures):
- `SchedulerServiceProtocol` from `src/hassette/core/scheduler_service.py` (`SchedulerService`): `task_bucket` (attribute), `add_job` (async), `dequeue_job`, `register_removal_callback`, `deregister_removal_callback`, `mark_job_cancelled` (async), `remove_jobs_by_owner`.
- `StateReader` from `src/hassette/core/state_proxy.py` (`StateProxy`): `get_state`, `num_domain_states`, `yield_domain_states`, `__contains__`.

Use the stubs in the design doc `## Architecture → Protocol home: types/types.py` section verbatim as the starting point:

```python
class SchedulerServiceProtocol(Protocol):
    task_bucket: "TaskBucket"
    async def add_job(self, job: "ScheduledJob") -> None: ...
    def dequeue_job(self, job: "ScheduledJob") -> bool: ...
    def register_removal_callback(self, owner_id: str, callback: "Callable[[ScheduledJob], None]") -> None: ...
    def deregister_removal_callback(self, owner_id: str) -> None: ...
    async def mark_job_cancelled(self, db_id: int) -> None: ...
    def remove_jobs_by_owner(self, owner: str) -> "asyncio.Task[None]": ...


class StateReader(Protocol):
    def get_state(self, entity_id: str) -> "HassStateDict | None": ...
    def num_domain_states(self, domain: str) -> int: ...
    def yield_domain_states(self, domain: str) -> "Generator[tuple[str, HassStateDict], Any, None]": ...
    def __contains__(self, entity_id: str) -> bool: ...
```

Add the three referenced names to the existing `if TYPE_CHECKING:` block at the top of `types.py` (lines 11–17) — none are currently imported there:
- `from hassette.scheduler.classes import ScheduledJob`
- `from hassette.task_bucket import TaskBucket`
- `from hassette.events import HassStateDict` — import from the `hassette.events` package (this is how `state_proxy.py:26` and `state_registry.py:11` import it). Do NOT change it to `hassette.events.base`: that submodule holds `Event`/`EventPayload`, a different symbol.

`Callable`, `Coroutine`, `Generator`, `Any`, `asyncio` may need adding to the runtime imports at the top of the file — check what's already imported (`Callable`, `Coroutine`, `Awaitable` are imported from `collections.abc` at line 1; `asyncio` and `Generator` are not). Add `import asyncio` and `Generator` to the `collections.abc` import as needed.

Export both protocols from `src/hassette/types/__init__.py`: add them to the `from .types import (...)` block and to `__all__`. The existing `__all__` is in case-sensitive `sorted()` order (ALL_CAPS constants first, then CamelCase) — insert the new names in their matching `sorted()` slots (`SchedulerServiceProtocol` and `StateReader` fall among the other `S*` CamelCase entries).

Create `tests/unit/types/test_service_protocols.py` with a structural-conformance test: assert (at minimum) that `SchedulerService` and `StateProxy` are usable where the protocols are expected. Since the protocols are not `@runtime_checkable`, use a pyright-style assignment assertion in a function annotated to accept the protocol, plus a lightweight runtime check that the concrete classes define the named members (`hasattr` over the member list). Do NOT make the protocols `@runtime_checkable` just to enable `isinstance`.

## Focus
- `types/types.py` already `TYPE_CHECKING`-imports from `app.app_config`, `bus.error_context`, `events.base`, `models.states.base`, `scheduler.error_context` (lines 11–17) — adding three more names to that same block is the established pattern and creates no runtime edge from `types`.
- `task_bucket` on `SchedulerServiceProtocol` is an attribute inherited from `Resource` (`resources/base.py:116`), not declared on `SchedulerService` directly — the structural match still holds because every `SchedulerService` is a `Resource`. Type it as `"TaskBucket"`.
- `types/__init__.py` re-exports `TriggerProtocol` from `.types` (line 32) and lists it in `__all__` (line 66) — mirror that for the two new names.
- Do not import `hassette.core` anywhere in `types` — these protocols exist precisely so `types`/`scheduler`/`state_manager` never need `core` at runtime.
- The test directory is `tests/unit/types/` — confirm it exists (or create it with the others); follow the project's existing unit-test style (plain `pytest`, no class wrappers needed).

## Verify
- [ ] FR#1: `SchedulerServiceProtocol` is defined in `types/types.py` with all seven members (`task_bucket`, `add_job`, `dequeue_job`, `register_removal_callback`, `deregister_removal_callback`, `mark_job_cancelled`, `remove_jobs_by_owner`) and exported from `types/__init__.py`.
- [ ] FR#2: `StateReader` is defined in `types/types.py` with all four members (`get_state`, `num_domain_states`, `yield_domain_states`, `__contains__`) and exported from `types/__init__.py`.
- [ ] AC#4: `pyright` passes with no new errors and no `# pyright: ignore` added for the protocol seams; the conformance test in `tests/unit/types/test_service_protocols.py` passes, confirming `SchedulerService` satisfies `SchedulerServiceProtocol` and `StateProxy` satisfies `StateReader`.
