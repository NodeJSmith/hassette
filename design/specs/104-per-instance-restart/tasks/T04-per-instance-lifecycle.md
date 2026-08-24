---
task_id: "T04"
title: "Add per-instance lifecycle methods and selective restart"
status: "done"
depends_on: ["T02", "T03"]
implements: ["FR#1", "FR#2", "FR#3", "FR#7", "FR#8", "AC#1", "AC#2", "AC#3", "AC#8", "AC#9"]
---

## Summary
The core feature task. Add `reload_instance()`, `_reload_instance_unlocked()`, `stop_instance()`, and `start_instance()` to `AppLifecycleService`. Modify `apply_changes()` to compare per-instance configs and selectively restart only changed instances when the list length is unchanged. Add corresponding thin facade delegates to `AppHandler`. Update all `apply_changes()` call sites for the new signature.

## Target Files
- modify: `src/hassette/core/app_lifecycle_service.py`
- modify: `src/hassette/core/app_handler.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- modify: `tests/unit/core/test_app_lifecycle_service_operations.py`
- modify: `tests/integration/test_apps.py`
- read: `src/hassette/core/app_factory.py` (create_single_instance from T02)
- read: `src/hassette/core/app_registry.py` (unregister_app with index, get_instances)
- read: `src/hassette/core/app_change_detector.py` (ChangeSet structure)
- read: `tests/unit/core/conftest.py` (lifecycle fixtures, set_registry_apps helper)
- read: `design/specs/104-per-instance-restart/design.md` (Architecture section)

## Prompt
### AppLifecycleService (`src/hassette/core/app_lifecycle_service.py`)

**1. Add `reload_instance()` and `_reload_instance_unlocked()`:**

Follow the `reload_app()` / `_stop_app_unlocked()` / `_start_app_unlocked()` pattern:

```python
async def reload_instance(
    self,
    app_key: str,
    index: int,
    force_reload: bool = False,
    *,
    admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
) -> None:
```

The public method calls `_admit_start()` (producing 409 pre-bootstrap), then acquires the per-app-key lock and calls `_reload_instance_unlocked()`.

`_reload_instance_unlocked()`:
- Re-validate `index` against current manifest's instance count (post-lock re-validation, mirroring `start_app()`'s pattern at line 478-491). No-op if out of range.
- Scope failed-entry info to the target index only (check `self.registry.get_instances(app_key).get(index)`) — do NOT use app-key-wide `get_failed_instance_infos()`.
- Unregister the instance at that index via `self.registry.unregister_app(app_key, index)`.
- If the entry had a running App, shut it down via `shutdown_instance()`.
- Emit STOPPED events for the removed entry if it was a failed entry.
- Call `factory.load_class()` — on failure, `record_failure(app_key, index, error)` with the real index, then emit `HassetteAppStateEvent` for the failure (mirroring `_start_app_unlocked()`'s post-create failure event emission at lines 526-543 — failures that never produce an `App` object need explicit event emission or the dashboard/WS status cache never learns about them).
- Call `factory.create_single_instance()` to create a replacement. On validation/init failure (recorded by `create_single_instance` via `record_failure`), emit `HassetteAppStateEvent` for the failed index (same pattern as above).
- Call `initialize_instances()` with `instance_index=index` so reconciliation is scoped.

**2. Add `stop_instance()` and `start_instance()`:**

- `stop_instance(app_key, index)` — no admission check (matches `stop_app`). Acquires lock, re-validates index, scopes to single instance.
- `start_instance(app_key, index, *, admission_mode=...)` — calls `_admit_start()` (matches `start_app`). Acquires lock, re-validates index, creates and initializes the single instance.

**3. Modify `apply_changes()`:**

Change signature to `apply_changes(self, changes, original_config, current_config)`.

In the `reload_apps` loop, wrap with `should_auto_reconcile()` check (preserve autostart=false dormancy), then compare per-instance configs:

```python
for app_key in changes.reload_apps:
    if not self.should_auto_reconcile(app_key):
        self.logger.debug("Skipping reload of autostart=false app %s (not running)", app_key)
        continue
    old_instances = self.factory.normalize_configs(original_config[app_key].app_config)
    new_instances = self.factory.normalize_configs(current_config[app_key].app_config)
    if len(old_instances) != len(new_instances):
        await self.reload_app(app_key)  # fallback
    else:
        changed_indices = [i for i in range(len(new_instances)) if old_instances[i] != new_instances[i]]
        if changed_indices:
            async with self._get_app_key_lock(app_key):
                for idx in changed_indices:
                    await self._reload_instance_unlocked(app_key, idx)
```

**4. Update callers of `apply_changes()`:**

Thread `original_config` and `current_config` through from `handle_change_event()` and `_replay_pre_release_reconciliation_if_needed()` — both already have these values in scope.

### AppHandler (`src/hassette/core/app_handler.py`)

Add thin facade delegates:
- `reload_instance(app_key, index, force_reload=False)` → `self.lifecycle.reload_instance(...)`
- `stop_instance(app_key, index)` → `self.lifecycle.stop_instance(...)`
- `start_instance(app_key, index)` → `self.lifecycle.start_instance(...)`
- Update `apply_changes()` to pass through the new parameters

### Tests

Update all `apply_changes()` call sites in test files to match the new signature. Add unit tests:
- AC#1: 2-instance app, only instance 1's config changes — verify only instance 1 restarts
- AC#2: File change → `reimport_apps` — verify full app-key reload via `reload_app`
- AC#3: Instance list length changes — verify fallback to `reload_app`
- AC#8: Per-instance reload emits correct `HassetteAppStateEvent` (app_key, index, instance_name)
- AC#9: Per-instance operations acquire the per-app-key lock

See design doc `## Architecture → Component changes → AppLifecycleService` and `## Data flow for selective restart` for the full specification.

## Focus
- `_reload_instance_unlocked()` must call `factory.load_class()` itself — `create_single_instance()` receives an already-loaded `app_class` and cannot handle class-load failures. Record class-load failure at the actual target index, not 0.
- The `should_auto_reconcile` check must wrap the entire per-instance branch, not just individual `_reload_instance_unlocked()` calls.
- The `reload_apps` loop in `apply_changes()` currently calls `reload_app()` which acquires the lock internally. The new per-instance branch must acquire the lock in `apply_changes()` before the inner loop — do NOT call the public `reload_instance()` (which also acquires the lock) from inside the loop.
- `handle_change_event()` has `original_apps_config` and `current_apps_config` in local scope. `_replay_pre_release_reconciliation_if_needed()` also has both. Thread them through to `apply_changes()`.
- `tests/unit/core/test_app_lifecycle_service.py` has 7 `apply_changes` call sites. `test_app_lifecycle_service_operations.py` has 1. `tests/integration/test_apps.py` has 2 (via `app_handler.apply_changes`).
- Use `tests/unit/core/conftest.py`'s existing `lifecycle_service` fixture and `set_registry_apps` helper.

## Verify
- [ ] FR#1: Unit test with 2-instance app, one config change, only the changed instance reloads
- [ ] FR#2: Unit test where file change triggers `reimport_apps`, all instances reload via `reload_app`
- [ ] FR#3: Unit test where instance list length changes, system falls back to `reload_app`
- [ ] FR#7: Unit test verifies per-instance reload emits `HassetteAppStateEvent` with correct identity
- [ ] FR#8: Unit test verifies per-instance operations acquire the per-app-key lock
- [ ] AC#1: Same as FR#1 — `shutdown_instance` called only for instance 1, `create_single_instance` called only for index 1
- [ ] AC#2: Same as FR#2 — file change → `reimport_apps` → all instances reload via `reload_app`
- [ ] AC#3: Same as FR#3 — list length change → `reload_app` fallback
- [ ] AC#8: Same as FR#7 — correct app_key, index, instance_name in event
- [ ] AC#9: Per-instance operations acquire the per-app-key lock, serializing with full app-key operations
