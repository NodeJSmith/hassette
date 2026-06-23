---
task_id: "T03"
title: "Break scheduler <-> core cycle via SchedulerServiceProtocol"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#7", "AC#3", "AC#6"]
---

## Summary
Remove the runtime `from hassette.core.scheduler_service import SchedulerService` import in `scheduler/scheduler.py` (line 74) by retyping `Scheduler.scheduler_service` against the `SchedulerServiceProtocol` defined in T01. The instance is unchanged — it still comes from `self.hassette.scheduler_service` (line 116). Every call site keeps working because the protocol is structural. Add a `scheduler-no-core` rule to the boundary checker and a test so the import cannot return.

## Target Files
- modify: `src/hassette/scheduler/scheduler.py`
- modify: `tools/check_module_boundaries.py`
- modify: `tests/unit/tools/test_check_module_boundaries.py`
- read: `src/hassette/types/__init__.py`
- read: `design/specs/083-break-remaining-import-cycles/design.md`

## Prompt
Follow the design doc `## Architecture → Step 2 — the two core cycles` (the `core ↔ scheduler` paragraph).

In `src/hassette/scheduler/scheduler.py`:
1. Delete the runtime import `from hassette.core.scheduler_service import SchedulerService` (line 74).
2. Add `SchedulerServiceProtocol` to the existing runtime import `from hassette.types import TriggerProtocol` (line 76) → `from hassette.types import SchedulerServiceProtocol, TriggerProtocol`.
3. Retype the class attribute at line 95: `scheduler_service: SchedulerServiceProtocol` (was `SchedulerService`). Update its docstring if it names the concrete type.
4. Leave the instance assignment `self.scheduler_service = self.hassette.scheduler_service` (line 116) unchanged. Leave every call site unchanged (`register_removal_callback`, `deregister_removal_callback`, `add_job`, `mark_job_cancelled`, `dequeue_job`, `remove_jobs_by_owner`, `task_bucket.spawn`).

In `tools/check_module_boundaries.py`:
1. Append a `Rule` to `RULES` (copy the `bus-no-core` shape):
   ```python
   Rule(
       name="scheduler-no-core",
       applies=lambda layer: layer == "scheduler",
       forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
       reason="scheduler must not import core at runtime; SchedulerService is consumed via SchedulerServiceProtocol (#1079)",
   ),
   ```
2. Update the module docstring (lines 13–24): add `scheduler-no-core` to the enforced-rules list, and edit the "remaining runtime cycles … deferred to an ADR" paragraph (lines 20–24) to drop `scheduler ↔ core` (it is now resolved); leave `state_manager ↔ core` there for now (T04 removes it) and the `conversion ↔ models` mention (still open, #892).

In `tests/unit/tools/test_check_module_boundaries.py`:
1. Add a test mirroring `test_bus_import_of_core_flagged` (line 151) and `test_bus_import_of_core_submodule_flagged` (line 162) for the `scheduler` layer importing `hassette.core.scheduler_service`, asserting the `scheduler-no-core` message. Add a TYPE_CHECKING-exempt variant if it adds value.

## Focus
- `scheduler/scheduler.py:74` is the ONLY runtime `hassette.core` import in the entire `scheduler` package (verified — `classes.py`, `sync.py`, `triggers.py`, `error_context.py`, `__init__.py` have none). So the `scheduler-no-core` rule passes once line 74 is removed; no sibling files need touching.
- `scheduler.py` already imports `from hassette.types import TriggerProtocol` at line 76 (runtime) and uses `from hassette.types.enums import ExecutionMode` and `from hassette.types.types import LOG_LEVEL_TYPE` — `scheduler → types` is already an established runtime edge, so adding the protocol there is free.
- The annotation `scheduler_service: SchedulerServiceProtocol` is a class-body annotation evaluated at definition time (no `from __future__`), so `SchedulerServiceProtocol` must be a runtime import — which it is (step 2 above), not TYPE_CHECKING.
- Depends on T01: `SchedulerServiceProtocol` must already exist in and be exported from `hassette.types`.
- This is annotation-only + import removal — no runtime behavior changes. Run the scheduler unit/integration tests (`tests/unit/test_scheduler_resource.py`, `tests/integration/` scheduler tests) to confirm `SchedulerService` still satisfies the protocol at the call sites.

## Verify
- [ ] FR#3: `grep -n "hassette.core" src/hassette/scheduler/scheduler.py` shows no runtime import (TYPE_CHECKING-only acceptable); `Scheduler.scheduler_service` is typed `SchedulerServiceProtocol`; pyright passes.
- [ ] FR#7: `tools/check_module_boundaries.py` `RULES` contains `scheduler-no-core` forbidding `hassette.core` for the `scheduler` layer.
- [ ] AC#3: `scheduler/scheduler.py` contains no runtime `hassette.core` import; `python tools/check_module_boundaries.py` reports zero violations.
- [ ] AC#6: a `check_source` test asserts that re-adding `from hassette.core.scheduler_service import SchedulerService` in a `scheduler` file is flagged by `scheduler-no-core`.
