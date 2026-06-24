---
task_id: "T02"
title: "Gate automatic starts on autostart at boot and reload"
status: "done"
depends_on: ["T01"]
implements: ["FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "FR#12", "FR#13", "AC#2", "AC#4", "AC#5", "AC#6", "AC#7", "AC#8"]
---

## Summary
Wire the autostart invariant into app lifecycle. At boot, `start_apps()` seeds its default set from the new `autostart_manifests` property instead of `active_manifests`. On live config reload, `apply_changes()` gates the *starting* actions: a new or not-running `autostart=false` app is not auto-started, while an already-running app is always reconciled and an unrelated reload never tears it down. `start_app`/`reload_app`/`stop_app` stay untouched so explicit REST/CLI actions remain unconditional. Add the integration tests that pin all reload and boot cases.

## Target Files
- modify: `src/hassette/core/app_lifecycle_service.py`
- modify: `tests/integration/test_apps.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- read: `src/hassette/core/app_change_detector.py`
- read: `src/hassette/core/app_registry.py`
- read: `tests/unit/core/test_app_lifecycle_service_operations.py`
- read: `design/specs/085-app-autostart/design.md`
- read: `design/specs/085-app-autostart/tasks/context.md`

## Prompt
Implement the lifecycle changes from the design doc's `## Architecture` section 4 and the `Reload decision matrix`.

1. **`src/hassette/core/app_lifecycle_service.py`** —
   - `start_apps()` (line 341): change the default set to seed from `autostart_manifests`:
     ```python
     apps = apps if apps is not None else set(self.registry.autostart_manifests.keys())
     ```
   - Add two helpers (methods on the service, no leading underscore — repo style):
     ```python
     def should_autostart(self, app_key: str) -> bool:
         """A new/not-yet-running app auto-starts only if its manifest allows it."""
         manifest = self.registry.get_manifest(app_key)
         return bool(manifest and manifest.autostart)

     def should_auto_reconcile(self, app_key: str) -> bool:
         """Already-running apps are always reconciled; dormant apps only if autostart."""
         return app_key in self.registry.apps or self.should_autostart(app_key)
     ```
   - `apply_changes()` (lines 356-370): gate the starting actions. `orphans` → stop unconditionally. `reimport_apps` and `reload_apps` → only `reload_app(...)` when `should_auto_reconcile(app_key)`. `new_apps` → only `start_app(app_key)` when `should_autostart(app_key)`. Preserve the existing log lines / force_reload flags.
   - Do **not** modify `start_app`, `reload_app`, `stop_app`, or `refresh_config`.

2. **`tests/integration/test_apps.py`** — Add a fixture app to the integration test config with `enabled = true, autostart = false` (mirror how `disabled_app` is defined in the backing test config; see the `test_handle_changes_*` tests for how the fixture config is wired). Then add tests:
   - After bootstrap, the autostart-off app is **not** in `self.app_handler.apps` and has no running instances (AC#2).
   - `get_full_snapshot()` for the autostart-off app reports `status == "stopped"` and `autostart is False` (AC#2/AC#3 cross-check — assert here too).
   - `await self.app_handler.start_app(<key>)` starts the autostart-off app → it appears in `self.app_handler.apps` (AC#4).
   - A `handle_change_event` with `new_apps={<autostart-off key>}` leaves it unstarted — mirror `test_handle_changes_enables_app` (line 138) with the inverse assertion (`not in self.app_handler.apps`) (AC#5).
   - A reload changing an unrelated app leaves a manually-started autostart-off app running (AC#6).
   - A reload with `reload_apps={<autostart-off key>}` (config changed) for an app that is **not** currently running leaves it unstarted — `not in self.app_handler.apps` (FR#6). Mirror the reload-test convention with a `reload_apps` (not `new_apps`) ChangeSet.
   - A reload with `reload_apps={<autostart-off key>}` for an app that **is** currently running (manually started first) reloads it and leaves it running — still `in self.app_handler.apps` after the event (FR#8). Use `test_config_changes_are_reflected_after_reload` (line 184) as the shape.
   - Existing enabled+autostart apps still start at boot; `disabled_app` still absent + `disabled` status (AC#7/AC#8).

3. **`tests/unit/core/test_app_lifecycle_service.py`** — the `start_apps` tests mock `mock_registry.active_manifests` (lines 374, 406). Since `start_apps` now reads `autostart_manifests`, update those mocks to set `autostart_manifests` (keep `active_manifests` if other assertions in the same test rely on it).

Follow the convention example for reload tests in `context.md`.

## Focus
- **The core invariant (context.md decision 3):** Hassette auto-starts an instance only when `autostart=True`; reconciliation may stop/reload existing instances but never creates the first instance of an autostart=false app. Walk each row of the design's `Reload decision matrix` and confirm your gates produce it.
- `apply_changes` ordering matters: `should_auto_reconcile` checks `app_key in self.registry.apps` — evaluate it **before** calling `reload_app` (which calls `stop_app` and removes the app from `registry.apps`). The guard is in the loop before the call, so this is naturally correct; do not move the check inside `reload_app`.
- The unblock path in `handle_change_event` (lines 392-401) merges unblocked apps into `changes.new_apps`, so an unblocked autostart=false app is correctly gated by `should_autostart` — no extra handling needed.
- `start_app` does **not** check `enabled`/`autostart` (it only checks the manifest exists), so explicit REST/CLI start of an autostart=false app already works — verify you didn't add a gate there.
- `tests/unit/core/test_app_lifecycle_service_operations.py` mocks `active_manifests` at lines 212/227/245 for non-`start_apps` paths (resolve_only_app / apply_changes). Confirm those tests still pass unchanged after your edit; only `start_apps`-driven tests need the `autostart_manifests` mock.
- `tests/unit/core/conftest.py` gains `autostart_manifests = {}` in T01 — depend on that.
- Run: `uv run pytest -n 4 tests/integration/test_apps.py tests/unit/core/test_app_lifecycle_service.py tests/unit/core/test_app_lifecycle_service_operations.py` and `uv run pyright`.

## Verify
- [ ] FR#3: After `bootstrap_apps()`, an enabled+autostart=false app has zero running instances and is absent from `registry.apps`.
- [ ] FR#4: `start_app(app_key)` for that app produces a running instance (no config edit).
- [ ] FR#5: A reload `ChangeSet` whose `new_apps` contains an autostart=false app leaves it unstarted.
- [ ] FR#6: A reload does not start an autostart=false app that is not currently running even when its config/file changed.
- [ ] FR#7: A reload that changes an unrelated app leaves an already-running autostart=false app running.
- [ ] FR#8: A reload of a running autostart=false app whose config changed reloads it and leaves it running.
- [ ] FR#12: `enabled=false` apps are still skipped at boot and report `disabled` status (unchanged).
- [ ] FR#13: An app with no `autostart` key still auto-starts at boot (existing fixture apps continue to start).
- [ ] AC#2: Integration test confirms the autostart-off app is absent from `registry.apps` after bootstrap.
- [ ] AC#4: Integration test confirms `start_app` starts the autostart-off app.
- [ ] AC#5: Integration test confirms `new_apps={autostart-off key}` reload leaves it unstarted.
- [ ] AC#6: Integration test confirms an unrelated reload leaves a manually-started autostart-off app running.
- [ ] AC#7: Integration test confirms autostart-absent apps auto-start at boot.
- [ ] AC#8: Integration test confirms `disabled_app` stays absent + `disabled` status.
