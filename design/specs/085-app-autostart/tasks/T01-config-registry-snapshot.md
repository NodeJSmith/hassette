---
task_id: "T01"
title: "Add autostart field to manifest, registry property, and snapshot"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#9", "FR#10", "FR#13", "AC#1", "AC#3"]
---

## Summary
Add the `autostart` axis at the data layer: a new `autostart: bool` field on `AppManifest` (default `True`), a new `autostart_manifests` property on `AppRegistry` for the startup set, and surfacing `autostart` in the manifest snapshot (`AppManifestInfo` + `get_full_snapshot`). This is the foundation the lifecycle (T02) and web/CLI (T03) layers build on. The `get_full_snapshot` status-derivation chain is **not** changed — an enabled, non-blocked, instance-less, failure-less app already derives to `stopped`.

## Target Files
- modify: `src/hassette/config/classes.py`
- modify: `src/hassette/core/app_registry.py`
- modify: `src/hassette/schemas/app_snapshots.py`
- modify: `tests/unit/core/test_app_registry.py`
- modify: `tests/unit/core/conftest.py`
- modify: `tests/unit/test_config_classes.py` (exists — reuse its `make_manifest(**overrides)` helper at line 14)
- read: `design/specs/085-app-autostart/design.md`
- read: `design/specs/085-app-autostart/tasks/context.md`

## Prompt
Implement the data-layer changes from the design doc's `## Architecture` sections 1, 2, and 3.

1. **`src/hassette/config/classes.py`** — In `AppManifest` (around line 130), add immediately after the `enabled` field, following the attribute-docstring convention:
   ```python
   autostart: bool = Field(default=True)
   """Whether the app starts automatically when Hassette starts. Orthogonal to
   `enabled`: an enabled app with autostart=false is registered and startable on
   demand, but is not started at startup or by a live config reload."""
   ```
   Also extend `__repr__` (line 158) to include `autostart` alongside `enabled`.

2. **`src/hassette/core/app_registry.py`** —
   - Add an `autostart_manifests` property (after `active_manifests`, ~line 250) that layers the autostart filter on top of `active_manifests` (which already applies the `enabled` + `only_app` filters):
     ```python
     @property
     def autostart_manifests(self) -> dict[str, "AppManifest"]:
         """Active manifests that should start automatically at boot."""
         return {k: v for k, v in self.active_manifests.items() if v.autostart}
     ```
   - In `get_full_snapshot()`, add `autostart=manifest.autostart` to the `AppManifestInfo(...)` construction (lines 207-222). **Do not** change the status-derivation chain at lines 174-184.

3. **`src/hassette/schemas/app_snapshots.py`** — Add `autostart: bool = True` to the `AppManifestInfo` dataclass. **Place it after the last non-default field (`status: str`)** — among the defaulted fields (e.g. immediately after `status`, before `block_reason`). It must keep the `= True` default.

4. **Tests:**
   - `tests/unit/core/test_app_registry.py` — add a test that `autostart_manifests` excludes `autostart=false` manifests while `active_manifests`/`enabled_manifests` still include them (see the existing `test_enabled_manifests` at line 301 for the pattern). Add a test that `get_full_snapshot()` sets `autostart` on each `AppManifestInfo` and that an enabled+autostart=false manifest still derives `status == "stopped"`.
   - `tests/unit/core/conftest.py` — the mock-registry fixture sets `enabled_manifests`/`active_manifests` at lines 143-144; add `registry.autostart_manifests = {}` alongside them so mocks expose the new property.
   - `tests/unit/test_config_classes.py` — this file already exists (tests `model_dump` privacy) with a `make_manifest(**overrides)` helper at line 14. **Modify, do not overwrite.** Add a test that `AppManifest` parses `autostart` (use `make_manifest(autostart=False)`), and that `make_manifest()` with no `autostart` override yields `autostart is True`.

Follow the convention examples in `context.md`. Do not change `active_manifests` or `enabled_manifests`.

## Focus
- `AppManifest` uses `ConfigDict(extra="allow", coerce_numbers_to_str=True, validate_assignment=True, use_attribute_docstrings=True)` — the attribute docstring becomes the field description, so write it well.
- **Dataclass field-ordering trap:** `AppManifestInfo` has `enabled`/`auto_loaded`/`status` with no defaults followed by defaulted fields. Inserting `autostart: bool = True` before `status` raises `TypeError: non-default argument follows default argument` at import. Place it after `status`.
- `AppManifestInfo` is constructed in three places: `app_registry.py:208` (this task adds `autostart=...` there), and two test helpers (`src/hassette/test_utils/web_helpers.py:89`, `tests/unit/web/test_mappers.py:148`) which rely on the `= True` default — leave those for T03; the default keeps them green.
- `get_full_snapshot()` keyword-constructs `AppManifestInfo`; if you add the field to the dataclass but forget `autostart=manifest.autostart` in the construction, every app silently reports `autostart=True` (the default). The construction line is essential.
- Run: `uv run pytest -n 4 tests/unit/core/test_app_registry.py tests/unit/test_config_classes.py` and `uv run pyright`.

## Verify
- [ ] FR#1: `AppManifest` has an `autostart: bool` field defaulting to `True`; constructing a manifest without `autostart` yields `autostart is True`.
- [ ] FR#2: An `enabled=true, autostart=false` manifest appears in `registry.manifests` and in `get_full_snapshot().manifests`.
- [ ] FR#9: `get_full_snapshot()` reports `status == "stopped"` (not `"disabled"`) for an enabled+autostart=false manifest with no running instances/failures.
- [ ] FR#10: `get_full_snapshot()` sets `autostart` on each `AppManifestInfo` matching the manifest's value.
- [ ] FR#13: A manifest dict with no `autostart` key parses to `autostart is True`.
- [ ] AC#1: A unit test confirms `autostart` round-trips through config parsing and absent-key defaults to `True`.
- [ ] AC#3: A unit test confirms an enabled+autostart=false manifest's snapshot entry has `status == "stopped"` and `autostart is False`.
