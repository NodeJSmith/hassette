# Design: Documentation Sync with Recent Code Changes

**Status:** approved
**Spec:** 2034-docs-sync
**Date:** 2026-04-08

## Problem

Seven significant commits landed after the last documentation update (v0.24.0 release prep). The largest gap is a brand-new public API (`hassette.test_utils`) with zero user-facing documentation. Several existing pages are also stale — missing the bus `name=` parameter, registration persistence behavior, and telemetry source-tier changes. All Web UI screenshots predate the color system overhaul and dashboard polish.

## Scope

### In Scope

1. **New "Testing" top-level section** — tutorial-style page documenting `AppTestHarness`, `RecordingApi`, time control, event factories, state seeding, and assertions
2. **Bus docs update** — add "Registration Identity" subsection with `name=` parameter, collision detection, and forward link to persistence
3. **Telemetry/session/dashboard page updates** — registration persistence subsection, source-tier explanation, degraded-mode clarification
4. **Web UI overview update** — mention mobile-responsive design
5. **Cross-reference updates** — link testing page from hassette-vs-ha-yaml.md, advanced/index.md, appdaemon-comparison.md
6. **Screenshot refresh** — retake all Web UI screenshots from demo repo (with prior-session precondition)
7. **mkdocs.yml nav update** — add Testing section before Advanced
8. **Code change: RecordingApi error messages** — remove `SimpleTestServer` references from `NotImplementedError` messages, replace with generic guidance

### Out of Scope

- API reference docs (auto-generated from docstrings)
- Internal architecture docs
- New tutorials beyond testing
- CHANGELOG updates

## Architecture

### New Page: Testing Your Apps

Location: `docs/pages/testing/index.md`
Nav position: Top-level section between "Web UI" and "Advanced" (not after Advanced — testing is a first-class concern, not an advanced topic)

Structure (progressive disclosure):

1. **Installation** — `hassette.test_utils` ships with the main package — no extra install required. Install test runners separately: `pip install pytest pytest-asyncio` (or `uv add --dev pytest pytest-asyncio`). Do NOT reference `hassette[test]` — that extra only installs pytest runners and misleads users into thinking it unlocks the utilities.

2. **Quick Start** — minimal AppTestHarness example (5 lines). The `assert_called` example must use `"call_service"` as the method name (not `"turn_on"`) and the text must explain why — `turn_on`/`turn_off`/`toggle_service` delegate to `call_service` internally, matching the real HA API.

3. **The Test Harness** — full API walkthrough
   - Constructor: `AppTestHarness(AppClass, config={...}, tmp_path=...)`
   - Properties: `app`, `bus`, `scheduler`, `api_recorder`, `states`

4. **State Seeding** — `set_state()`, `set_states()` with examples.
   - `!!! warning` admonition: "`set_state` is pre-test setup only and does not fire bus events. Always call it before any `simulate_*` calls for the same entity — calling it after will silently overwrite the simulated state."

5. **Simulating Events** — `simulate_state_change()`, `simulate_attribute_change()`, `simulate_call_service()`
   - `!!! warning` admonition after `simulate_attribute_change` example: this method delegates to `simulate_state_change`, so any `on_state_change` handler registered for the same entity will also fire. Include code example showing the cross-handler firing and advice to use `api_recorder.reset()` or `get_calls()` for fine-grained inspection.
   - **Timeouts and slow handlers** callout: (a) the default 2s timeout per simulate call, (b) how to override with `timeout=` parameter, (c) limitation that handlers dispatching secondary work via `self.task_bucket.add(...)` are not tracked by `await_dispatch_idle` and may produce premature idle signals.

6. **Asserting API Calls** — `api_recorder.assert_called()`, `assert_not_called()`, `assert_call_count()`, `get_calls()`, `reset()`
   - Explicit note: "`turn_on`, `turn_off`, and `toggle_service` are recorded as `call_service` calls — they delegate to `call_service` internally, matching the real HA API. Assert them with `assert_called("call_service", service="turn_on", ...)` rather than `assert_called("turn_on")`."
   - Note that `assert_called` uses partial (subset) matching — all specified kwargs must be present, but additional kwargs are allowed. This is not exact matching.

7. **Time Control** — Lead with a single canonical worked sequence showing the full protocol: `freeze_time` → schedule job → `advance_time` → `trigger_due_jobs` → assert. Then document each method individually.
   - All code examples must include `from whenever import Instant` with a complete construction example (e.g., `Instant.from_utc(2024, 1, 15, 9, 0)`) and a one-line link to `whenever` docs. No stdlib `datetime` — `freeze_time` accepts `Instant | ZonedDateTime` only.
   - Explicit note: "`advance_time` alone has no effect on scheduled jobs — always call `trigger_due_jobs()` after advancing time."

8. **Event Factories** — document exactly these six symbols from `__all__` (no others): `create_state_change_event`, `create_call_service_event`, `make_state_dict`, `make_light_state_dict`, `make_sensor_state_dict`, `make_switch_state_dict`. Do NOT document Tier 2 symbols like `make_full_state_change_event`.

9. **Configuration Errors** — `AppConfigurationError` and validation

10. **Advanced: make_test_config** — for users who need HassetteConfig without the full harness

11. **Limitations and Troubleshooting**
    - **RecordingApi coverage boundary**: "RecordingApi stubs write methods and state proxy reads. Anything requiring a live HA connection — template rendering, WebSocket calls, history queries, raw state access — raises `NotImplementedError`." Enumerate the specific unimplemented methods in a compact list. Note that `api.sync` is a `Mock()` instance and will silently pass rather than raise — may produce false-green tests.
    - **Concurrency and xdist**: (a) `freeze_time` uses a process-global non-reentrant lock, (b) only one harness at a time may call `freeze_time` in a process regardless of App class, (c) sequential tests in the same worker are safe if the prior `async with` block exits cleanly, (d) for parallelized suites, mark all time-controlling tests with `@pytest.mark.xdist_group('time_control')`, (e) two harnesses for the same App class cannot run concurrently in the same event loop (no `asyncio.gather` with multiple harnesses).
    - **Harness startup failures**: "If the harness raises `TimeoutError: Timed out waiting for <App> RUNNING`, the app's `on_initialize()` either raised an exception or took longer than 5 seconds. Check test output for earlier log lines — initialization exceptions are logged at WARNING level during teardown."

### Existing Page Updates

| Page | Change |
|------|--------|
| `bus/index.md` | Add "Registration Identity" subsection (not under Rate Control) explaining `name=`, the duplicate-listener collision `ValueError`, and a forward link to the "Registration Persistence" subsection in `database-telemetry.md` |
| `database-telemetry.md` | Add "Registration Persistence" subsection: listener/job registrations persist across sessions via upsert semantics, old registrations marked as retired. Add "Source Tier" paragraph: "Framework-internal handlers (telemetry, WebSocket, scheduler services) are recorded with `source_tier='framework'` and excluded from Dashboard KPIs. Handler and Job counts show only your app registrations — not Hassette's own housekeeping listeners." Clarify in degraded mode section: all telemetry including persisted registrations is unavailable when the database is degraded (same SQLite file). |
| `web-ui/dashboard.md` | Note that handler/job counts reflect persisted registrations. Add inline note alongside Handlers KPI card description explaining framework-tier exclusion. |
| `web-ui/sessions.md` | Note about registration persistence across sessions |
| `web-ui/index.md` | Add mobile-responsive mention to intro paragraph |
| `advanced/index.md` | Add testing page link |
| `hassette-vs-ha-yaml.md` | Revise anchor text from "Built-in testing and debugging tools from Python's ecosystem" to reference Hassette-native test utilities (e.g., "Built-in testing harness — test your apps with `AppTestHarness`, event simulation, and time control"), then link to testing page |
| `appdaemon-comparison.md` | Make "Test each app incrementally" in migration checklist a link to testing page; add Testing page to Next Steps block |
| `mkdocs.yml` | Add Testing nav section between Web UI and Advanced |

### Code Change: RecordingApi Error Messages

In `src/hassette/test_utils/recording_api.py`, update `_not_implemented()` and `__getattr__` to remove `SimpleTestServer` references. Replace with generic guidance: "RecordingApi.{method}() is not implemented. Seed state via AppTestHarness.set_state() for read methods, or use a full integration test for methods requiring a live HA connection."

### Screenshot Refresh

Use the demo repo workflow (see `reference_demo_screenshots.md` memory) to capture fresh screenshots for:
- `_static/web_ui_dashboard.png`
- `_static/web_ui_apps.png` (if referenced)
- `_static/web_ui_sessions.png`
- `_static/web_ui_logs.png` (if referenced)

**Precondition**: Before capturing, ensure the demo repo has completed at least one prior session so persisted handler/job counts are non-zero. Run the demo once, stop it, then restart and screenshot.

## Alternatives Considered

1. **Testing page under Advanced** — rejected: testing is a first-class concern for the target audience (automation authors), not an advanced topic. Top-level section makes it discoverable.
2. **Defer screenshots** — rejected by user: include in this workflow.
3. **Multiple testing pages (one per topic)** — rejected: the API surface is compact enough for a single well-structured page. Can split later if it grows.
4. **Keep `hassette[test]` in install instructions** — rejected: the extra only installs pytest runners, not test_utils (which ships in the main package). Misleads users into thinking an install unlocks functionality that's already there.
5. **Document SimpleTestServer as escape hatch** — rejected: changing the error messages to remove the reference is cleaner than documenting a Tier 2 internal tool. Code change included in scope.

## Risks

- **Demo repo availability** — screenshots require the demo repo running with sample data. If unavailable, screenshots can be deferred to a follow-up commit.
- **Test utils API stability** — the API is marked Tier 1 in `__all__`, so it's stable. Document only what's in `__all__`.
- **`whenever` library unfamiliarity** — mitigated by including complete import + construction examples in every time control code snippet.
