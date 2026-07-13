---
task_id: "T06"
title: "Delete old methods and final cleanup"
status: "planned"
depends_on: ["T03", "T04", "T05"]
implements: ["AC#4", "AC#5", "AC#6"]
---

## Summary

Delete the old method bodies from LifecycleMixin and Resource — all callers (src/ and tests/) have been migrated by T03-T05. Update `INHERITED_LIFECYCLE_EXCLUSIONS` in `test_forgotten_await_completeness.py` to remove entries for methods that no longer exist on the class. Update `CLAUDE.md` Architecture section. Run the full verification suite. This is the task that satisfies the "no compatibility shims" constraint — after this, the extracted methods are structurally gone from the classes.

## Target Files

- modify: `src/hassette/resources/mixins.py`
- modify: `src/hassette/resources/base.py`
- modify: `tests/unit/test_forgotten_await_completeness.py`
- modify: `CLAUDE.md`
- read: `src/hassette/resources/lifecycle.py`
- read: `src/hassette/resources/operations.py`
- read: `tests/unit/app/test_app_dir.py`

## Prompt

**Delete from `src/hassette/resources/mixins.py` (LifecycleMixin class):**

Remove these 11 method definitions entirely (the bodies are now in `lifecycle.py`):
- `handle_failed`
- `handle_crash`
- `handle_stop`
- `handle_starting`
- `handle_running`
- `create_service_status_event`
- `mark_ready`
- `mark_not_ready`
- `request_shutdown`
- `start`
- `cancel`

Keep all properties, `__init__`, `is_ready`, `wait_ready`, and the `status` property/setter. Keep `VALID_TRANSITIONS` and all class attributes (`_ready_reason`, `_init_task`, etc.).

**Delete from `src/hassette/resources/base.py` (Resource class):**

Remove these 5 method/classmethod definitions (bodies now in `operations.py`):
- `start_children_and_wait`
- `restart`
- `register_task_bucket_factory` (classmethod)
- `_run_hooks`
- `_ordered_children_for_shutdown`

Keep `add_child`, `initialize`, `shutdown`, `cleanup`, `__init__`, and all properties/attributes. Keep the `_default_task_bucket_factory` class variable (the function in `operations.py` sets it).

**Update `tests/unit/test_forgotten_await_completeness.py`:**

The `INHERITED_LIFECYCLE_EXCLUSIONS` set (lines 101-119) lists methods excluded from forgotten-await checking because they're framework plumbing. Remove entries for methods that no longer exist on the class after extraction:
- Remove: `handle_crash`, `handle_failed`, `handle_running`, `handle_starting`, `handle_stop`, `restart`, `start_children_and_wait`
- Keep: `after_initialize`, `after_shutdown`, `before_initialize`, `before_shutdown`, `cleanup`, `initialize`, `on_initialize`, `on_shutdown`, `shutdown`, `wait_ready`

**Update `CLAUDE.md`:**

In the Architecture section, add a note under the Resource Hierarchy subsection that lifecycle state transitions and structural operations are module-level functions in `resources/lifecycle.py` and `resources/operations.py`, not methods on Resource/LifecycleMixin.

**Add hasattr test:**

In `tests/unit/app/test_app_dir.py` (created in T02), add a test verifying `hasattr(app_instance, "handle_failed")` returns `False` — the method no longer exists on the class.

**Run full verification:**
- `ptest -n 4` — full unit + integration test suite
- `prek -a && prek pyright -a --stage pre-push` — lint + type check

## Focus

- `mixins.py` LifecycleMixin methods span lines 120-363. Delete method by method, preserving class attributes and properties.
- `base.py` Resource methods: `register_task_bucket_factory` (151-157), `start_children_and_wait` (285-315), `restart` (294-315 area), `_run_hooks` (317-344), `_ordered_children_for_shutdown` (346+).
- `INHERITED_LIFECYCLE_EXCLUSIONS` is at `test_forgotten_await_completeness.py:101-119`. After removal, the set should have 10 entries (down from 17).
- The `hasattr` test is AC#4 — it can only pass after the methods are deleted, which is why it's in this task rather than T02.
- After deletion, verify no import errors from the deleted methods — any remaining `from hassette.resources.mixins import handle_failed` style imports (there shouldn't be any after T03-T05) would break.

## Verify

- [ ] AC#4: `hasattr(App(...), "handle_failed")` returns `False`. Verify: `pytest tests/unit/app/test_app_dir.py -k hasattr -v` passes.
- [ ] AC#5: Full test suite passes: `ptest -n 4` exits 0.
- [ ] AC#6: Linter and type checker pass: `prek -a && prek pyright -a --stage pre-push` exits 0.
