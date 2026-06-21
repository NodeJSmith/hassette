---
task_id: "T03"
title: "Make AppChangeDetector stateless and remove dead Bus child"
status: "done"
depends_on: []
implements: ["FR#9", "FR#10", "FR#13", "AC#6", "AC#8", "AC#9"]
---

## Summary
Two small app-lifecycle cleanups (both audit N2, both touching `app_lifecycle_service.py`, so they
ship together). First, the `only_app` filter is stored in two mutable places — `AppRegistry._only_app`
and `AppChangeDetector.only_app_filter` — kept equal by a sync method with no test pin. Make
`AppChangeDetector` stateless by passing `only_app` as a parameter to `detect_changes`; the registry
becomes the single owner, and a test pins that the registry value and the value passed to the next
`detect_changes` agree. Second, `AppLifecycleService` constructs a `Bus` child Resource it never uses
(the real file-watcher subscription is on `AppHandler.bus`); delete it.

## Target Files
- modify: `src/hassette/core/app_change_detector.py` — remove `only_app_filter` field (`:47-48`) and `set_only_app_filter` (`:108-110`); add `only_app` parameter to `detect_changes` (`:51`); update the filter read (`:78-79`)
- modify: `src/hassette/core/app_lifecycle_service.py` — drop the detector-sync line in `update_only_app_filter` (`:489`); pass `only_app=self.registry.only_app` at the `detect_changes` call (`:395`); remove the `Bus` child: annotation (`:69`), `self.bus = self.add_child(Bus)` (`:86`), docstring mention (`:54`), and the now-unused `Bus` import if nothing else uses it
- read: `src/hassette/core/app_registry.py` — `_only_app` / `set_only_app` / `only_app` (sole owner, `:28,101-103,237-238`)
- read: `src/hassette/core/app_handler.py` — file-watcher subscription on `AppHandler.bus` (`:100-104`), confirms item-6 deletion is safe
- modify: `tests/unit/core/test_app_change_detector.py` — migrate `set_only_app_filter`/`only_app_filter`-field tests (`:199-236`, `:251-255`) to the parameter form; remove tests of the deleted API
- read: `design/specs/081-design-audit-followups-1096/design.md` — Architecture items 4 & 6
- read: `design/specs/081-design-audit-followups-1096/tasks/context.md`

## Prompt
Implement items 4 and 6 from the design (`## Architecture` → "4. Stateless `AppChangeDetector`" and
"6. Delete unused `Bus` child").

**Item 4 — stateless detector.**
1. In `src/hassette/core/app_change_detector.py`: remove the `only_app_filter` instance field
   (`__init__`, `:47-48`) and the `set_only_app_filter` method (`:108-110`). Add an `only_app: str |
   None = None` parameter to `detect_changes` (`:51`). Change the filter read (`:78-79`) from
   `self.only_app_filter` to the new `only_app` parameter.
2. In `src/hassette/core/app_lifecycle_service.py`: `update_only_app_filter` (`:486-489`) now only sets
   the registry — delete the `self.change_detector.set_only_app_filter(app_key)` line (`:489`). At the
   `detect_changes` call site (`:395`), pass `only_app=self.registry.only_app`.
3. `AppRegistry` is unchanged — it remains the single owner of `_only_app` via
   `set_only_app`/`only_app`.
4. Add a test pinning the invariant: after `resolve_only_app(...)` runs, `registry.only_app` equals the
   value that the next `detect_changes` call receives as `only_app`. Also migrate the existing
   `test_app_change_detector.py` tests that used `set_only_app_filter`/the constructor field
   (`:199-236`, `:251-255`) to pass `only_app=...` into `detect_changes`; delete
   `test_set_only_app_filter` and `test_init_with_only_app_filter` (they test removed API), replacing
   their coverage with parameter-based assertions where still meaningful.

**Item 6 — delete dead Bus child.** In `src/hassette/core/app_lifecycle_service.py`, remove the
`bus: Bus` annotation (`:69`), the `self.bus = self.add_child(Bus)` line (`:86`), the `Bus` mention in
the class docstring (`:54`), and the `Bus` import if nothing else in the file references it. The real
file-watcher subscription lives on `AppHandler.bus` (`app_handler.py:100-104`) and is untouched. No
external code references `lifecycle.bus` (verified during design).

Follow repo conventions (no `from __future__`, `X | None`, no lazy imports). The integration mocks at
`tests/integration/test_apps.py:124,165` `patch.object(...detect_changes)` — a new defaulted `only_app`
kwarg won't break them, but confirm they still pass.

## Focus
- `update_only_app_filter` is called from four sites (`:446,469,475,483`) — all pass through the
  registry setter; after the edit they set only the registry. No call-site signature change needed.
- The integration tests `patch.object(change_detector, "detect_changes")` — adding a defaulted kwarg is
  backward-compatible with the mock. Verify, don't assume.
- Item 6 is pure subtraction with zero external references — the only risk is leaving a dangling `Bus`
  import; remove it if unused, keep it if the file still imports `Bus` for another reason.
- Behavioral invariant: `only_app` filtering must produce the same change-set decisions as before; the
  file-watcher reload path on `AppHandler.bus` must still fire. Existing reload coverage + the new pin
  guard these.

## Verify
- [ ] FR#9: `AppChangeDetector.detect_changes` accepts `only_app` as a parameter and the class holds no `only_app_filter` instance state (field and `set_only_app_filter` removed).
- [ ] FR#10: `AppRegistry` is the sole owner of `only_app`; `update_only_app_filter` no longer syncs the detector; the lifecycle service passes `registry.only_app` into `detect_changes`.
- [ ] FR#13: `AppLifecycleService` no longer constructs or owns a `Bus` child (annotation, `add_child`, docstring, and unused import removed).
- [ ] AC#6: A test asserts `detect_changes(..., only_app=...)` filters correctly with no instance state, and a test pins that `registry.only_app` equals the value passed to the next `detect_changes`.
- [ ] AC#8: No `Bus` child reference remains in `AppLifecycleService`; the `AppHandler.bus` file-watcher reload still fires (existing reload coverage passes).
- [ ] AC#6: The integration tests that `patch.object(...detect_changes)` (`tests/integration/test_apps.py:124,165`) still pass unchanged with the new defaulted `only_app` kwarg.
- [ ] AC#9: The affected unit/integration suites pass for this task; core change — the branch-level `nox -s system`/`nox -s e2e` gate is green before push.
