# Design: Add `autostart` option to register an app without auto-starting it

**Date:** 2026-06-24
**Status:** archived
**Scope-mode:** hold

## Problem

`AppManifest.enabled` currently conflates two independent axes:

1. **Allowed to run at all** — a hard on/off switch.
2. **Starts automatically when Hassette starts** — a startup-policy switch.

There is no way to register an app that Hassette knows about and can start on demand, but that does **not** start itself at startup. Today the only way to keep an app idle at boot is `enabled = false` ("disabled"), but that reads as "turned off": a disabled app started from the UI is transient (reverts on config reload) and reports as `DISABLED` rather than as a ready-but-idle app.

Process supervisors solve this by separating the two axes — systemd (`enable`/`disable` vs `start`/`stop`), supervisord (`autostart` independent of program definition). Hassette should do the same: an app can be `enabled` (allowed, fully registered) yet skipped at startup, startable on demand without a config edit.

## Goals

- Add `autostart: bool` to `AppManifest`, orthogonal to `enabled`, defaulting to `True` (backward compatible).
- `enabled = true` + `autostart = false` → the app is registered, appears in the apps list, but is **not** started by any *automatic* path (boot or live config reload).
- Such an app is startable on demand via `POST /apps/{app_key}/start` (and any CLI/REST caller), with no config edit required, and the start persists across unrelated config reloads.
- The app reports a distinct-from-`disabled` status, and the UI can visually mark it as "won't autostart."
- `enabled = false` behavior is unchanged.

## Non-Goals

- No new `autostart` toggle control in the UI (the field is read-only/observable this iteration; toggling still happens by editing `hassette.toml`).
- No persistence of "manually started" state across full Hassette process restarts — after a restart, an `autostart = false` app is idle again until started. (This matches supervisord and the issue's intent.)
- No new dedicated lifecycle status value (e.g. `idle`/`not_started`); we reuse the existing `stopped` status. See Alternatives.

## User Scenarios

### App author: configures an on-demand app

- **Goal:** register a heavy/occasional app that should only run when explicitly started.
- **Context:** editing `hassette.toml`.

#### Register but don't autostart

1. **Add `autostart = false` to the app's manifest block** alongside `enabled = true`.
   - Sees: the app appears in the apps dashboard after Hassette starts.
   - Decides: leave it idle, or start it now.
   - Then: at boot the app is **not** started; it shows a non-`disabled`, ready state.

2. **Start the app on demand** from the dashboard (or `POST /apps/{key}/start`).
   - Sees: the app transitions to `RUNNING` and processes events.
   - Then: a later unrelated config reload (a different app changes) leaves this app running — it is not torn down.

### Operator: reloads config while an on-demand app runs

- **Goal:** edit another app's config without disturbing a manually-started on-demand app.
- **Context:** live `hassette.toml` edit picked up by the file watcher.

#### Reload does not auto-start or tear down dormant/running on-demand apps

1. **Add a new `autostart = false` app to config and save.**
   - Then: the file watcher fires; the new app is registered but **not** started (a reload-add is an automatic start, which `autostart = false` forbids).

2. **Edit an unrelated app while an on-demand app is already running.**
   - Then: the running on-demand app is untouched and keeps running.

## Functional Requirements

- **FR#1** `AppManifest` exposes an `autostart: bool` field defaulting to `True`.
- **FR#2** When `enabled = true` and `autostart = false`, the app is registered in the registry and present in `get_full_snapshot()` / the apps list.
- **FR#3** During `bootstrap_apps()` → `start_apps()`, apps with `autostart = false` are not started.
- **FR#4** `start_app(app_key)` (the on-demand path used by `POST /apps/{key}/start` and CLI) starts an `autostart = false` app regardless of the autostart flag.
- **FR#5** A live config reload does not start a newly-added `autostart = false` app.
- **FR#6** A live config reload does not start an `autostart = false` app that is not currently running, even when that app's config or source file changed.
- **FR#7** A live config reload does not tear down an `autostart = false` app that is currently running, when that app's manifest did not change.
- **FR#8** A live config reload of an `autostart = false` app that **is** running and whose config/file changed reloads it (reflects the new config) and leaves it running.
- **FR#9** An `enabled = true` + `autostart = false` app that has never started reports `status = "stopped"` (not `"disabled"`) in `get_full_snapshot()`.
- **FR#10** The manifest snapshot and the `/apps` response expose the `autostart` value per app.
- **FR#11** The apps UI visually marks apps where `autostart = false`.
- **FR#12** `enabled = false` (disabled) behavior is unchanged: excluded from startup, `disabled` status, transient API start as today.
- **FR#13** A manifest with no `autostart` key behaves exactly as before (auto-starts at boot).

## Edge Cases

- **`@only_app` + `autostart = false`** on the same app: at boot nothing autostarts (the only-app filter narrows to that app, then the autostart filter removes it). The app remains startable on demand. Consistent with "autostart governs automatic starts."
- **Unblock during reload** (an app previously blocked by `@only_app` becomes eligible): unblocked apps are routed through the `new_apps` start path, so an `autostart = false` unblocked app is **not** auto-started — it falls under FR#5's gate.
- **Reload of a running on-demand app whose config changed** (FR#8): handled by the "already-running apps are always reconciled" rule.
- **Disabled apps are absent from change detection** (`refresh_config` filters by `enabled`), so the autostart gate never needs to consider them in the reload path.
- **Explicit `/reload` on a stopped `autostart = false` app**: `reload_app` is an explicit user action and is not autostart-gated, so it will start the app. This is the intended "explicit actions always work" behavior; documented as such.

## Acceptance Criteria

- **AC#1** Adding `autostart: bool = Field(default=True)` to `AppManifest` round-trips through TOML config; absent key → `True`. (FR#1, FR#13)
- **AC#2** After `bootstrap_apps()`, an `enabled = true` + `autostart = false` app has zero running instances and is absent from `registry.apps`. (FR#3)
- **AC#3** After `bootstrap_apps()`, that same app's `get_full_snapshot()` entry has `status == "stopped"` and `autostart is False`. (FR#2, FR#9, FR#10)
- **AC#4** Calling `start_app(app_key)` for that app produces a running instance. (FR#4)
- **AC#5** A reload `ChangeSet` whose `new_apps` contains an `autostart = false` app leaves it unstarted (`app_key not in registry.apps`). (FR#5)
- **AC#6** A reload that changes an unrelated app leaves an already-running `autostart = false` app running. (FR#7)
- **AC#7** A manifest with no `autostart` key auto-starts at boot (existing apps in the fixture continue to start). (FR#13)
- **AC#8** `enabled = false` apps still report `status == "disabled"` and are skipped at boot. (FR#12)
- **AC#9** The `/apps` REST response includes `autostart` for each manifest, and the UI renders a "no autostart" marker when it is `false`. (FR#10, FR#11)

## Key Constraints

- **Do not change the semantics of `active_manifests` or `enabled_manifests`.** They are consumed by `@only_app` resolution (`resolve_only_app`) and block reconciliation (`reconcile_blocked_apps`), which are independent of autostart. The autostart filter must be a *separate* property used only by the startup path.
- **Do not autostart-gate `start_app` / `reload_app` themselves.** These are shared by explicit (API/CLI) and automatic (file-watcher) callers. Gating must live in the *automatic orchestration* (`start_apps` default set, `apply_changes`) so explicit user actions remain unconditional.
- **Do not introduce a new `ManifestStatus` value.** Reuse `stopped` (decision below) — adding a status value ripples through the literal, counts dict, mappers, frontend filter options, tones, and stats strip with no semantic gain.

## Dependencies and Assumptions

- No external systems. Pure framework-internal change plus its web/UI surface.
- Assumes the existing file-watcher → `handle_change_event` → `detect_changes` → `apply_changes` reload pipeline is the only automatic start path besides `bootstrap_apps`. (Verified: `start_apps` is called only from `bootstrap_apps`; on-demand starts go through `start_app`.)

## Architecture

### Core invariant

> Hassette **auto-starts** an app instance only when `autostart = True`. Automatic reconciliation may **stop** or **reload** instances that already exist, but it never creates the *first* instance of an `autostart = false` app. Only an explicit user/API/CLI action creates the first instance of an `autostart = false` app.

This single rule resolves every reload case (FR#3, FR#5–FR#8).

### 1. Config — `src/hassette/config/classes.py`

Add the field immediately after `enabled` (line 130), using the existing attribute-docstring convention so it becomes the field description:

```python
autostart: bool = Field(default=True)
"""Whether the app starts automatically when Hassette starts. Orthogonal to
`enabled`: an enabled app with autostart=false is registered and startable on
demand, but is not started at startup or by a live config reload."""
```

Extend `__repr__` (line 158) to include `autostart` alongside `enabled` — it directly governs startup behavior, so surfacing it makes `autostart=false` misconfigurations visible in logs.

### 2. Registry — `src/hassette/core/app_registry.py`

- Add a property that is the startup set, layering the autostart filter on top of `active_manifests` (which already applies the `enabled` + `only_app` filters):

```python
@property
def autostart_manifests(self) -> dict[str, "AppManifest"]:
    """Active manifests that should start automatically at boot."""
    return {k: v for k, v in self.active_manifests.items() if v.autostart}
```

- In `get_full_snapshot()`, the status-derivation chain (lines 174–184) is **unchanged** — an enabled, non-blocked, instance-less, failure-less app already falls through to `"stopped"`. Add `autostart=manifest.autostart` to the `AppManifestInfo(...)` construction (lines 207–222).

### 3. Snapshot schema — `src/hassette/schemas/app_snapshots.py`

Add `autostart: bool = True` to the `AppManifestInfo` dataclass. **It must keep the `= True` default and be placed after the last non-default field (`status: str`)** — `enabled`, `auto_loaded`, and `status` have no defaults, so a defaulted field inserted "after `enabled`" would raise `TypeError: non-default argument follows default argument` at import. Place it among the defaulted fields (e.g. immediately after `status`, before `block_reason`).

The `= True` default is load-bearing: `AppManifestInfo` is constructed in **three** places — `app_registry.py:208` (the real one, which passes `autostart=manifest.autostart` explicitly, see Section 2) and two test helpers, `src/hassette/test_utils/web_helpers.py:89` and `tests/unit/web/test_mappers.py:148`. The default lets those two helpers keep working without edits.

### 4. Lifecycle — `src/hassette/core/app_lifecycle_service.py`

- `start_apps()` default set (line 341): seed from `autostart_manifests` instead of `active_manifests`:

```python
apps = apps if apps is not None else set(self.registry.autostart_manifests.keys())
```

- `apply_changes()` (line 348): gate the *starting* actions on the invariant. `new_apps` only start when `autostart`; `reimport`/`reload` proceed when the app is already running **or** `autostart`:

```python
for app_key in changes.orphans:
    await self.stop_app(app_key)

for app_key in changes.reimport_apps:
    if self.should_auto_reconcile(app_key):
        await self.reload_app(app_key, force_reload=True)

for app_key in changes.reload_apps:
    if self.should_auto_reconcile(app_key):
        await self.reload_app(app_key)

for app_key in changes.new_apps:
    if self.should_autostart(app_key):
        await self.start_app(app_key)
```

With two small module-level/instance helpers:

```python
def should_autostart(self, app_key: str) -> bool:
    """A new/not-yet-running app auto-starts only if its manifest allows it."""
    manifest = self.registry.get_manifest(app_key)
    return bool(manifest and manifest.autostart)

def should_auto_reconcile(self, app_key: str) -> bool:
    """Already-running apps are always reconciled; dormant apps only if autostart."""
    return app_key in self.registry.apps or self.should_autostart(app_key)
```

`start_app` and `reload_app` are left untouched, so the REST routes (`POST /apps/{key}/start`, `/reload`) and CLI keep working unconditionally (FR#4, explicit-action edge case).

### 5. Web models + mappers + CLI

- `src/hassette/web/models.py`: add `autostart: bool = True` to `AppManifestResponse` (after `enabled`, ~line 127). The `= True` default keeps the existing direct constructions working — `src/hassette/test_utils/web_helpers.py:117` and `tests/unit/test_model_types.py:94,106` build `AppManifestResponse` without this field. The mapper always supplies the real value. `ManifestStatus` literal is **unchanged**.
- `src/hassette/web/mappers.py`: map `autostart=m.autostart` in the manifest-response construction (~line 91).
- `src/hassette/cli/commands/app.py`: the `hassette app` list table (`APP_LIST_COLUMNS`, lines 13-19) already renders `status` and `enabled` columns. Add an `Autostart` column for CLI/web parity — an enabled app that won't autostart should be visible in the CLI too, not just the web UI.

### 6. Frontend — `frontend/src/`

- Regenerate types: `uv run python scripts/export_schemas.py --types` (regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`); `autostart` appears on the manifest response type.
- `frontend/src/utils/app-data.ts`: **required** — `AppRow` (the interface at line 5) and `mergeManifestsAndGrid` (line 33) are manually enumerated and do **not** pass through arbitrary manifest fields (confirmed: `enabled`/`auto_loaded` are listed explicitly, line 12-13 / 44-45). Add `autostart: boolean` to the `AppRow` interface and `autostart: m.autostart` to the `mergeManifestsAndGrid` mapping. Without this the marker has no data to render.
- `frontend/src/pages/apps.tsx` + `apps-table-row.tsx`: when a row's `autostart === false`, render a small marker (e.g. a "no autostart" chip/badge near the status). `FILTER_OPTIONS` / `FILTER_TONES` / stats strip are **unchanged** (no new status). The marker also surfaces in the app detail view header if it shows status.

### Reload decision matrix (for reference)

| Reload event | App running? | autostart | Action |
|---|---|---|---|
| `new_apps` | no (new) | true | start |
| `new_apps` | no (new) | false | **skip** (FR#5) |
| `reload`/`reimport` | yes | any | reload (FR#8) |
| `reload`/`reimport` | no | true | reload→start (pre-existing: `stop_app` logs a benign "not found" warning before `start_app` creates it) |
| `reload`/`reimport` | no | false | **skip** (FR#6) |
| no manifest change | yes | false | untouched (FR#7) |
| `orphans` | any | any | stop |

## Replacement Targets

No code path is removed or superseded. The change is mostly additive (a new field, a new registry property, a new response/schema field), but **`apply_changes()`'s loop bodies are modified in place**, not just extended: the unconditional `reload_app`/`start_app` calls become gated calls. For `autostart=true` apps the gates are transparent (`should_auto_reconcile`/`should_autostart` return `True`), so behavior is preserved; for `autostart=false` apps the gates suppress the automatic start. A reviewer auditing the blast radius should scrutinize the `reimport_apps`/`reload_apps`/`new_apps` loops in `apply_changes`, not treat them as untouched. `active_manifests` and `enabled_manifests` retain their current semantics and callers.

## Migration

No data migration. `AppManifest` is parsed from TOML at startup, not persisted. Existing configs without `autostart` default to `True` (FR#13), preserving current auto-start behavior. The `AppManifestInfo` dataclass gets a defaulted field, so any in-flight constructor without `autostart` is safe.

## Convention Examples

### Manifest field with attribute docstring

**Source:** `src/hassette/config/classes.py:130`

```python
enabled: bool = Field(default=True)
"""Whether the app is enabled or not, will default to True if not set. Does not consider @only_app decorator."""
```

`AppManifest` uses `ConfigDict(use_attribute_docstrings=True)`, so the docstring under each field becomes its description. New `autostart` field follows this exact pattern.

### Status derivation chain (do not add a branch for autostart)

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

An `autostart = false` app that never started is enabled, not blocked, has no instances and no failures → already `"stopped"`. The new field is surfaced separately via `autostart=manifest.autostart`, not via a new status branch.

### Reload-behavior integration test (mirror for autostart cases)

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

The "newly-added `autostart = false` app does not start" test (AC#5) is this exact shape with `new_apps={"autostart_off_app"}` and the inverse assertion (`not in self.app_handler.apps`).

## Alternatives Considered

- **Dedicated `idle`/`not_started` status** instead of reusing `stopped`. Rejected: more semantically explicit, but it adds a value to the `ManifestStatus` literal, the `counts` dict, the mappers, the frontend `FILTER_OPTIONS`/`FILTER_TONES`/stats strip, and the status-tone map — broad blast radius for a distinction the AC already gets from `disabled` vs `stopped`. The `autostart` field on the response gives the UI everything it needs to mark these apps without enlarging the status set. (Chosen: reuse `stopped` + expose `autostart`.)
- **Strict "startup-only" reload semantics** — `autostart` affects only `bootstrap_apps`, so a newly-added `autostart = false` app via live config edit auto-starts. Rejected: a reload-add is itself an automatic start, so this makes `autostart = false` fail to mean "won't start unless I ask." (Chosen: `autostart` governs all automatic starts; explicit actions always work.)
- **Gating inside `start_app`/`reload_app`.** Rejected: those methods are shared by explicit (API/CLI) and automatic (watcher) callers; gating there would break on-demand start. Gating lives in the automatic orchestration instead.
- **Tri-state `startup` mode** (e.g. `auto`/`manual`/`disabled`). Rejected: re-merges the two axes this change is separating, and is non-standard versus supervisord's `autostart`.

## Test Strategy

### Existing Tests to Adapt

No existing tests should break — the change is additive and existing fixtures omit `autostart` (default `True`, current behavior). The reload tests in `tests/integration/test_apps.py` (`test_handle_changes_enables_app`, `test_config_changes_are_reflected_after_reload`) are the convention to mirror, not to modify. If a snapshot/manifest assertion in `tests/unit/core/test_app_registry.py` constructs `AppManifestInfo` positionally, it may need the new field — verify and adjust.

### New Test Coverage

Integration — `tests/integration/test_apps.py` (needs an `enabled = true, autostart = false` app in the test config fixture):
- **AC#2/AC#3** — after bootstrap, the autostart-off app is not in `registry.apps`, has no running instances, and its `get_full_snapshot()` entry is `status == "stopped"`, `autostart is False`. (FR#2, FR#3, FR#9, FR#10)
- **AC#4** — `start_app(app_key)` starts the autostart-off app. (FR#4)
- **AC#5** — `handle_change_event` with `new_apps={autostart_off_key}` leaves it unstarted. (FR#5) — mirror of `test_handle_changes_enables_app`.
- **AC#6** — reload changing an unrelated app leaves a manually-started autostart-off app running. (FR#7)
- **AC#7/AC#8** — existing enabled+autostart apps still start; disabled apps still `disabled` and skipped. (FR#12, FR#13)

Unit — `tests/unit/core/test_app_registry.py`:
- `autostart_manifests` excludes `autostart = false` while `active_manifests`/`enabled_manifests` still include them.
- `get_full_snapshot()` sets `autostart` on each `AppManifestInfo` and keeps `status == "stopped"` for an autostart-off app.

Config — `tests/unit/test_config_classes.py` (there is no `tests/unit/config/` dir): `AppManifest` parses `autostart` from TOML; absent key defaults to `True`.

### Tests to Remove

No tests to remove.

## Documentation Updates

- **`docs/pages/core-concepts/apps/configuration.md`** (~line 15): document `autostart` alongside `enabled`, naming the orthogonality — `enabled` is the hard on/off, `autostart` controls start-at-startup. Add to the registration-fields callout (~line 46).
- **`docs/pages/web-ui/manage-apps.md`** "Understand App States" table (lines 60–68): clarify the `STOPPED` row to note it also covers an enabled app with `autostart = false` that has not been started, and describe the "no autostart" marker. The `DISABLED` row stays as-is.
- **Config reference / API docstrings**: the new `AppManifest.autostart` attribute docstring is the reference source (mkdocstrings).
- **PR**: requires a Screenshots section (or `no-visual-change` label is not applicable — this *does* change rendered output) showing the "no autostart" marker, per `design-completeness.md` and `tools/frontend/check_pr_screenshots.py`.
- **CHANGELOG**: not edited manually (release-please). Commit/PR title is `feat:` so it lands in the changelog.

## Impact

### Changed Files

- `src/hassette/config/classes.py` — modify: add `autostart` field to `AppManifest` (after line 130); optional `__repr__` update.
- `src/hassette/core/app_registry.py` — modify: add `autostart_manifests` property; add `autostart=manifest.autostart` to `AppManifestInfo` construction in `get_full_snapshot()`.
- `src/hassette/schemas/app_snapshots.py` — modify: add `autostart: bool = True` to `AppManifestInfo`, placed after the last non-default field (`status`).
- `src/hassette/core/app_lifecycle_service.py` — modify: `start_apps()` default set → `autostart_manifests`; `apply_changes()` gates via `should_autostart` / `should_auto_reconcile` helpers.
- `src/hassette/web/models.py` — modify: add `autostart: bool` to `AppManifestResponse`.
- `src/hassette/web/mappers.py` — modify: map `autostart=m.autostart`.
- `src/hassette/cli/commands/app.py` — modify: add `Autostart` column to `APP_LIST_COLUMNS`.
- `frontend/src/api/generated-types.ts` — regenerate (do not hand-edit).
- `openapi.json`, `ws-schema.json`, `frontend/src/api/ws-types.ts` — regenerate via `scripts/export_schemas.py --types`.
- `frontend/src/pages/apps.tsx`, `frontend/src/pages/apps-table-row.tsx`, `frontend/src/utils/app-data.ts` — modify: thread `autostart` and render the marker.
- `docs/pages/core-concepts/apps/configuration.md` — modify: document `autostart`.
- `docs/pages/web-ui/manage-apps.md` — modify: clarify `STOPPED`, describe marker.
- `tests/integration/test_apps.py` — modify: add autostart-off fixture app + AC#2–AC#8 tests.
- `tests/unit/core/test_app_registry.py` — modify: `autostart_manifests` + snapshot tests.
- `tests/unit/core/test_app_lifecycle_service.py` — modify: `start_apps` tests mock `active_manifests` (lines 374, 406); switch to `autostart_manifests` since `start_apps` now reads that property.
- `tests/unit/core/conftest.py` — modify: the mock-registry fixture sets `enabled_manifests`/`active_manifests` (lines 143-144); add `autostart_manifests = {}`.
- `tests/unit/test_model_types.py` — modify: `TestManifestStatus` builds `AppManifestResponse` (lines 94, 106); safe via the `= True` default, but add an assertion that `autostart` round-trips.
- `tests/unit/web/test_mappers.py` — modify: assert the mapper carries `autostart` onto `AppManifestResponse`.
- `tests/unit/test_config_classes.py` — modify: `AppManifest` parses `autostart`; absent key defaults to `True`.
- Test config fixture (the `hassette.toml` / manifest fixtures backing `tests/integration/test_apps.py`) — modify: add one `enabled = true, autostart = false` app.
- `src/hassette/test_utils/web_helpers.py` (line 89) and `tests/unit/web/test_mappers.py` (line 148) — note: additional `AppManifestInfo` construction sites. Covered by the `= True` default, so no change is strictly required; optionally set `autostart` in `web_helpers.py` for fixture realism. If the new `AppManifestResponse.autostart` is required (no default), `test_mappers.py`'s response assertions must account for it.

### Behavioral Invariants

- `active_manifests` and `enabled_manifests` keep their current contents and callers (`resolve_only_app`, `reconcile_blocked_apps`) — unchanged.
- `start_app` / `reload_app` / `stop_app` signatures and behavior unchanged; on-demand REST/CLI start of any registered app (including disabled, transiently) works as today.
- `ManifestStatus` literal value set unchanged; existing `stopped`/`disabled` consumers unaffected.
- Apps with no `autostart` key auto-start exactly as before.

### Blast Radius

- Backend: app lifecycle/startup, registry snapshot, web `/apps` response. Confined to the app subsystem.
- Frontend: apps dashboard row rendering + the regenerated type surface (`generated-types.ts`). No change to status filtering.
- Consumers of the `/apps` REST endpoint gain an additive `autostart` field (non-breaking).

<!-- Gap check 2026-06-24: 7 unlisted dependencies included — CLI app-list table (cli/commands/app.py:13-19) → T03 Autostart column; start_apps mocks (test_app_lifecycle_service.py:374,406) → T02; mock-registry fixture (conftest.py:143-144) → T01; AppManifestResponse constructions (test_model_types.py:94,106) → T03; AppManifestInfo mapper test (test_mappers.py:148) → T03; web_helpers.py builders (89,117) → covered by =True defaults (T01/T03); frontend structure tests (apps-table-row.test.tsx, app-detail.test.tsx) → T04. Verified non-gap: client.py:198 (instance-resolution only, no columns); routes/apps.py model_copy preserves fields; test_app_lifecycle_service_operations.py active_manifests mocks (212-245) back non-start_apps paths (T02 Focus confirms unchanged). -->

## Open Questions

None — both design decisions (status reuse, reload semantics) are settled above.
