---
proposal: "Support per-instance app restart instead of full app-key restart when only one instance's config changes (#796)"
date: 2026-08-24
status: Draft
flexibility: Exploring
motivation: "Unnecessary restarts of all instances when only one instance's config changes hurts reliability (disrupts running automations, causes state loss), adds operational friction, and is a correctness gap."
constraints: "File-level changes (Python source) must still trigger full app-key restart. Edge cases around instance add/remove during reload are unknown territory."
non-goals: "None stated"
depth: normal
---

# Research Brief: Per-Instance App Restart

**Initiated by**: GitHub issue #796 -- "Support per-instance app restart instead of full app-key restart"

## Context

### What prompted this

When a multi-instance app (e.g. `motion_lights` with two instances `backyard_kitchen` and `backyard_ceiling`) has a config change to just one instance, the current system restarts all instances under that app key. This is wasteful and disruptive: the unchanged instance loses its in-flight automations, scheduler state, and event subscriptions for no reason. The issue asks for surgical per-instance restart when only config changed, while preserving full app-key restart when the Python source file changes (which affects all instances).

### Current state

The reload pipeline has four layers, all operating at **app-key granularity only**:

1. **Change detection** (`AppChangeDetector.detect_changes()` in `app_change_detector.py`): Compares `dict[str, AppManifest]` snapshots using DeepDiff. Returns a `ChangeSet` with four `frozenset[str]` fields -- each containing app_key strings, never instance indices. The detector distinguishes file changes (`reimport_apps`, matched by `app.full_path in changed_file_paths`) from config changes (`reload_apps`, from `config_diff.affected_root_keys`), but both categories are app-key-level.

2. **Lifecycle service** (`AppLifecycleService` in `app_lifecycle_service.py`): `apply_changes()` iterates the four ChangeSet buckets, calling `reload_app(app_key)` for each. `reload_app()` acquires a per-app-key lock, stops *all* instances (`_stop_app_unlocked`), then restarts *all* instances (`_start_app_unlocked`). There is no `reload_instance()` method.

3. **External entry points**: The file watcher emits `HassetteFileWatcherEvent` with only `changed_file_paths: frozenset[Path]`. The HTTP endpoints (`POST /apps/{app_key}/start|stop|reload`) take only `app_key` as a path parameter. Neither carries instance-level information.

4. **App registry** (`AppRegistry` in `app_registry.py`): Internally tracks `dict[str, dict[int, InstanceEntry]]` -- app_key to index to entry. Instance-level operations exist (`register_app(key, idx)`, `unregister_app(key, idx)`, `get(key, idx)`), but the lifecycle layer never calls them at single-instance granularity for reload.

**A bug in change detection**: The `include_paths=["root", "user_config"]` passed to DeepDiff is effectively a no-op. DeepDiff's `_skip_this` uses substring matching, and since every path begins with `"root"`, the bare `"root"` entry matches everything. Additionally, `USER_CONFIG_PATH = "user_config"` does not match the actual field name `app_config` on `AppManifest`. Net effect: `reload_apps` fires on *any* manifest attribute change (display_name, enabled, autostart, etc.), not just `app_config` changes. This is a pre-existing bug, orthogonal to #796 but worth fixing alongside it.

### Instance identity model

Each App instance is identified by:
- **`index`** (int): Positional index from `enumerate(manifest.app_config)` in `AppFactory.create_instances()`. Fragile -- reordering the TOML list shifts indices.
- **`instance_name`** (str): User-supplied via config (e.g. `"backyard_kitchen"`). Defaults to `"{ClassName}.{idx}"`. No uniqueness enforcement.
- **`unique_name`** (str): Derived from `class_name` + `instance_name`. Used as `owner_id` for Bus/Scheduler ownership tracking.

Each instance gets its own dedicated Bus, Scheduler, StateManager, Api, and AsyncCache. No resources are shared between instances of the same app_key, except the loaded Python class object (cached by file path + class name) and the `app_manifests` DB table (one row per app_key, not per instance).

The telemetry DB tracks listeners and jobs per-instance via `(app_key, instance_index)` composite keys. Row IDs are preserved across restarts via `ON CONFLICT ... DO UPDATE RETURNING id`, which assumes `(app_key, instance_index, name)` is stable -- reordering instances breaks this.

### Key constraints

- `reconcile_registrations()` scopes its DELETE/UPDATE queries by `app_key` only, not `instance_index`. A per-instance restart that skips reconciliation for untouched instances would need either (a) instance-scoped reconciliation, or (b) confidence that the untouched instances' registrations are unaffected.
- The per-app-key lock (`_app_key_locks`) serializes all lifecycle operations for the same app_key. Per-instance restart must still serialize with full-app-key operations.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Change detection | `app_change_detector.py` | Med | Low -- well-isolated, good test coverage |
| ChangeSet model | `app_change_detector.py` | Med | Med -- consumed by multiple callers |
| Lifecycle service | `app_lifecycle_service.py` | High | High -- complex, many edge cases |
| HTTP endpoints | `web/routes/apps.py` | Low | Low -- additive |
| App registry | `app_registry.py` | Low | Low -- instance-level methods already exist |
| DB reconciliation | `telemetry/repository.py` | Med | Med -- correctness-critical |
| Tests | multiple test files | High | Low -- additive |

### What already supports this

- **AppRegistry already tracks per-instance**: `_instances[app_key][index]` with `register_app(key, idx)`, `unregister_app(key, idx)`, `get_running_apps(key)`.
- **Each instance owns its own resources**: Bus, Scheduler, StateManager, Cache are all per-instance with no shared state. Shutting down one instance does not affect another's resources.
- **DB schema is per-instance**: Listeners and jobs use `(app_key, instance_index)` composite keys. The data model already supports instance-level queries.
- **DeepDiff produces instance-level paths**: When comparing `app_config` lists, DeepDiff generates paths like `root['app1'].app_config[1]['setting']` -- the index information exists in the raw diff, it is just discarded by `affected_root_keys`.
- **`shutdown_instance()` exists**: `AppLifecycleService.shutdown_instance(inst)` can shut down a single instance already.

### What works against this

- **`affected_root_keys` discards sub-path info**: The current detector uses DeepDiff's `affected_root_keys` which collapses everything to the top-level dict key. Extracting instance indices requires parsing the raw diff paths or walking the diff tree.
- **`include_paths` bug**: The filtering meant to scope diffs to config-only changes is broken. Needs fixing to avoid false positive reload triggers.
- **No `create_single_instance()` method**: `AppFactory.create_instances()` always creates *all* instances for an app_key. There is no method to create instance N alone from an existing manifest.
- **Reconciliation is app-key-scoped**: `reconcile_registrations()` and its helper queries (`_build_delete_query`, `_build_retire_query`) scope by `app_key` only. Running reconciliation after restarting one instance would incorrectly retire the other instances' still-live registrations.
- **Instance identity is positional**: Adding/removing instances shifts indices, which could cause the "restart only instance 2" logic to target the wrong instance after a list-length change.
- **`ChangeSet` is consumed by multiple paths**: `apply_changes()`, `handle_change_event()`, `_replay_pre_release_reconciliation_if_needed()`, and `_fold_unblocked_apps_into_changes()` all consume `ChangeSet`. Changing its shape affects all of them.

## Options Evaluated

### Option A: Instance-aware ChangeSet with selective restart

**How it works**: Extend `ChangeSet` to carry per-instance information for config-only changes, while keeping file-level changes at app-key granularity (since a file change affects all instances).

The change detection layer would parse DeepDiff's raw diff paths (not `affected_root_keys`) to extract the `app_config[N]` index when only specific instances changed. A new field on `ChangeSet` -- something like `reload_instances: dict[str, frozenset[int]]` mapping app_key to the set of changed instance indices -- would carry this information. When all instances changed or a non-config field changed, the app_key would land in `reload_apps` as before (full restart).

`AppLifecycleService` would gain a `reload_instance(app_key, index)` method that shuts down and recreates a single instance. This method would:
1. Shut down the targeted instance via existing `shutdown_instance()`
2. Unregister it from the registry via `unregister_app(app_key, index)`
3. Create and initialize only the replacement instance
4. Run instance-scoped reconciliation (new: scope DELETE/UPDATE by `instance_index` in addition to `app_key`)

`apply_changes()` would handle the new `reload_instances` bucket by calling `reload_instance()` for each changed index, falling back to full `reload_app()` for app_keys in `reload_apps` or `reimport_apps`.

**Pros**:
- Directly addresses the issue: unchanged instances keep running undisturbed
- Preserves full app-key restart for file changes (no behavior change for `reimport_apps`)
- Instance-level operations already exist in AppRegistry and shutdown_instance()
- DB schema already supports per-instance queries

**Cons**:
- Parsing DeepDiff raw paths to extract indices adds complexity to the detector
- Reconciliation queries need instance-scoping (new parameter, new SQL)
- Must handle edge cases: list length changes, reordering, all-instances-changed
- `ChangeSet` shape change touches all consumers (4+ call sites)
- `AppFactory` needs a `create_single_instance()` method extracted from the existing loop

**Effort estimate**: Medium -- the pieces exist, but wiring them together across the detector, lifecycle service, factory, and reconciliation layer is non-trivial.

**Dependencies**: None new. DeepDiff already provides the raw diff paths.

### Option B: Config-hash comparison with selective instance restart

**How it works**: Instead of parsing DeepDiff paths, compute a hash (or serialized snapshot) of each instance's config dict at startup and store it alongside the instance in the registry. On config reload, compare old and new per-instance hashes to determine which specific instances changed.

The flow would be:
1. On reload trigger, `refresh_config()` produces old and new manifests as today
2. For app_keys in `reload_apps`, normalize both old and new `app_config` lists
3. For each index, compare the old and new config dict (exact equality or hash)
4. Only restart instances whose config actually differs

This approach sidesteps the DeepDiff path-parsing complexity entirely. The change detection stays at app-key level (identifying *which app_keys* changed), and the instance-level diffing happens downstream in the lifecycle service when it processes a config-change reload.

**Pros**:
- Simpler than Option A: no DeepDiff path parsing, no ChangeSet schema change
- All consumers of ChangeSet remain unchanged
- Instance-level diffing logic is localized in one method
- Easy to understand and test: "did this instance's config dict change?"

**Cons**:
- Does not distinguish config-only changes from other manifest field changes (but the `include_paths` bug means this distinction does not work today anyway)
- Still needs `create_single_instance()` extraction from AppFactory
- Still needs instance-scoped reconciliation
- Slightly less precise: compares entire config dicts rather than specific fields

**Effort estimate**: Medium -- similar to Option A in lifecycle/factory/reconciliation work, but simpler on the detection side.

**Dependencies**: None.

### Option C: Minimal -- fix the detection bug, defer per-instance restart

**How it works**: Fix the `include_paths` bug in `AppChangeDetector` (change `ROOT_PATH` to match actual field paths, or remove the broken filter), improve test coverage for multi-instance scenarios, and add the `# Per-instance restart (#796)` TODO comment's infrastructure incrementally without the full per-instance restart yet.

Concrete scope:
1. Fix `include_paths` so only `app_config` changes trigger `reload_apps` (non-config manifest changes like `display_name` should not restart apps)
2. Add HTTP endpoint for per-instance stop/start (`POST /apps/{app_key}/instances/{index}/restart`) as an escape hatch
3. Add tests for multi-instance config change detection
4. Leave the automatic per-instance restart for a follow-up

**Pros**:
- Smallest change, lowest risk
- Fixes a real bug (the `include_paths` no-op)
- HTTP endpoint gives users manual per-instance control immediately
- Defers the harder automatic detection to when there is more clarity on edge cases

**Cons**:
- Does not solve the core issue: automatic config-change reload still restarts all instances
- Users must manually restart individual instances via the API
- The `include_paths` fix may surface currently-masked bugs if some callers depend on all-manifest-change detection

**Effort estimate**: Small

**Dependencies**: None.

## Concerns

### Technical risks

- **Positional identity instability**: Instance index is derived from list position in `hassette.toml`. If a config change adds, removes, or reorders instances, the "restart only index 2" logic could target the wrong instance. Options A and B both face this. Mitigation: when the list length changes or `instance_name` values shift positions, fall back to full app-key restart.

- **Reconciliation correctness**: `reconcile_registrations()` currently deletes/retires all non-live rows for an `app_key`. After restarting only instance 1, if reconciliation runs with only instance 1's live IDs, it would retire instance 0's still-running listeners. The queries must be scoped by `instance_index` to prevent this. This is the highest-risk change -- getting it wrong silently orphans or deletes active listener/job rows.

- **`include_paths` bug masking**: Fixing the DeepDiff `include_paths` bug could change which changes trigger reloads. Currently, changing `display_name` triggers a reload; after the fix, it would not. This is correct behavior but could surprise users who depended on the side effect.

### Complexity risks

- **Edge case matrix**: The interaction of per-instance restart with instance addition/removal, reordering, `autostart=false`, `enabled=false`, pre-release reconciliation, and the `--app` filter creates a large test matrix. Each combination needs consideration.

- **Two restart paths**: After this change, `reload_app()` (full) and `reload_instance()` (selective) would coexist. Callers must choose correctly, and both must maintain the same invariants (event emission, reconciliation, error handling, structlog context binding).

### Maintenance risks

- **Positional identity debt**: The deeper problem is that instance identity is positional (list index), not content-based (instance_name). Per-instance restart works around this but does not fix it. A future change to content-based identity (keying by `instance_name` rather than list position) would be a better foundation but is a larger change.

## Open Questions

- [ ] **Should instance identity be positional or name-based?** Currently `index` comes from `enumerate()`. If the TOML list is reordered, index 0 becomes a different instance. Should the framework match instances by `instance_name` instead of position? This would make per-instance restart more robust but is a larger change with DB migration implications (the `instance_index` column is an integer, not a string).

- [ ] **What should happen when the instance list length changes?** If old config has 2 instances and new has 3, is that a "new instance added" (start only index 2) or a "full restart" (because the list structure changed)? Similarly for removal: stop only the removed instance, or restart everything?

- [ ] **Should the `include_paths` bug be fixed as a prerequisite or alongside?** The bug is orthogonal but affects which changes trigger reloads. Fixing it first (Option C's step 1) would give a cleaner baseline for the per-instance work.

- [ ] **Does the HTTP API need per-instance endpoints?** The REST API currently has no way to target a specific instance. Adding `POST /apps/{app_key}/instances/{index}/restart` is straightforward and useful regardless of the automatic detection.

- [ ] **How should the frontend reflect per-instance restart?** The dashboard shows per-instance status already (via `AppInstanceInfo`). A per-instance restart would be visible as one instance cycling through STOPPING/STARTING while others stay RUNNING. No frontend changes are likely needed for the automatic case, but a manual per-instance restart button would need UI work.

## Recommendation

**Option B (config-hash comparison) is the strongest starting point**, with the `include_paths` bug fix from Option C as a prerequisite.

The reasoning: Option B localizes the instance-level diffing in the lifecycle service rather than threading it through the ChangeSet model and all its consumers. The ChangeSet stays at app-key granularity (which is the right abstraction for "what app_keys need attention"), and the lifecycle service decides internally whether to do a full restart or a selective one. This minimizes blast radius and keeps the harder logic in one place.

Suggested sequence:

1. **Fix the `include_paths` bug** in `AppChangeDetector` -- prerequisite, small, independently valuable. Fix `ROOT_PATH`/`USER_CONFIG_PATH` constants or remove the broken filter. Add tests for non-config manifest changes.

2. **Extract `create_single_instance()` from `AppFactory`** -- extract the inner loop body of `create_instances()` into a method that creates one instance by index. Both the existing bulk path and the new selective path call it.

3. **Add instance-scoped reconciliation** -- extend `_build_delete_query`/`_build_retire_query` with an optional `instance_index` parameter. When provided, scope the WHERE clause to `app_key AND instance_index`.

4. **Implement `reload_instance()` on `AppLifecycleService`** -- shut down one instance, recreate it from the current manifest, run instance-scoped reconciliation. Use the existing per-app-key lock.

5. **Wire the selective logic into `apply_changes()`** -- when processing `reload_apps`, compare old and new per-instance configs. If only some instances changed and the list length is the same, call `reload_instance()` for each changed index. Otherwise fall back to `reload_app()`.

6. **Add HTTP endpoint** for manual per-instance restart as a bonus.

This sequence is incrementally landable -- each step is independently valuable and testable, and steps 1-3 are prerequisite infrastructure that reduces risk for steps 4-5.

### Suggested next steps

1. Write a design doc via `/mine-define` covering the selective restart behavior, the fallback-to-full-restart rules, and the reconciliation scoping change.
2. Fix the `include_paths` bug as a standalone PR (step 1 above) -- it is independently valuable and reduces noise for the per-instance work.
3. Prototype step 4 (the `reload_instance` method) in a branch to validate the lifecycle invariants and edge cases before committing to the full plan.
