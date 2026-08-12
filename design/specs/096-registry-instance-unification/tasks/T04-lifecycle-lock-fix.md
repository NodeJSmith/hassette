---
task_id: "T04"
title: "Fix stop_app concurrency and boot issue detection"
status: "done"
depends_on: ["T02"]
implements: ["FR#9", "FR#14"]
---

## Summary

Fix the `stop_app` concurrency gap by wrapping it in the per-app-key lock. Extract internal unlocked methods (`_stop_app_unlocked`, `_start_app_unlocked`) so `reload_app` can acquire the lock once and call both without deadlocking on the non-reentrant `asyncio.Lock`. Fix the `stop_app` guard for failed-only apps. Update `collect_boot_issues()` to treat `ManifestStatus.DEGRADED` as a boot issue alongside `"failed"`.

## Target Files

- modify: `src/hassette/core/app_lifecycle_service.py`
- modify: `src/hassette/core/runtime_query_service.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- modify: `tests/unit/core/test_app_lifecycle_service_operations.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/unit/core/conftest.py`
- modify: `tests/unit/core/test_app_lifecycle_service_coverage.py`
- read: `design/specs/096-registry-instance-unification/design.md`

## Prompt

### stop_app lock

In `src/hassette/core/app_lifecycle_service.py`:

1. **Extract `_stop_app_unlocked(app_key)`** — move the current `stop_app` body (lines 515-523) into this new private method.

2. **Extract `_start_app_unlocked(app_key, manifest, force_reload)`** — move the body of `start_app` that runs inside `async with self._get_app_key_lock(app_key):` (lines 480-507) into this new private method. The admission check (`_admit_start`) stays outside the lock and outside this method.

3. **`stop_app`** becomes:
```python
async def stop_app(self, app_key: str) -> None:
    async with self._get_app_key_lock(app_key):
        await self._stop_app_unlocked(app_key)
```

4. **`start_app`** becomes:
```python
async def start_app(self, app_key, force_reload=False, *, admission_mode=...):
    app_manifest = self.registry.get_manifest(app_key)
    if not app_manifest:
        ...
        return
    await self._admit_start(app_key=app_key, admission_mode=admission_mode)
    async with self._get_app_key_lock(app_key):
        # Re-fetch under the lock (same reason as current code)
        app_manifest = self.registry.get_manifest(app_key)
        if not app_manifest:
            ...
            return
        await self._start_app_unlocked(app_key, app_manifest, force_reload)
```

5. **`reload_app`** acquires the lock once:
```python
async def reload_app(self, app_key, force_reload=False, *, admission_mode=...):
    ...
    await self._admit_start(...)
    async with self._get_app_key_lock(app_key):
        await self._stop_app_unlocked(app_key)
        app_manifest = self.registry.get_manifest(app_key)
        if not app_manifest:
            ...
            return
        await self._start_app_unlocked(app_key, app_manifest, force_reload)
```

### stop_app guard for failed-only apps

After the `unregister_app` change in T02, stopping a failed-only app returns `{}` (running subset is empty). The current `if not instances: warn("not found")` guard would log a misleading warning. In `_stop_app_unlocked`, change the guard to distinguish "no entries existed" from "entries existed but none were running":

- `unregister_app` returns `None` when the app_key had no entries at all → log "not found" warning
- `unregister_app` returns `{}` when entries existed but none were running → log debug "cleared failed entries, no running instances to shut down" (or similar)
- `unregister_app` returns a non-empty dict → proceed to `shutdown_instances`

### Boot issue detection

In `src/hassette/core/runtime_query_service.py`, update `collect_boot_issues()` (around line 385). The current condition:

```python
elif manifest.status == "failed" and manifest.error_message:
```

Should also match `"degraded"`:

```python
elif manifest.status in ("failed", "degraded") and manifest.error_message:
```

Or use the `ManifestStatus` enum: `manifest.status in (ManifestStatus.FAILED, ManifestStatus.DEGRADED)`.

### Rename production callers of get_apps_by_key

In `src/hassette/core/app_lifecycle_service.py`, rename the two production call sites:
- Line 350 (`shutdown_all`): `self.registry.get_apps_by_key(app_key)` → `self.registry.get_running_apps(app_key)`
- Line 502 (`start_app`): `self.registry.get_apps_by_key(app_key)` → `self.registry.get_running_apps(app_key)`

These are the only two production callers (T02 renames the method definition, this task renames the callers since it already modifies this file).

### Tests

Update or add tests in:
- `tests/unit/core/test_app_lifecycle_service.py` — test that `stop_app` acquires the lock
- `tests/unit/core/test_app_lifecycle_service_operations.py` — test `reload_app` acquires lock once (no deadlock)
- `tests/unit/core/test_runtime_query_service.py` — test that a manifest with `status="degraded"` and an `error_message` appears in `collect_boot_issues()` output

## Focus

- `asyncio.Lock` is NOT reentrant. If `reload_app` calls `stop_app()` (which acquires the lock) then `start_app()` (which also acquires the lock), it deadlocks. The internal-method extraction is the standard pattern.
- The current `start_app` has a re-fetch-under-the-lock pattern (lines 480-488) that must be preserved in `_start_app_unlocked` — it handles the case where a file-watcher reconciliation replaces the manifest between `_admit_start` and the lock acquisition.
- `_fold_unblocked_apps_into_changes` at line 817 calls `self.lifecycle.start_app` and `self.lifecycle.reload_app` — these callers use the public methods, so they get the lock automatically. No changes needed there.
- Gap check found `tests/unit/core/test_app_lifecycle_service.py` (line 636, 653 mocking `get_apps_by_key`) and `tests/unit/core/test_app_lifecycle_service_operations.py` (line 52-280 mocking `get_apps_by_key`) — these need the rename to `get_running_apps` as well. Handle that rename in this task since you're already modifying these files.
- Also update `tests/unit/core/conftest.py:145,150` which mocks `get_apps_by_key` with `side_effect`.
- `tests/unit/core/test_app_lifecycle_service_coverage.py:58,73` asserts `get_apps_by_key` not called — update to `get_running_apps`.

## Verify

- [ ] FR#9: `stop_app()` acquires the per-app-key lock before unregistering — test confirms lock is held
- [ ] FR#14: `collect_boot_issues()` returns a boot issue for a manifest with `status="degraded"` and `error_message` — test confirms
