---
task_id: "T01"
title: "Create lifecycle.py and operations.py modules"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#5", "AC#2", "AC#3"]
---

## Summary

Create the two new module-level function files that will hold the extracted lifecycle and structural operations. Copy method bodies from LifecycleMixin and Resource into module-level functions with the resource as the first parameter. Update the `_LifecycleHostP` Protocol to remove `create_service_status_event`. Update `resources/__init__.py` to re-export. This task is purely additive — old methods remain on the classes until T06.

## Target Files

- create: `src/hassette/resources/lifecycle.py`
- create: `src/hassette/resources/operations.py`
- modify: `src/hassette/resources/mixins.py`
- modify: `src/hassette/resources/__init__.py`
- read: `src/hassette/resources/base.py`
- read: `src/hassette/utils/service_utils.py`

## Prompt

Create two new modules in `src/hassette/resources/`:

**`lifecycle.py`** — 11 functions for lifecycle state transitions (5 async, 6 sync). Each takes the resource as its first parameter, typed as `_LifecycleHostP` (imported from `mixins.py`). Copy the method bodies verbatim from `LifecycleMixin` in `mixins.py`, changing `self` references to the `resource` parameter. Preserve the exact sync/async status of each method. Functions:

Async (5):
- `async handle_failed(resource: _LifecycleHostP, exception: BaseException) -> None`
- `async handle_crash(resource: _LifecycleHostP, exception: Exception) -> None`
- `async handle_stop(resource: _LifecycleHostP) -> None`
- `async handle_starting(resource: _LifecycleHostP) -> None`
- `async handle_running(resource: _LifecycleHostP) -> None`

Sync (6):
- `create_service_status_event(resource: _LifecycleHostP, status, exception=None, ready=False, ready_phase=None) -> HassetteServiceEvent`
- `mark_ready(resource: _LifecycleHostP, reason: str | None = None) -> None`
- `mark_not_ready(resource: _LifecycleHostP, reason: str | None = None) -> None`
- `request_shutdown(resource: _LifecycleHostP, reason: str | None = None) -> None`
- `start(resource: _LifecycleHostP) -> None`
- `cancel(resource: _LifecycleHostP) -> None`

Cross-calls within the module (`handle_failed` calls `mark_not_ready` and `create_service_status_event`) should call the module-level function directly — no `resource.method()` dispatch.

**`operations.py`** — 5 functions for structural operations. These use the concrete `Resource` type (not the Protocol) since they need full Resource access. Copy from `Resource` in `base.py`:

- `start_children_and_wait(resource: Resource, timeout: float | None = None) -> None`
- `restart(resource: Resource) -> None`
- `register_task_bucket_factory(factory: Callable) -> None` (was a classmethod — becomes plain function that sets `Resource._default_task_bucket_factory`)
- `run_hooks(resource: Resource, hooks: list, *, continue_on_error: bool = False) -> None` (was `_run_hooks`)
- `ordered_children_for_shutdown(resource: Resource) -> list[Resource]` (was `_ordered_children_for_shutdown`)

Note: `run_hooks` calls `handle_failed` — import it from `lifecycle.py`.

**Protocol update:** In `mixins.py`, remove `create_service_status_event` from the `_LifecycleHostP` Protocol (the free function accesses resource attributes directly).

**`resources/__init__.py`:** Currently empty. Add re-exports for the new modules' public functions.

Follow the `wait_for_ready()` pattern in `src/hassette/utils/service_utils.py` for style. Preserve exact method signatures (parameter types, defaults, return types).

## Focus

- `_LifecycleHostP` Protocol is at `mixins.py:97-117`. Remove only `create_service_status_event` — leave all other attributes and `initialize` method.
- `LifecycleMixin` methods span `mixins.py:120-363`. Read each method body carefully before copying — some reference instance state (`_ready_reason`, `_init_task`, `_status`, `_previous_status`, `ready_event`, `shutdown_event`, `shutdown_completed`). These become `resource._ready_reason` etc. in the free functions.
- `Resource` methods to copy: `register_task_bucket_factory` (base.py:151), `start_children_and_wait` (base.py:285), `_run_hooks` (base.py:317), `_ordered_children_for_shutdown` (base.py:346), `restart` (base.py:615).
- `run_hooks` in `operations.py` calls `handle_failed` from `lifecycle.py` — import needed.
- `resources/__init__.py` is currently empty (line count 1).

## Verify

- [ ] FR#1: All 11 lifecycle functions exist as module-level functions in `src/hassette/resources/lifecycle.py`. Verify: `python -c "from hassette.resources.lifecycle import handle_failed, handle_crash, handle_stop, handle_starting, handle_running, create_service_status_event, mark_ready, mark_not_ready, request_shutdown, start, cancel"`
- [ ] FR#2: All 5 structural functions exist in `src/hassette/resources/operations.py`. Verify: `python -c "from hassette.resources.operations import start_children_and_wait, restart, register_task_bucket_factory, run_hooks, ordered_children_for_shutdown"`
- [ ] FR#5: `_LifecycleHostP` Protocol no longer requires `create_service_status_event`. Verify: `grep -A 30 'class _LifecycleHostP' src/hassette/resources/mixins.py | grep create_service_status_event` returns no results. Note: `_LifecycleHostP` is defined inside a `TYPE_CHECKING` guard, so runtime `hasattr` checks are meaningless — use grep against the source.
- [ ] AC#2: `from hassette.resources.lifecycle import handle_failed, mark_ready` works without error.
- [ ] AC#3: `from hassette.resources.operations import start_children_and_wait, restart` works without error.
