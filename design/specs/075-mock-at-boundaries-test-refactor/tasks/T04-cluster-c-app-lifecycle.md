---
task_id: "T04"
title: "Cluster C: drive AppLifecycle/AppHandler tests through public entry points"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#5", "FR#8", "AC#5"]
---

## Summary
Convert the app lifecycle tests across three files so they mock the lifecycle's collaborators (`AppFactory`, `AppRegistry`, `AppChangeDetector`, or the app-dir/config boundary) and drive through the public entry points (`apply_changes()`, `handle_change_event()`), rather than patching the lifecycle methods (`start_app`, `stop_app`, `reload_app`, `resolve_only_app`, `handle_crash`, `detect_changes`, `refresh_config`) when those are the method under test.

## Target Files
- modify: `tests/unit/core/test_app_lifecycle_service.py` — convert `resolve_only_app`/`handle_crash` MUT patches
- modify: `tests/unit/core/test_app_lifecycle_service_operations.py` — convert `stop_app`/`reload_app`/`start_app` MUT patches
- modify: `tests/integration/test_apps.py` — convert `detect_changes`/`refresh_config` MUT patches
- read: `src/hassette/app/` and the AppHandler/AppLifecycleService implementation — `apply_changes`, `handle_change_event`, and the collaborators
- read: `design/specs/075-mock-at-boundaries-test-refactor/tasks/context.md`
- read: `design/specs/075-mock-at-boundaries-test-refactor/design.md`

## Prompt
For each prohibited lifecycle symbol patch in the three files, determine the test's MUT and act:

1. **Tests whose MUT is a lifecycle operation** (`start_app`/`stop_app`/`reload_app`/`resolve_only_app`/`handle_crash`/`detect_changes`/`refresh_config`) currently patch that method to short-circuit it: instead, mock the lifecycle's **collaborators** — `AppFactory`, `AppRegistry`, `AppChangeDetector`, and/or the app-dir/config file boundary — and drive the real method through the public `apply_changes()` / `handle_change_event()` entry points.
2. **If a method is genuinely a collaborator of the MUT** (e.g. a test of `handle_change_event` that stubs `detect_changes` as a collaborator), keep the stub and annotate it `# boundary-exempt: collaborator of <MUT>` — same dual-role rule as Cluster A. Classify per-test by MUT.
3. Assert on observable outcomes — registry state, emitted events, app status snapshots — not on internal-method call spies where a public observable exists.

First read the AppHandler/AppLifecycleService source to confirm the exact names and signatures of `apply_changes`, `handle_change_event`, and the collaborator classes (`AppFactory`, `AppRegistry`, `AppChangeDetector`) before editing. Run each file after conversion; confirm green.

## Focus
- Confirm the public entry-point method names against the source before relying on them (`apply_changes` / `handle_change_event` are named in the design's Architecture → Cluster C; verify they exist and their signatures).
- `test_app_lifecycle_service.py` patches imported collaborators (e.g. `patch("...AppFactory")`) in some places — those are legitimate boundary mocks (external collaborator), NOT MUT patches; keep them. The violations are the `lifecycle_service.<method> = AsyncMock()` reassignments on the real service (e.g. `resolve_only_app`, `handle_crash`, `stop_app`, `reload_app`, `start_app`).
- `test_apps.py` patches `change_detector.detect_changes` and `lifecycle.refresh_config` on a real harness-wired AppHandler — drive through `handle_change_event()` instead.
- Watch for the dual-role case: `detect_changes` may be the MUT in one test (convert) and a collaborator of `handle_change_event` in another (annotate).
- Test-only; gap check clean.

## Verify
- [ ] FR#1: No test in the three files patches its own MUT among the lifecycle methods; mocks are limited to collaborators (`AppFactory`/`AppRegistry`/`AppChangeDetector`/config boundary), each annotated where it's a deliberate collaborator stub.
- [ ] FR#5: Lifecycle-operation tests drive the real method through `apply_changes()`/`handle_change_event()` with collaborators mocked, rather than patching `start_app`/`stop_app`/`reload_app`/`resolve_only_app`/`handle_crash`/`detect_changes`/`refresh_config` as the MUT.
- [ ] FR#8: Every changed test asserts an observable outcome; no configured-but-unasserted mocks remain.
- [ ] AC#5: Breaking `stop_app` (a representative method) causes at least one in-scope lifecycle test to fail.
