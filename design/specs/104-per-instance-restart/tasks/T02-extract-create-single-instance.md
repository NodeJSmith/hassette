---
task_id: "T02"
title: "Extract create_single_instance from AppFactory"
status: "planned"
depends_on: []
implements: ["FR#1"]
---

## Summary
Extract the inner loop body of `AppFactory.create_instances()` into a `create_single_instance()` method. This is the foundational refactor that both the existing bulk path and the new per-instance reload path will call. Also fix the class-load failure index attribution: the current code hardcodes `record_failure(app_key, 0, load_error)` at line 52, which would corrupt a healthy sibling's registry entry during per-instance reload.

## Target Files
- modify: `src/hassette/core/app_factory.py`
- modify: `tests/unit/test_app_factory.py`
- read: `src/hassette/core/app_registry.py` (record_failure behavior)

## Prompt
Refactor `src/hassette/core/app_factory.py`:

1. Extract `create_single_instance(self, app_key, manifest, index, config_dict, app_class)` from the inner loop of `create_instances()` (lines 58-83). The new method should:
   - Validate `instance_name` via `is_valid_instance_name()`
   - Call `app_class.app_config_cls.model_validate(config)`
   - Construct the `App` instance
   - Call `self.registry.register_app(app_key, index, app_instance)`
   - On failure, call `self.registry.record_failure(app_key, index, exc)` with the real index

2. Rewrite `create_instances()` to:
   - Call `self.load_class()` (unchanged — class-load failure at index 0 is correct here since it applies to all instances equally)
   - Call `self.normalize_configs()`
   - Loop calling `create_single_instance()` for each index

3. Add/update tests in `tests/unit/test_app_factory.py`:
   - Verify `create_single_instance()` registers the instance on success
   - Verify `create_single_instance()` records failure at the correct index (not hardcoded 0)
   - Verify `create_instances()` still works end-to-end (existing tests should pass)

See design doc `## Architecture → Component changes → AppFactory` for details.

## Focus
- The class-load failure path (`app_factory.py:48-53`) fires BEFORE the per-instance loop, so it is NOT part of the `create_single_instance()` extraction. `create_single_instance()` receives an already-loaded `app_class` parameter.
- `_reload_instance_unlocked()` (T04) will need to call `factory.load_class()` itself and handle class-load failures with the actual target index — that's T04's responsibility, not this task's.
- `normalize_configs()` is a static method — no state dependency, safe to call from anywhere.
- The `record_failure` call at line 52 currently hardcodes index 0. In the bulk `create_instances()` path, this is acceptable (class failure applies to all instances). But the new `create_single_instance()` method must use the real `index` parameter.

## Verify
- [ ] FR#1: `create_single_instance()` exists, registers the instance at the correct index, and records failures at the correct index (unit tests pass)
