# Design: Per-Instance App Restart

**Date:** 2026-08-24
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-08-24-per-instance-restart/research.md

## Problem

When a multi-instance app (e.g. `motion_lights` with instances `backyard_kitchen` and `backyard_ceiling`) has a config change to just one instance, the current system restarts all instances under that app key. The unchanged instance loses its in-flight automations, scheduler state, and event subscriptions for no reason. This disrupts running automations unnecessarily and makes iterative config tuning painful for multi-instance apps.

Additionally, the change detection filter meant to restrict reloads to config-only changes is broken: `ROOT_PATH = "root"` matches every DeepDiff path via substring matching, and `USER_CONFIG_PATH = "user_config"` does not match the actual field name `app_config`. Any manifest attribute change (display_name, autostart, etc.) triggers a reload, not just config changes.

## Goals

- A config change to one instance restarts only that instance; sibling instances continue running undisturbed.
- File-level changes (Python source) continue to trigger full app-key restart (all instances), since the class affects all of them.
- Per-instance lifecycle operations (start/stop/reload) are available via HTTP API.
- The `include_paths` bug in `AppChangeDetector` is fixed so only `app_config` changes trigger reloads.
- When the instance list length changes (instances added or removed), the system falls back to full app-key restart.

## Non-Goals

- **Content-based instance identity** — keying instances by `instance_name` instead of positional index. This would require a DB migration (`instance_index` column is integer, not string) and is a larger change. Positional identity is accepted for this scope.
- **Frontend per-instance restart button** — the dashboard already shows per-instance status; a UI control for per-instance restart is a separate feature.
- **CLI per-instance lifecycle commands** — the CLI currently has no lifecycle commands at all (only query commands: `health`, `activity`, `config`, `source`). Adding per-instance CLI commands is a follow-up issue.

## User Scenarios

### App author: Automation developer

- **Goal:** Tune one instance's config without disrupting other running instances
- **Context:** Developing or tuning a multi-instance app with different configs per room/zone

#### Automatic config reload

1. **Edit `hassette.toml` to change one instance's setting** (e.g. `motion_lights[1].off_delay = 30`)
   - Sees: File watcher detects the change
   - Then: System compares old and new per-instance configs, identifies only instance 1 changed

2. **System restarts only the changed instance**
   - Sees: Instance 1 cycles through STOPPING → STARTING → RUNNING in the dashboard
   - Sees: Instance 0 remains RUNNING with no interruption
   - Then: The changed config takes effect for instance 1

#### Manual per-instance restart via HTTP

1. **Send `POST /apps/{app_key}/instances/{index}/reload`**
   - Sees: 202 response confirming the reload was accepted
   - Then: Only the targeted instance reloads; siblings are unaffected

2. **Send `POST /apps/{app_key}/instances/{index}/stop`**
   - Sees: 202 response; the targeted instance stops
   - Sees: Other instances continue running

3. **Send `POST /apps/{app_key}/instances/{index}/start`**
   - Sees: 202 response; the targeted instance starts from current config
   - Then: Instance initializes with the current manifest config at that index

## Functional Requirements

- **FR#1** When a config-only change affects a subset of instances for an app key, only the changed instances restart; unchanged instances continue running with their existing state.
- **FR#2** When a file-level change occurs (Python source file modified), all instances for the affected app key restart, regardless of per-instance config differences.
- **FR#3** When the instance list length changes between old and new config (instances added or removed), all instances for that app key undergo a full restart.
- **FR#4** Per-instance DB reconciliation scopes all reconciliation SQL (the `_build_delete_query`/`_build_retire_query` builder paths and the hand-written `once=True` listener cleanup block) by both `app_key` and `instance_index`, so restarting one instance does not retire sibling instances' listener/job rows.
- **FR#5** The `include_paths` filter in `AppChangeDetector` correctly restricts config-change detection to `app_config` field changes only; non-config manifest attribute changes (display_name, autostart, enabled) do not trigger reloads.
- **FR#6** HTTP endpoints exist for per-instance start, stop, and reload at `POST /apps/{app_key}/instances/{index}/{action}`.
- **FR#7** Per-instance reload emits the same `HassetteAppStateEvent` lifecycle events as full app-key reload, scoped to the affected instance only.
- **FR#8** Per-instance operations acquire the same per-app-key lock as full app-key operations, serializing all lifecycle operations for the same app key.

## Edge Cases

- **Instance list grows:** Old config has 2 instances, new config has 3. Falls back to full app-key restart (FR#3). The new instance is created during the full restart.
- **Instance list shrinks:** Old config has 3 instances, new config has 2. Falls back to full app-key restart (FR#3). The removed instance is shut down during the full restart.
- **All instances change:** Old and new configs have the same length but every instance's config dict differs. Each instance reloads individually (functionally equivalent to full reload but executed per-instance).
- **Pure reorder (same dicts, swapped positions):** `DeepDiff(ignore_order=True)` treats this as zero diff, so the app key never enters `reload_apps` and no restart occurs. This is a known limitation of positional identity combined with `ignore_order=True`. To reassign configs to different indices, also change a value — the value change will be detected.
- **No instances change:** Config reload fires but per-instance comparison shows no differences. No restarts occur.
- **Non-config manifest change only:** `display_name` or `autostart` changes but `app_config` is identical. After the `include_paths` fix (FR#5), this does not trigger a reload.
- **Per-instance restart of a failed instance:** The target index has a failed entry in the registry. The restart clears the failed entry and attempts to create and initialize a fresh instance.
- **Per-instance start/reload during bootstrap:** Before bootstrap release, per-instance `start` and `reload` HTTP endpoints return 409 (same as full app-key endpoints, via `AppAdmissionMode.REJECT_IF_UNRELEASED`). The `stop` endpoint does not go through admission — it works before bootstrap release, matching the existing full app-key `stop` behavior.
- **Concurrent per-instance and full-app reload:** Both paths acquire the same per-app-key lock (FR#8), so they serialize correctly.

## Acceptance Criteria

- **AC#1** (FR#1) A unit test with a 2-instance app where only instance 1's config changes verifies that `shutdown_instance` is called only for instance 1, and `create_single_instance` is called only for index 1.
- **AC#2** (FR#2) A unit test where a file change triggers `reimport_apps` verifies that all instances for the app key reload via `reload_app`, not `reload_instance`.
- **AC#3** (FR#3) A unit test where the instance list length changes verifies that the system falls back to full `reload_app`.
- **AC#4** (FR#4) A unit test for `_build_delete_query`, `_build_retire_query`, and the `once=True` cleanup SQL with `instance_index` parameter verifies each SQL path includes `AND instance_index = :instance_index`.
- **AC#5** (FR#5) A unit test changes only `display_name` on a manifest and verifies `detect_changes` does not include the app key in `reload_apps`.
- **AC#6** (FR#6) Integration tests for `POST /apps/{app_key}/instances/{index}/start`, `stop`, and `reload` verify 202 responses and correct lifecycle behavior.
- **AC#7** (FR#1) An integration test using `HassetteHarness` with a multi-instance app changes one instance's config and verifies only that instance reloaded while the other remained running.
- **AC#8** (FR#7) A unit test verifies that per-instance reload emits `HassetteAppStateEvent` with the correct instance identity (app_key, index, instance_name).
- **AC#9** (FR#8) A unit test verifies that per-instance operations acquire the per-app-key lock, serializing with full app-key operations.
- **AC#10** (FR#4) An integration test sets up a 2-instance app, records the sibling instance's live listener/job row IDs, calls `reload_instance()` on the other index, then queries the DB and asserts the sibling's rows are unaffected (same `id`, `retired_at IS NULL`, no row-count change for that `instance_index`).

## Key Constraints

- `reload_instance` must acquire the same per-app-key lock (`_app_key_locks`) as `reload_app` — never a per-instance lock. A per-instance lock would allow a selective restart and a full restart to run concurrently for the same app key, racing on the registry.
- The ChangeSet model must not change shape. Option B (config-hash comparison in the lifecycle service) was chosen specifically to avoid touching ChangeSet's consumers. The per-instance diffing happens downstream in `apply_changes`, not in the change detector.
- Instance identity is positional (list index from `enumerate()`). Do not introduce name-based identity resolution in this change.

## Dependencies and Assumptions

- **DeepDiff `include_paths` uses substring matching.** The `ROOT_PATH = "root"` constant matches every path because every DeepDiff path starts with `"root"`. This is documented DeepDiff behavior and confirmed by the research brief. The fix changes the constants to match actual field paths, not the matching algorithm.
- **No shared mutable state between instances of the same app key.** Each instance owns its own Bus, Scheduler, StateManager, Api, and AsyncCache. Confirmed by reading `AppFactory.create_instances()` and `App.__init__()`. This means shutting down one instance has no side effects on siblings.
- **Pure reorders of the instance list are not detected.** `DeepDiff(ignore_order=True)` treats a reorder of the `app_config` list (same dicts, swapped positions) as zero diff. The app key never enters `reload_apps`, so the per-instance comparison in `apply_changes` never runs. To reassign configs to different indices, also change a value — the value change will be detected. This is a known limitation of positional identity combined with `ignore_order=True`; fixing it would require either removing `ignore_order` (which could break dict key ordering tolerance) or adding a separate ordered comparison for `app_config` lists.
- **CLI per-instance commands are a follow-up.** The CLI currently has no lifecycle commands at all. A GitHub issue will be filed for per-instance CLI commands (`hassette app reload <key> --instance <index>`, `hassette app stop <key> --instance <index>`, `hassette app start <key> --instance <index>`).

## Architecture

### Approach: Option B — Config-equality comparison in the lifecycle service

The ChangeSet stays at app-key granularity. When `apply_changes()` processes a config-change reload (`reload_apps` bucket), it compares old and new per-instance config dicts. If the instance list length is the same and only some instances changed, it calls `reload_instance()` for each changed index. Otherwise, it falls back to `reload_app()`.

This localizes the per-instance logic in one place (the lifecycle service) rather than threading it through the ChangeSet model and all its consumers (`apply_changes`, `handle_change_event`, `_replay_pre_release_reconciliation_if_needed`, `_fold_unblocked_apps_into_changes`).

**Layering contract:** `AppChangeDetector`'s job is reduced to "should this app_key be looked at at all" (app-key granularity, reorder-tolerant via `ignore_order=True`). `apply_changes()`'s positional dict-equality pass is the authoritative determination of "which indices changed." The two algorithms operate at different granularities by design — they need not agree on the set of "things that changed."

### Component changes

**`AppChangeDetector`** (`src/hassette/core/app_change_detector.py`):
- Fix `ROOT_PATH` and `USER_CONFIG_PATH` constants. The fix depends on DeepDiff's path format for the `include_paths` parameter — the paths must match the actual attribute access paths DeepDiff generates (e.g., `root['app_key'].app_config`). If the substring-matching behavior makes precise filtering impractical, remove `include_paths` entirely and filter in the detector's own logic after the diff.

**`AppFactory`** (`src/hassette/core/app_factory.py`):
- Extract `create_single_instance(app_key, manifest, index, config_dict, app_class)` from the inner loop of `create_instances()`. Both `create_instances()` and the new `reload_instance()` path call it. `create_instances()` becomes a loop calling `create_single_instance()` for each index.
- Fix the class-load failure path (`app_factory.py:52`): `record_failure(app_key, 0, load_error)` hardcodes index `0`. This fires inside `create_instances()` before the per-instance loop, so it is NOT part of the `create_single_instance()` extraction (which receives an already-loaded `app_class`). For the per-instance reload path, `_reload_instance_unlocked()` must call `factory.load_class()` itself and, on failure, `record_failure(app_key, index, load_error)` with the actual target index. The existing `create_instances()` bulk path can keep index `0` as the representative failure entry since the class failure applies to all instances equally.

**`AppLifecycleService`** (`src/hassette/core/app_lifecycle_service.py`):
- Add `reload_instance(app_key, index, force_reload=False, *, admission_mode=AppAdmissionMode.REJECT_IF_UNRELEASED)` and `_reload_instance_unlocked(app_key, index, force_reload=False)`: the public method calls `_admit_start()` (producing 409 pre-bootstrap-release), then acquires per-app-key lock and calls the unlocked helper (same pattern as `reload_app`/`_stop_app_unlocked`/`_start_app_unlocked`). The unlocked helper follows the `_stop_app_unlocked` pattern — unregisters the instance first (capturing failed-entry info for event emission), shuts down only if a running `App` object exists (failed entries have no `App` to shut down), creates a replacement via `create_single_instance()`, initializes it, runs instance-scoped reconciliation. This mirrors how `_stop_app_unlocked` handles the failed-vs-running distinction.
- Add `stop_instance(app_key, index)` (no admission check — matches existing `stop_app` convention) and `start_instance(app_key, index, *, admission_mode=AppAdmissionMode.REJECT_IF_UNRELEASED)` (calls `_admit_start()` — matches existing `start_app` convention) for the HTTP endpoints.
- All three per-instance methods (`reload_instance`, `stop_instance`, `start_instance`) must re-validate `index` against the current manifest's instance count after acquiring the per-app-key lock, mirroring `start_app()`'s existing post-lock re-fetch pattern (`app_lifecycle_service.py:478-491`). An out-of-range index at that point is a no-op (log + return), not an exception.
- `reload_instance`/`stop_instance` must scope failed-entry info capture to the target index only (e.g., check `self.registry.get_instances(app_key).get(index)` for a failed entry) rather than reusing the app-key-wide `get_failed_instance_infos(app_key)`, which would emit STOPPED events for unrelated sibling failed indices.
- Thread `instance_index` through the full call chain: `initialize_instances(instance_index=None)` → `reconcile_app_registrations(instance_index=None)` → `command_executor.reconcile_registrations(instance_index=None)` → `TelemetryRepository.reconcile_registrations(instance_index=None)`. The per-instance reload path passes the target index; the existing bulk path passes `None` (backward-compatible). `initialize_instances()` is the real entry point — it calls `reconcile_app_registrations()` at line 225.
- Modify `apply_changes(changes, original_config, current_config)`: add explicit parameters for old and new configs (the field-snapshot alternative is worse for testability — hidden mutable state that tests would need to prime out-of-band). When processing `reload_apps`, compare old and new per-instance configs. Call `_reload_instance_unlocked()` for changed indices under a single lock acquisition when list length is unchanged; fall back to `reload_app()` otherwise. The existing `refresh_config()` already returns `(original_apps_config, current_apps_config)`, and `handle_change_event()` already has both. This signature change touches 13 call sites (3 production: `handle_change_event`, `_replay_pre_release_reconciliation_if_needed`, `AppHandler.apply_changes()` facade; 10 test call sites: `tests/unit/core/test_app_lifecycle_service.py` (7 sites), `tests/unit/core/test_app_lifecycle_service_operations.py` (1 site), `tests/integration/test_apps.py` (2 sites via `app_handler.apply_changes()`)).

**`AppHandler`** (`src/hassette/core/app_handler.py`):
- Add thin facade delegates: `reload_instance(app_key, index, force_reload=False)`, `stop_instance(app_key, index)`, `start_instance(app_key, index)`, delegating to `self.lifecycle.*`.
- Update `apply_changes()` facade to match the lifecycle service's new signature (`apply_changes(changes, original_config, current_config)`).

**Telemetry reconciliation** (`src/hassette/core/telemetry/repository.py`):
- Extend `_build_delete_query()` and `_build_retire_query()` with an optional `instance_index: int | None` parameter. When provided, add `AND instance_index = :instance_index` to the WHERE clause. The existing `extra_where` parameter could achieve this, but a dedicated typed parameter is preferred for safety — `extra_where` accepts arbitrary SQL fragments, while `instance_index` is a parameterized bind value immune to injection and self-documenting at every call site.
- The hand-written `once=True` listener cleanup SQL block in `reconcile_registrations()` (lines 625-654) also needs `instance_index` scoping — it bypasses the builder functions entirely, so extending only the builders would leave this path scoped by `app_key` alone, silently deleting sibling instances' `once=True` listeners on a per-instance reload. Add `AND instance_index = :instance_index` when the parameter is provided.
- `TelemetryRepository.reconcile_registrations()` and `CommandExecutor.reconcile_registrations()` both gain the same optional `instance_index` parameter.
- Single-source the `AND instance_index = :instance_index` fragment construction into one shared helper (e.g., a function returning the clause + params when `instance_index` is not None) interpolated into all five SQL statements, rather than five independent call sites each building it independently.

**HTTP routes** (`src/hassette/web/routes/apps.py`):
- Add per-instance endpoints: `POST /apps/{app_key}/instances/{index}/start`, `POST /apps/{app_key}/instances/{index}/stop`, `POST /apps/{app_key}/instances/{index}/reload`. Follow the existing `_run_app_action` pattern, including the `responses={409: ...}` OpenAPI decorator on `start` and `reload` (but not `stop`, matching the existing full app-key convention where `stop` skips admission). Validate that `index` is within the current manifest's instance count; return 404 for out-of-range indices. The `reload` endpoint hardcodes `force_reload=True`, matching the existing full app-key HTTP reload convention and closing the same #1005-shaped gap at instance granularity.

### Data flow for selective restart

```
handle_change_event()
  → refresh_config() → (original_config, current_config)
  → detect_changes() → ChangeSet (app-key level, unchanged)
  → apply_changes(changes, original_config, current_config)
      → for app_key in changes.reload_apps:
          if not should_auto_reconcile(app_key):  # preserve autostart=false dormancy
              log.debug("Skipping reload of autostart=false app %s (not running)", app_key)
              continue
          old_instances = normalize_configs(original_config[app_key].app_config)
          new_instances = normalize_configs(current_config[app_key].app_config)
          if len(old_instances) != len(new_instances):
              reload_app(app_key)  # fallback
          else:
              changed_indices = [i for i in range(len(new_instances)) if old_instances[i] != new_instances[i]]
              if changed_indices:
                  async with _get_app_key_lock(app_key):  # single lock for entire batch
                      for idx in changed_indices:
                          _reload_instance_unlocked(app_key, idx)
```

## Implementation Preferences

- Follow existing `reload_app()` pattern for `reload_instance()` — acquire per-app-key lock, call unlocked stop/start bodies.
- Use simple dict equality (`old_config != new_config`) for per-instance comparison, not hashing. Config dicts from TOML are plain dicts; equality comparison is deterministic.
- Follow existing HTTP route pattern in `web/routes/apps.py` — reuse `_run_app_action` helper.
- Instance-scoped reconciliation uses the same SQL builder pattern (`_build_delete_query`, `_build_retire_query`) with an additive parameter, not a separate function.

## Replacement Targets

- **`ROOT_PATH = "root"` and `USER_CONFIG_PATH = "user_config"` in `app_change_detector.py`**: Replace with correct path constants or remove the `include_paths` parameter and implement filtering in the detector's own logic.

## Convention Examples

### Service lifecycle method structure

**Source:** `src/hassette/core/app_lifecycle_service.py` — `reload_app()`

```python
async def reload_app(
    self,
    app_key: str,
    force_reload: bool = False,
    *,
    admission_mode: AppAdmissionMode = AppAdmissionMode.REJECT_IF_UNRELEASED,
) -> None:
    self.logger.debug("Reloading app %s", app_key)
    await self._admit_start(app_key=app_key, admission_mode=admission_mode)
    try:
        async with self._get_app_key_lock(app_key):
            await self._stop_app_unlocked(app_key)
            app_manifest = self.registry.get_manifest(app_key)
            if not app_manifest:
                self.logger.debug("Skipping disabled or unknown app %s", app_key)
                return
            await self._start_app_unlocked(app_key, app_manifest, force_reload)
    except Exception:
        self.logger.error("Failed to reload app %s:\n%s", app_key, get_short_traceback())
```

### SQL builder pattern for reconciliation

**Source:** `src/hassette/core/telemetry/repository.py` — `_build_delete_query()`

```python
def _build_delete_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_fk: str,
    extra_where: str = "",
) -> tuple[str, dict]:
    _assert_reconcile_identifiers(table, history_fk)
    params: dict[str, Any] = {"app_key": app_key}
    if live_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(live_ids)))
        params.update({f"id_{i}": v for i, v in enumerate(live_ids)})
        not_in_clause = f"AND id NOT IN ({placeholders})"
    else:
        not_in_clause = ""
    sql = f"""
        DELETE FROM {table}
        WHERE app_key = :app_key{extra_where}
          {not_in_clause}
          AND NOT EXISTS (
              SELECT 1 FROM executions WHERE {history_fk} = {table}.id
          )
    """
    return sql, params
```

### AppHandler thin facade delegate

**Source:** `src/hassette/core/app_handler.py` — `reload_app()`

```python
async def reload_app(self, app_key: str, force_reload: bool = False) -> None:
    """Reload an app by key — delegates to lifecycle service."""
    await self.lifecycle.reload_app(app_key, force_reload=force_reload)
```

### HTTP route action pattern

**Source:** `src/hassette/web/routes/apps.py` — `reload_app()`

```python
@router.post("/apps/{app_key}/reload", status_code=202, response_model=ActionResponse)
async def reload_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    return await _run_app_action(
        "reload", app_key, hassette, request, lambda: hassette.app_handler.reload_app(app_key, force_reload=True)
    )
```

## Alternatives Considered

### Option A: Instance-aware ChangeSet with DeepDiff path parsing

Extend `ChangeSet` to carry per-instance information (e.g., `reload_instances: dict[str, frozenset[int]]`). Parse DeepDiff's raw diff paths to extract `app_config[N]` indices.

**Rejected because:** Changes the ChangeSet schema, which is consumed by `apply_changes()`, `handle_change_event()`, `_replay_pre_release_reconciliation_if_needed()`, and `_fold_unblocked_apps_into_changes()`. Higher blast radius with no functional benefit over Option B. DeepDiff path parsing adds fragile string parsing that could break with DeepDiff version changes.

### Option C: Fix the detection bug only, defer per-instance restart

Fix `include_paths`, add manual HTTP endpoint, defer automatic selective restart.

**Rejected because:** Does not solve the core issue. The user's primary scenario — automatic selective restart on config change — remains unaddressed. The `include_paths` fix is a prerequisite but not sufficient on its own.

## Test Strategy

### Required Test Types

- **Unit tests** — `AppChangeDetector` bug fix (single module), `AppFactory.create_single_instance` extraction (single module), `reload_instance` on `AppLifecycleService` (mock-based), instance-scoped reconciliation queries (single module).
- **Integration tests** — selective restart flow via `HassetteHarness` (crosses app lifecycle + registry + reconciliation boundaries), HTTP per-instance endpoints (crosses web + lifecycle boundaries).

### Existing Tests to Adapt

- `tests/unit/core/test_app_change_detector.py` — add tests for the `include_paths` fix; existing tests should still pass since the bug made detection overly broad (the fix narrows it).
- `tests/unit/core/test_app_lifecycle_service.py` and `test_app_lifecycle_service_operations.py` — may need updates if `apply_changes` signature changes to accept old config.
- `tests/integration/web_api/test_endpoints.py` — add tests for the new per-instance HTTP endpoints.

### New Test Coverage

- FR#1: Unit test — multi-instance app, one instance config changes, verify only that instance reloads (mock `shutdown_instance`, `create_single_instance`).
- FR#1: Unit test — same length, all configs differ, verify each reloads individually.
- FR#2: Unit test — file change triggers `reimport_apps`, verify all instances reload via `reload_app` (covered by AC#2).
- FR#3: Unit test — instance list length changes, verify fallback to `reload_app`.
- FR#4: Unit test — `_build_delete_query`, `_build_retire_query`, and `once=True` cleanup SQL with `instance_index` parameter.
- FR#5: Unit test — non-config manifest change does not trigger reload.
- FR#6: Integration test — HTTP per-instance endpoints return 202 and trigger correct lifecycle methods.
- FR#7: Unit test — per-instance reload emits correct lifecycle events.
- FR#8: Unit test — per-instance operations use the per-app-key lock.

### Tests to Remove

No tests to remove.

## Smoke Test

**Verification surface:** HTTP API and log output against a running hassette instance with a multi-instance app.

**Scenario:** Start hassette with a 2-instance app (e.g., `motion_lights` with instances `backyard_kitchen` and `backyard_ceiling`). Edit `hassette.toml` to change only the `backyard_ceiling` instance's config (instance index 1). Observe logs confirming only instance 1 restarted. Then send `POST /apps/motion_lights/instances/0/reload` and confirm instance 0 reloads independently.

**Success:** Logs show "Reloading instance 1 of app motion_lights" (not "Reloading app motion_lights"). Instance 0's listeners and jobs remain active throughout. HTTP endpoint returns 202.

## Documentation Updates

- **docs site:** Update any page covering app configuration and multi-instance apps to mention per-instance restart behavior.
- **API docs:** The new per-instance HTTP endpoints will be auto-documented via OpenAPI schema generation (`scripts/export_schemas.py`).
- **Follow-up issue:** File a GitHub issue for CLI per-instance lifecycle commands (`hassette app reload <key> --instance <index>`, `hassette app stop <key> --instance <index>`, `hassette app start <key> --instance <index>`).

## Impact

### Changed Files

- **modify** `src/hassette/core/app_change_detector.py` — fix `ROOT_PATH`/`USER_CONFIG_PATH` constants or remove broken `include_paths`
- **modify** `src/hassette/core/app_factory.py` — extract `create_single_instance()` from `create_instances()` inner loop
- **modify** `src/hassette/core/app_lifecycle_service.py` — add `reload_instance()`, `stop_instance()`, `start_instance()`; modify `apply_changes()` for selective restart
- **modify** `src/hassette/core/app_handler.py` — add thin facade delegates for per-instance operations
- **modify** `src/hassette/core/telemetry/repository.py` — extend `_build_delete_query`/`_build_retire_query` with optional `instance_index`
- **modify** `src/hassette/core/command_executor.py` — extend `reconcile_registrations` with optional `instance_index`
- **modify** `src/hassette/web/routes/apps.py` — add per-instance HTTP endpoints
- **modify** `tests/unit/core/test_app_change_detector.py` — add tests for include_paths fix
- **create** new test files or extend existing ones for per-instance lifecycle and HTTP endpoints

### Behavioral Invariants

- Full app-key restart behavior for `reimport_apps` (file changes) must remain identical.
- Full app-key restart behavior when instance list length changes must match current behavior.
- Existing HTTP endpoints (`POST /apps/{app_key}/start|stop|reload`) must continue to operate on all instances.
- `reconcile_registrations` called without `instance_index` must behave identically to current behavior (backward-compatible optional parameter).
- The `HassetteAppStateEvent` lifecycle event contract must remain unchanged — per-instance operations emit the same event structure, just scoped to one instance.
- A config change to one instance of a currently-dormant `autostart=false` app must not start any instance; the app remains fully stopped until explicitly started. The existing `should_auto_reconcile` check must wrap the new per-instance branch of `apply_changes()`'s `reload_apps` loop.

### Blast Radius

- **ChangeSet consumers:** Unaffected — ChangeSet schema is unchanged (Option B).
- **Pre-release reconciliation:** Unaffected — operates at app-key level, which is preserved.
- **File watcher:** Unaffected — emits `changed_file_paths` at file level, which feeds into the existing `reimport_apps` path.
- **Dashboard/WebSocket status:** Unaffected — `HassetteAppStateEvent` already carries per-instance identity; the dashboard will show the individual instance cycling through states.
- **Telemetry queries:** Unaffected — queries already use `(app_key, instance_index)` composite keys.

## Open Questions

None — all questions discharged. The DeepDiff `include_paths` fix approach was deferred to implementation and is now owned by T01's Focus section.
