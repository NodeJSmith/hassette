---
task_id: "T02"
title: "Add is_teardown_confirmed_quiescent lifecycle helper"
status: "planned"
depends_on: []
implements: ["FR#2", "AC#2"]
---

## Target Files

- modify: `src/hassette/resources/mixins.py`
- modify: `src/hassette/resources/lifecycle.py`
- modify: `tests/unit/resources/lifecycle/test_shutdown.py`
- modify: `tests/unit/resources/test_lifecycle_transitions.py`

## Prompt

Read the design doc's "Confirm quiescence" subsection under `## Approach` (`design/specs/106-scope-restart-refusal-escalation/design.md`) for full rationale.

### `src/hassette/resources/mixins.py`

`_TaskBucketP` (a `Protocol` class, near line 80) currently declares only `spawn`, `cancel_all_sync`, `cancel_all`, and `reopen`. Add one more method declaration to it:

```python
def pending_task_names(self) -> tuple[str, ...]: ...
```

This is required because `_LifecycleHostP.task_bucket` (used below) is typed as `_TaskBucketP`, and without this declaration, calling `.pending_task_names()` on it fails Pyright even though the real `TaskBucket` class already implements the method (`task_bucket.py:119-126`).

Also add `ResourceStatus.EXHAUSTED_DEAD` to the `VALID_TRANSITIONS[ResourceStatus.STOPPED]` entry (currently `frozenset({ResourceStatus.STARTING})`, `mixins.py:51`), with an inline comment matching the table's existing convention (e.g. `# confirmed-quiescent timeout-only refusal`). This is required because T03's `handle_timeout_only_refusal()` will call `set_service_status(..., EXHAUSTED_DEAD)` on a resource whose actual status is `STOPPED` at that point — `resource.shutdown()` always drives a resource to `STOPPED` on completion (via `handle_stop()` or `_force_terminal()`), even when the resulting `TeardownReport` later causes `restart()` to raise `RestartRefusedError`. Without this entry, that transition is invalid and raises `InvalidLifecycleTransitionError` under `strict_lifecycle=True` (which `HassetteHarness` forces unconditionally, including for T03's own integration tests).

Add a unit test to `tests/unit/resources/test_lifecycle_transitions.py` (the existing file covering `VALID_TRANSITIONS`/the `status` setter — read it first to match its fixture/assertion conventions) asserting that setting a resource's status from `STOPPED` to `EXHAUSTED_DEAD` succeeds without raising, under `strict_lifecycle=True`.

### `src/hassette/resources/lifecycle.py`

Add a module-level function (place it near `reject_lifecycle_reentry`, since it's the exact precedent to follow — read the surrounding module first to match its existing style and docstring conventions):

```python
def is_teardown_confirmed_quiescent(resource: _LifecycleHostP) -> bool:
    """Return True if nothing tracked from the resource's last teardown attempt is still running.

    Checks the resource's task_bucket for any pending task names and its shutdown-body task (if
    any) for completion. Both reflect *live* state, not a frozen snapshot from when a
    TeardownReport was generated -- every tracked task is discarded from the bucket the moment it
    actually finishes (see TaskBucket's done-callback in task_bucket.py), and _shutdown_body_task
    is never reset to None, so this can be polled safely at any point after teardown to confirm --
    rather than assume -- that a timeout-only refusal has actually resolved.
    """
    resource = typing.cast("LifecycleMixin", resource)
    body_task = resource._shutdown_body_task
    return not resource.task_bucket.pending_task_names() and (body_task is None or body_task.done())
```

This follows `reject_lifecycle_reentry`'s (`lifecycle.py:448`) pattern: a public signature typed against `_LifecycleHostP` (the module's documented convention — see the module docstring, "Functions are typed against `_LifecycleHostP`"), then `typing.cast("LifecycleMixin", resource)` before touching `_shutdown_body_task`, a `LifecycleMixin`-private attribute. `resource.task_bucket.pending_task_names()` needs no cast — only the `_TaskBucketP` Protocol change above, since `_LifecycleHostP` already declares `task_bucket` as a public field of that (now-extended) type. Use `pending_task_names()`, not `pending_tasks()` — it's already documented as safe to call without awaiting anything, and this check only needs to know whether anything is pending, not to hold a reference to the actual `asyncio.Task` objects.

In `tests/unit/resources/lifecycle/test_shutdown.py`, add tests (read the file first to match its existing fixtures — likely a real `Resource` subclass or the shared lifecycle test fixtures in `tests/unit/resources/lifecycle/conftest.py`):

- A resource with an empty `task_bucket` and no `_shutdown_body_task` set → `is_teardown_confirmed_quiescent` returns `True`.
- A resource with a task still tracked in `task_bucket` (not yet done) → returns `False`. Use an event-gated task (an `asyncio.Event().wait()` coroutine spawned via `task_bucket.spawn()`) so the test controls exactly when it finishes — do not use `asyncio.sleep()` to fake "still running."
- Same resource, after setting the event and awaiting the task to actually complete → returns `True`.
- A resource with `_shutdown_body_task` set to a task that hasn't completed → returns `False`; after it completes → returns `True`.

## Verify

- [ ] FR#2: `is_teardown_confirmed_quiescent(resource)` correctly reflects live task-bucket and shutdown-body-task state, not a frozen snapshot.
- [ ] AC#2: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py -v` passes, including the new cases above, using event-gated (not sleep-based) task completion signaling.
- [ ] `STOPPED -> EXHAUSTED_DEAD` is a valid transition: `uv run pytest tests/unit/resources/test_lifecycle_transitions.py -v` passes, including the new case asserting this transition succeeds under `strict_lifecycle=True`.
