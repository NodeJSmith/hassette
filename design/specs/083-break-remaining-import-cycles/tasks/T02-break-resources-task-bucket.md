---
task_id: "T02"
title: "Break resources <-> task_bucket cycle via factory/marker"
status: "planned"
depends_on: []
implements: ["FR#5", "FR#6", "FR#8", "AC#2", "AC#6", "AC#7"]
---

## Summary
Remove the lazy `TaskBucket` import inside `Resource.__init__` (`resources/base.py:145`) by inverting the dependency: `task_bucket` injects its constructor and identity into `resources` instead of `resources` reaching up. Replace the `type(self) is TaskBucket` identity check with an `is_task_bucket` ClassVar marker, and replace the in-`__init__` default construction with a factory that the `task_bucket` module registers on `Resource` at import time. Add a `resources-no-task_bucket` rule to the boundary checker so the cycle cannot re-accrete. Behavior is unchanged: every non-`TaskBucket` resource still gets its own default bucket, and a `TaskBucket` is still its own bucket.

## Target Files
- modify: `src/hassette/resources/base.py`
- modify: `src/hassette/task_bucket/task_bucket.py`
- modify: `tools/check_module_boundaries.py`
- modify: `tests/unit/tools/test_check_module_boundaries.py`
- read: `design/specs/083-break-remaining-import-cycles/design.md`

## Prompt
Follow the design doc `## Architecture → Step 1 — resources ↔ task_bucket` section.

In `src/hassette/resources/base.py`:
1. Add a class attribute to `Resource`: `is_task_bucket: ClassVar[bool] = False` (place it with the other class-level attributes near `task_bucket: "TaskBucket"` at line 116).
2. Add the factory slot and registrar to `Resource`:
   ```python
   _default_task_bucket_factory: ClassVar["Callable[[Hassette, Resource], TaskBucket] | None"] = None

   @classmethod
   def register_task_bucket_factory(cls, factory: "Callable[[Hassette, Resource], TaskBucket]") -> None:
       cls._default_task_bucket_factory = factory
   ```
3. In `Resource.__init__` (lines 142–162): remove the lazy import at line 145. Replace `if type(self) is TaskBucket:` (line 158) with `if self.is_task_bucket:`. Replace `task_bucket or TaskBucket(self.hassette, parent=self)` (line 162) with a call through the factory — guard it: if `self._default_task_bucket_factory is None`, raise a clear `RuntimeError` explaining that `hassette.task_bucket` must be imported before constructing a `Resource`. Keep `TaskBucket` referenced only under `TYPE_CHECKING` in this file. The `TYPE_CHECKING` import already exists (`resources/base.py:20`) — `TaskBucket` is already used in `"TaskBucket"` string annotations — so do NOT add a redundant import; just confirm it's present.
4. Add `Callable` to the imports if not present.

In `src/hassette/task_bucket/task_bucket.py`:
1. Set `is_task_bucket = True` on the `TaskBucket` class (class-level, overriding the `Resource` default).
2. At module import time (after the `TaskBucket` class definition), register the factory:
   `Resource.register_task_bucket_factory(lambda hassette, owner: TaskBucket(hassette, parent=owner))`.

In `tools/check_module_boundaries.py`:
1. Append a `Rule` to `RULES` (copy the `api-no-core` rule shape):
   ```python
   Rule(
       name="resources-no-task_bucket",
       applies=lambda layer: layer == "resources",
       forbids=lambda module: module == "hassette.task_bucket" or module.startswith("hassette.task_bucket."),
       reason="resources sits below task_bucket; TaskBucket is injected via register_task_bucket_factory (#1079)",
   ),
   ```
2. Update the module docstring's enforced-rules list (lines 13–18) to include `resources-no-task_bucket`.

In `tests/unit/tools/test_check_module_boundaries.py`:
1. Add a test mirroring `test_bus_import_of_core_flagged` (line 151) that asserts a `resources` file importing `hassette.task_bucket` at runtime is flagged with the `resources-no-task_bucket` message, and a TYPE_CHECKING-exempt variant.

## Focus
- `resources/base.py` is the highest-fan-in file in the codebase — every `Resource` subclass (Bus, Scheduler, Api, StateManager, every Service) runs `Resource.__init__`. The full suite covers it; run it.
- Load-order safety: `task_bucket/task_bucket.py` imports `from hassette.resources.base import Resource` (line 13), so `Resource` is defined before the registration line runs. `Resource` instances are only constructed at Hassette runtime, well after `hassette.task_bucket` is imported by `core` — so the factory is always set by then. The guarded `RuntimeError` is the safety net for the impossible-in-practice case.
- `type(self) is TaskBucket` is exact-class; `is_task_bucket: ClassVar` is inherited, so a future `TaskBucket` subclass would also self-bucket. No `TaskBucket` subclasses exist (verified), so behavior is unchanged. This is the only `is TaskBucket` identity check in the codebase (verified via grep).
- `resources/base.py:145` is the only runtime `hassette.task_bucket` import in the `resources` package (verified), so the new rule passes once it is removed.
- The boundary checker lives at `tools/check_module_boundaries.py` (repo root), not under `src/`. Its test imports from `check_module_boundaries` (the `tools/` dir is on the path).

## Verify
- [ ] FR#5: `grep -n "hassette.task_bucket" src/hassette/resources/base.py` shows no runtime import (TYPE_CHECKING-only is acceptable); the `# lazy-import:` line at 145 is gone.
- [ ] FR#6: existing resource/task-bucket tests pass — a non-`TaskBucket` `Resource` still gets its own default `TaskBucket`, and a `TaskBucket` is still its own `task_bucket`.
- [ ] FR#8: `tools/check_module_boundaries.py` `RULES` contains `resources-no-task_bucket`; it forbids `hassette.task_bucket` for the `resources` layer.
- [ ] AC#2: `python tools/check_lazy_imports.py` passes and `grep -rn "lazy-import" src/hassette/` no longer lists `resources/base.py`.
- [ ] AC#6: a `check_source` test asserts that reverting to `from hassette.task_bucket import TaskBucket` in a `resources` file is flagged by `resources-no-task_bucket`.
- [ ] AC#7: a test confirms a non-`TaskBucket` `Resource` receives its own bucket, a `TaskBucket` is its own bucket, and the guarded `RuntimeError` fires when the factory is unregistered.
