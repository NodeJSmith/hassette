# Context: Per-Instance App Restart

## Problem & Motivation
When a multi-instance app has a config change to just one instance, all instances restart — the unchanged ones lose their in-flight automations, scheduler state, and event subscriptions unnecessarily. Additionally, the change detection filter (`include_paths`) is broken: `ROOT_PATH = "root"` matches every DeepDiff path via substring matching, so any manifest attribute change triggers a reload, not just `app_config` changes. This feature adds per-instance lifecycle operations so only affected instances restart on config changes, with fallback to full app-key restart when the instance list length changes.

## Visual Artifacts
None.

## Key Decisions
1. **Option B — Config-equality comparison in the lifecycle service.** ChangeSet stays at app-key granularity; per-instance diffing happens downstream in `apply_changes()` using plain dict equality. This avoids changing the ChangeSet schema and its 4+ consumers.
2. **Batch lock acquisition for selective restart.** When `apply_changes()` reloads multiple changed indices for one app_key, it acquires the per-app-key lock once for the entire batch (via `_reload_instance_unlocked()`), not per-call. This prevents registry races with concurrent HTTP operations.
3. **Positional instance identity.** Instance index comes from `enumerate()` on the TOML config list. Content-based identity (keying by `instance_name`) is a non-goal for this scope.
4. **`apply_changes()` explicit parameter approach.** Signature changes to `apply_changes(changes, original_config, current_config)` — the field-snapshot alternative is worse for testability. This touches 11+ call sites (3 production, 8+ test).
5. **Class-load failure fix.** `_reload_instance_unlocked()` calls `factory.load_class()` itself and records failure at the actual target index, not hardcoded index 0.

## Constraints & Anti-Patterns
- Do NOT change the ChangeSet model shape — per-instance logic lives in the lifecycle service.
- Do NOT introduce per-instance locks — all per-instance operations use the existing per-app-key lock (`_app_key_locks`).
- Do NOT introduce name-based instance identity resolution.
- Do NOT implement CLI per-instance commands (follow-up issue).
- Do NOT implement a frontend per-instance restart button (separate feature).
- `should_auto_reconcile` check must wrap the new per-instance branch — a config edit to a dormant `autostart=false` app must not start any instance.
- `reload_instance`/`stop_instance` must scope failed-entry info capture to the target index only — do NOT reuse the app-key-wide `get_failed_instance_infos(app_key)`.
- All per-instance methods must re-validate `index` after acquiring the lock, mirroring `start_app()`'s post-lock re-fetch pattern.

## Design Doc References
- `## Architecture → Component changes` — detailed changes per file
- `## Architecture → Data flow for selective restart` — pseudocode for the selective path
- `## Edge Cases` — fallback rules, pure reorder limitation, failed instance handling, bootstrap behavior
- `## Behavioral Invariants` — 6 must-preserve behaviors including autostart=false dormancy
- `## Test Strategy` — required test types, existing tests to adapt, new coverage
- `## Smoke Test` — HTTP API + log verification scenario

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
