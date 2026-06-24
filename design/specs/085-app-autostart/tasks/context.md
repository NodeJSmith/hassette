# Context: Add `autostart` option to AppManifest

## Problem & Motivation
`AppManifest.enabled` conflates two independent axes: whether an app is *allowed to run at all* (a hard on/off switch) and whether it *starts automatically when Hassette starts*. There is no way to register an app that Hassette knows about and can start on demand but that stays idle at startup. Today the only way to keep an app idle at boot is `enabled = false` ("disabled"), but a disabled app started from the UI is transient (reverts on config reload) and reports as `DISABLED` rather than as a ready-but-idle app. This change adds an orthogonal `autostart` axis (following supervisord's naming) so an app can be enabled yet skipped at startup, startable on demand without a config edit.

## Visual Artifacts
None.

## Key Decisions
1. **Add `autostart: bool = Field(default=True)` to `AppManifest`**, orthogonal to `enabled`. Default `True` preserves current auto-start behavior (backward compatible).
2. **Status: reuse the existing `stopped` status, do NOT add a new `ManifestStatus` value.** An enabled, non-blocked, instance-less, failure-less app already derives to `"stopped"` in `get_full_snapshot()` (`app_registry.py:174-184`) with zero change. The new `autostart` field is exposed separately on the snapshot/response so the UI (and CLI) can mark "won't autostart" apps. Adding a status value would ripple through the literal, counts dict, mappers, frontend filters/tones/stats with no semantic gain.
3. **Reload semantics — one core invariant:** Hassette **auto-starts** an instance only when `autostart = True`. Automatic reconciliation may **stop** or **reload** instances that already exist, but it never creates the *first* instance of an `autostart = false` app. Only an explicit user/API/CLI action creates the first instance of an `autostart = false` app. This resolves every reload case (boot skip, new-app skip, reload-of-not-running skip, reload-of-running reflects config, running app survives unrelated reload).
4. **Gating lives in the automatic orchestration, never in `start_app`/`reload_app`.** `start_apps()` (boot) seeds from a new `autostart_manifests` property; `apply_changes()` (reload) gates via `should_autostart`/`should_auto_reconcile` helpers. `start_app`/`reload_app` are shared by explicit (REST/CLI) and automatic callers, so gating them would break on-demand start.
5. **`active_manifests` / `enabled_manifests` keep their current semantics and callers** (`resolve_only_app`, `reconcile_blocked_apps`) — autostart filtering is a *separate* property layered on top of `active_manifests`.
6. **CLI/web parity:** the `hassette app` list table already shows `status` and `enabled`; add an `Autostart` column so a non-autostart app is visible in the CLI too.

## Constraints & Anti-Patterns
- Do **not** change the contents or callers of `active_manifests` / `enabled_manifests`.
- Do **not** autostart-gate `start_app` / `reload_app` / `stop_app` — explicit user/API/CLI actions must remain unconditional.
- Do **not** add a new `ManifestStatus` literal value; reuse `stopped`.
- Do **not** add a UI toggle for `autostart` (non-goal — toggling stays a `hassette.toml` edit).
- Do **not** persist "manually started" state across full process restarts (non-goal — after a restart an `autostart=false` app is idle again until started).
- `AppManifestInfo` (dataclass): place `autostart: bool = True` **after the last non-default field (`status`)** — `enabled`/`auto_loaded`/`status` have no defaults, so a defaulted field inserted earlier raises `TypeError` at import. The default shields the two test-helper constructors (`test_utils/web_helpers.py:89`, `tests/unit/web/test_mappers.py:148`).
- `AppManifestResponse` (pydantic): `autostart: bool = True` (default keeps `web_helpers.py:117` and `test_model_types.py:94,106` direct constructions working; the mapper always supplies the real value).
- Do **not** edit `CHANGELOG.md` (release-please owns it). Do **not** edit `ws-types.ts`/`generated-types.ts` by hand — regenerate.

## Design Doc References
- `## Architecture` — the core invariant, per-layer changes (config, registry, schema, lifecycle, web/CLI, frontend), and the reload decision matrix.
- `## Architecture → Reload decision matrix` — the full table of (reload event × running? × autostart) → action.
- `## Edge Cases` — `@only_app`+autostart, unblock-during-reload, reload-of-running, explicit `/reload` on a stopped autostart=false app.
- `## Test Strategy` — existing tests to adapt, new coverage mapped to FR#N, none to remove.
- `## Impact → Changed Files` — the per-file change inventory (seeds Target Files).
- `## Impact → Behavioral Invariants` — what must not change.

## Convention Examples

### Manifest field with attribute docstring

**Source:** `src/hassette/config/classes.py:130`

```python
enabled: bool = Field(default=True)
"""Whether the app is enabled or not, will default to True if not set. Does not consider @only_app decorator."""
```

`AppManifest` uses `ConfigDict(use_attribute_docstrings=True)`, so the docstring under each field becomes its description. The new `autostart` field follows this exact pattern.

### Status derivation chain (do NOT add a branch for autostart)

**Source:** `src/hassette/core/app_registry.py:174-184`

```python
for app_key, manifest in self._manifests.items():
    if not manifest.enabled:
        status = "disabled"
    elif app_key in self._blocked_apps:
        status = "blocked"
    elif self._apps.get(app_key):
        status = "running"
    elif self._failed_apps.get(app_key):
        status = "failed"
    else:
        status = "stopped"
```

An `autostart = false` app that never started is enabled, not blocked, has no instances and no failures → already `"stopped"`. Surface the new field via `autostart=manifest.autostart` in the `AppManifestInfo(...)` construction, not via a new status branch.

### Reload-behavior integration test (mirror for the autostart cases)

**Source:** `tests/integration/test_apps.py:138-182`

```python
with (
    patch.object(self.app_handler.lifecycle.change_detector, "detect_changes") as mock_detect,
    patch.object(self.app_handler.lifecycle, "refresh_config") as mock_refresh_config,
):
    self.app_handler.registry.set_manifests(new_app_config)
    mock_refresh_config.return_value = (self.app_handler.registry.manifests, new_app_config)
    mock_detect.return_value = ChangeSet(
        orphans=frozenset(), new_apps=frozenset({"disabled_app"}),
        reimport_apps=frozenset(), reload_apps=frozenset(),
    )
    await self.app_handler.lifecycle.handle_change_event()
    await asyncio.wait_for(event.wait(), timeout=1)
    assert "disabled_app" in self.app_handler.apps
```

The "newly-added `autostart = false` app does not start" test (AC#5) is this exact shape with `new_apps={<autostart-off key>}` and the inverse assertion (`not in self.app_handler.apps`).

## Test command
- Unit + integration (local dev gate): `uv run pytest -n 4 tests/unit tests/integration` (per repo default; never `-n auto`). Single file: `uv run pytest tests/integration/test_apps.py`.
- Type check: `uv run pyright`. Lint: `ruff check` / `ruff format`.
- Frontend (worktree needs `cd frontend && npm install` first): `npm run build`, `npm test`.
- Schema/type regen: `uv run python scripts/export_schemas.py --types`.
- Heavy suites (`nox -s system`, `nox -s e2e`) run in CI — do not run locally.
