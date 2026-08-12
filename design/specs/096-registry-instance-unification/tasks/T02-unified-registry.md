---
task_id: "T02"
title: "Replace dual-dict with unified InstanceEntry registry"
status: "done"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#8", "FR#10", "FR#11", "FR#12", "FR#13", "FR#16", "AC#1", "AC#2", "AC#3", "AC#4", "AC#9", "AC#10"]
---

## Summary

The core structural change. Replace `_apps` and `_failed_apps` with a single `_instances: dict[str, dict[int, InstanceEntry]]` dict. Create the `InstanceEntry` frozen dataclass. Update every registry method to work with the unified structure. Rename `get_apps_by_key` → `get_running_apps`, add `get_instances`. Delete dead code (`clear_failures`, `iter_all_instances`). Fix correctness bugs (per-index clearing, dedup). Add degraded status derivation. Resolve instance names from manifest config for failed entries. The characterization tests from T01 must still pass after this change (proving behavior preservation for existing status paths).

## Target Files

- modify: `src/hassette/core/app_registry.py`
- modify: `tests/unit/core/test_app_registry.py`
- modify: `tests/unit/core/test_overlay_runtime_state.py`
- read: `src/hassette/core/app_factory.py`
- read: `src/hassette/schemas/app_snapshots.py`
- read: `src/hassette/types/enums.py`
- read: `design/specs/096-registry-instance-unification/design.md`

## Prompt

### InstanceEntry dataclass

Add a frozen dataclass at the top of `src/hassette/core/app_registry.py` (private to this module):

```python
@dataclass(frozen=True)
class InstanceEntry:
    app: App[AppConfig] | None
    status: ResourceStatus
    error: Exception | None = None
    error_message: str | None = None
    error_traceback: str | None = None

    @property
    def instance_name(self) -> str | None:
        return self.app.app_config.instance_name if self.app else None
```

### Replace storage

In `__init__`, replace:
- `self._apps: dict[str, dict[int, App[AppConfig]]] = defaultdict(dict)` → remove
- `self._failed_apps: dict[str, list[tuple[int, Exception]]] = defaultdict(list)` → remove
- Add: `self._instances: dict[str, dict[int, InstanceEntry]] = defaultdict(dict)`

`_blocked_apps`, `_manifests`, `_only_apps` are unchanged.

### Update methods

**`register_app(app_key, index, app)`** — create `InstanceEntry(app=app, status=ResourceStatus.RUNNING)` and store at `_instances[app_key][index]`. No coarse clear — just replace the single entry at that key.

**`record_failure(app_key, index, error)`** — create `InstanceEntry(app=None, status=ResourceStatus.FAILED, error=error, error_message=str(error), error_traceback=get_traceback_string(error) if error.__traceback__ else None)` and store at `_instances[app_key][index]`. Dict keying naturally deduplicates.

**`unregister_app(app_key, index=None)`** — when `index is None`: pop ALL entries for app_key from `_instances`, return only the `App` objects from entries where `entry.app is not None` as `dict[int, App]`. When `index` is given: pop the single entry, return `{index: entry.app}` if entry was running, `None` otherwise. Clean up empty inner dicts.

**Rename `get_apps_by_key` → `get_running_apps`** — return `{idx: entry.app for idx, entry in self._instances.get(app_key, {}).items() if entry.app is not None}`.

**Add `get_instances(app_key)`** — return `self._instances.get(app_key, {}).copy()`.

**`__contains__`** — return True only if app_key has at least one entry with `entry.app is not None`.

**`app_keys()`** — return keys where at least one entry has `entry.app is not None`.

**`all_apps()`** — return all `entry.app` where `entry.app is not None`.

**`get(app_key, index=0)`** — return `entry.app` if the entry exists and has an app, else `None`.

**`clear_all()`** — clear `_instances`, `_blocked_apps`.

**Delete `clear_failures()`** — zero production callers.

**Delete `iter_all_instances()`** — zero production callers.

### Status derivation

Update `build_manifest_info()` status priority chain:

```
disabled > blocked > degraded (has_running AND has_failed) > running > failed > stopped
```

Where `has_running = any(e.app is not None for e in entries.values())` and `has_failed = any(e.status == ResourceStatus.FAILED for e in entries.values())` from `_instances.get(app_key, {})`. Use `ManifestStatus` enum values.

### Instance name resolution for failed entries

Update `info_from_failure` (or its replacement inline in snapshot methods) to look up the real `instance_name` from manifest config:

```python
manifest = self._manifests.get(app_key)
if manifest:
    configs = AppFactory.normalize_configs(manifest.app_config)
    if index < len(configs):
        instance_name = configs[index].get("instance_name", f"{manifest.class_name}.{index}")
    else:
        instance_name = f"{manifest.class_name}.{index}"
else:
    instance_name = f"Unknown.{index}"
```

`AppFactory.normalize_configs` is a static method — import it. `class_name` follows the same pattern: `manifest.class_name` when available, `"Unknown"` otherwise.

### Snapshot methods

Update `get_snapshot()` and `build_manifest_info()` instance-building loops to iterate `_instances[app_key].items()` instead of separate `_apps`/`_failed_apps` dicts.

### Unit tests

Update `tests/unit/core/test_app_registry.py`:
- Remove tests for `clear_failures()` and `iter_all_instances()`
- Update existing tests that reference `_apps`/`_failed_apps` directly
- Add new tests for:
  - Degraded status: register 3 instances, fail index 0, assert `build_manifest_info().status == "degraded"` (AC#1)
  - Per-index clearing: `register_app(key, 0, app)` after `record_failure(key, 2, error)` → index 2's failure preserved (AC#2)
  - Dedup: `record_failure(key, 0, err1)` then `record_failure(key, 0, err2)` → one entry with err2 (AC#3)
  - `get_running_apps` returns only running when failed entries exist (AC#4)
  - Instance name from manifest config for failed entries (AC#9)
  - `clear_failures` and `iter_all_instances` no longer exist (AC#10)
- The characterization tests from T01 must still pass
- Update `tests/unit/core/test_overlay_runtime_state.py` — `test_status_priority_running_beats_failed` (lines 99-111) registers a running + failed instance and asserts `status == "running"`. This must change to assert `status == "degraded"` after the new derivation logic. Also update any `ManifestStatus` Literal references to use the StrEnum import.

## Focus

- `AppFactory.normalize_configs()` at `src/hassette/core/app_factory.py:121-127` is a static method. Import it at the top of `app_registry.py` — there's no circular import risk since `app_factory.py` already TYPE_CHECKING-imports from `app_registry.py`.
- The `_instances` dict uses `defaultdict(dict)` — be careful with the empty-inner-dict cleanup in `unregister_app`. After popping entries, check if the inner dict is empty and delete the outer key to avoid phantom keys in `app_keys()`.
- `info_from_running` and `info_from_failure` are only called within `app_registry.py` itself (verified: zero external callers). They can be refactored inline or kept as private methods.
- `get(app_key, index)` must continue returning `App | None`, NOT `InstanceEntry | None` — callers expect the `App` object directly.
- The `stop_app` guard fix for failed-only apps (edge case in design) will be handled in T04 alongside the lock fix. This task changes `unregister_app` semantics but does not modify `stop_app` itself.
- Tests in `tests/unit/core/` — check `tests/unit/core/CLAUDE.md` for directory-specific fixtures and conventions before writing tests.

## Verify

- [ ] FR#1: `AppRegistry` stores all instance state in `_instances: dict[str, dict[int, InstanceEntry]]` — no `_apps` or `_failed_apps` exist
- [ ] FR#2: `InstanceEntry` is a frozen dataclass with `app`, `status`, `error`, `error_message`, `error_traceback` fields and `instance_name` property
- [ ] FR#3: `register_app` creates a RUNNING `InstanceEntry` and stores at `_instances[app_key][index]`, replacing any prior entry
- [ ] FR#4: `record_failure` creates a FAILED `InstanceEntry` and stores at `_instances[app_key][index]`, replacing any prior entry (no duplicates)
- [ ] FR#5: `build_manifest_info()` returns `ManifestStatus.DEGRADED` when an app_key has both running and failed entries
- [ ] FR#8: `get_running_apps(app_key)` returns only entries where `entry.app is not None`
- [ ] FR#10: `clear_failures()` and `iter_all_instances()` are removed from the codebase
- [ ] FR#11: Failed instance snapshot entries use `instance_name` from manifest config via `normalize_configs()`
- [ ] FR#12: `__contains__` and `app_keys()` consider only entries with running apps
- [ ] FR#13: `get_instances(app_key)` returns all entries (running and failed) as `dict[int, InstanceEntry]`
- [ ] FR#16: `unregister_app(app_key)` pops ALL entries and returns only running `App` objects; `unregister_app(app_key, index)` pops a single entry
- [ ] AC#1: Test confirms `build_manifest_info().status == "degraded"` for mixed running/failed
- [ ] AC#2: Test confirms per-index clearing (index 2 failure preserved after index 0 re-registration)
- [ ] AC#3: Test confirms dedup (two failures at same index → one entry with last error)
- [ ] AC#4: Test confirms `get_running_apps` returns only running entries
- [ ] AC#9: Test confirms failed entries show configured `instance_name` from manifest
- [ ] AC#10: `clear_failures` and `iter_all_instances` do not exist — grep returns zero results
