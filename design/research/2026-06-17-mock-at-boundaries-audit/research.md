# Research Brief: "Mock at Boundaries Only" violations across the test suite (issue #1036)

**Date:** 2026-06-17
**Question:** Beyond the 5 spots issue #1036 already names, what *else* in the test suite patches Hassette's own internal collaborators instead of mocking only system boundaries — so we can produce a complete cleanup list before refactoring?

**Method:** Five parallel read-only auditors swept the whole `tests/` tree (276 test files), each applying the same decision rule: *patching a method/attribute on a **real, constructed** Hassette object = violation; configuring a fake built from the ground up (`make_mock_hassette()`, `create_hassette_stub()`, local `Mock()`) = sanctioned.* Contested categories were then verified by hand against `src/` (see "Verification & corrections").

---

## Bottom line

The 5 known spots are the tip of a much larger pattern. The genuine, high-value cleanup is **internal-method patching on real `WebsocketService`, `StateProxy`, and `AppLifecycleService` objects** — roughly **45–50 sites across ~7 files**, of which the issue named only 5. A separate **systemic, by-design helper** (`bus_service.add_listener`, ~30 sites) is debatable and probably out of scope. The raw auditor aggregate ("~107 hits") is inflated; after correcting two mis-classified categories the real, defensible violation count is **~55–65 sites**, dominated by two service families.

This is a **medium–large** refactor, larger than #1036's framing suggests. Recommend scoping it as a few independently-landable waves by service family, with the existing tests as the behavioral pin.

---

## Verification & corrections (why the raw aggregate is not the answer)

Two auditor categories were checked against source and **reclassified**:

1. **`hassette.api.get_states_raw` patches are NOT violations.** `get_states_raw` is defined at `src/hassette/api/api.py:367` — it is the real `Api` method that calls the HA REST boundary. Patching it *is* mocking at the boundary, and issue #1036 itself names `get_states_raw` as the injection point to replace `load_cache` patching. Agent 4 flagged ~5 of these as High; they are removed from the violation count. (Optional, low-value cleanup: route them through the harness `RecordingApi` / mock API server instead of `monkeypatch`, but that is a style preference, not a boundary violation.)

2. **`logger` patches are Low, not High.** Patching `service.logger` (DatabaseService, others) is log-assertion avoidance, not an internal-collaborator short-circuit. Downgraded.

One category confirmed **real** but **systemic/by-design** (see Cluster D):
- `bus.bus_service` is the real `BusService` (`hassette_with_bus._bus`), and `add_listener` (src `bus_service.py:121`) does a DB write. The `mock_add_listener` conftest helper patches it with restore-on-exit, deliberately, and is documented. Real violation in principle; questionable ROI to "fix."

Auditor 2 (unit top-level + scheduler) and Auditor 5 (e2e + system) found **zero** violations — confirmed clean. e2e configures a `create_hassette_stub()` MagicMock (sanctioned); system tests run real components against real HA (no internal mocking).

---

## Prioritized inventory

### Cluster A — WebsocketService internal-method patching  **(HIGH, ~27 sites, 3 files)**
Real `WebsocketService` objects with their own methods overwritten, short-circuiting connection/cleanup/dispatch logic. This defeats the purpose of the tests (especially the integration ones).

| File | Sites (approx) | Patched symbols |
|---|---|---|
| `tests/integration/test_websocket_service.py` | ~15 (300, 317, 430, 466, 469, 600–601, 641–642, 676–677, 714, 744, 776–777, 864–865) | `make_connection`, `partial_cleanup`, `respond_if_necessary`, `dispatch`, `authenticate`, `mark_ready`, `_emit_readiness_event` |
| `tests/unit/core/test_ws_connection_state.py` | ~6 (158, 211, 212, 233, 259, 260) | `make_connection`, `partial_cleanup` |
| `tests/unit/core/test_websocket_readiness_events.py` | ~6 (69, 70, 117, 159, 161, 162) | `make_connection`, `partial_cleanup`, `task_bucket`, `send_connection_established_event`, `subscribe_events` |

**Should instead:** mock the aiohttp `ClientSession`/websocket boundary beneath `make_connection`, and observe readiness/connection events through the bus rather than patching `_emit_readiness_event`/`send_connection_established_event`. **(Includes 3 of the 5 known spots.)**

### Cluster B — StateProxy internal-method patching  **(HIGH, ~10 sites, 1 file)**
`tests/integration/test_state_proxy.py`: patches `load_cache` (604, 636), `subscribe_to_events` (576, 605), `mark_not_ready` (378, 394, 412, 540, 740), `_emit_readiness_event` (563, 665, 681) on the real harness-wired StateProxy.

**Should instead:** drive reconnect/readiness through the public surface (`on_reconnect()`, `is_ready()`) and assert on emitted bus events; mock the HA boundary via `RecordingApi`/mock server (which `get_states_raw` patching already approximates). **(Includes the `load_cache` known spot.)**

### Cluster C — AppLifecycleService / AppHandler internal patching  **(HIGH, ~9 sites, 3 files) — NEW, not in #1036**
- `tests/unit/core/test_app_lifecycle_service.py` (357, 358): `resolve_only_app`, `handle_crash`
- `tests/unit/core/test_app_lifecycle_service_operations.py` (14, 15, 16): `stop_app`, `reload_app`, `start_app`
- `tests/integration/test_apps.py` (123, 163, 164): `change_detector.detect_changes`, `lifecycle.refresh_config`

**Should instead:** mock the `AppFactory`/`AppRegistry`/`AppChangeDetector` collaborators (or the config-file boundary) and drive through the public `apply_changes()` / `handle_change_event()` entry points.

### Cluster D — bus_service / TaskBucket helper patching  **(MEDIUM, ~30 sites, 3 files) — SYSTEMIC, by-design**
`mock_add_listener` in `tests/unit/bus/conftest.py:54` plus inline equivalents in `test_if_exists.py` and `test_t04_once_listener_tracking.py` patch real `bus_service.add_listener`, `mark_listener_cancelled`, and `task_bucket.spawn` (all with try/finally restore). Real objects, but the patched methods sit right above the DB/task boundary, and the helper is deliberate and documented.

**Should instead (if pursued):** let `add_listener` run against the harness's real in-memory DB, or introduce a DB-failure seam at the boundary. **Recommend treating as a separate decision** — the ROI is low and the helper is intentional. Flag in the design doc; don't bundle into the core refactor.

### Cluster E — Lower-volume real-object patches  **(MEDIUM)**
- `tests/unit/core/test_scheduler_service_reschedule.py` (~15 sites): patches `run_job_with_guard` on a `SchedulerService.__new__(...)` hand-built double whose `task_bucket` is already mocked. Gray zone — the object is a scaffold, the boundary below is already faked. Redrivable but low urgency.
- `tests/integration/test_scheduler_mode.py` (1025, 1066): `warn_stalled_job` on real scheduler_service.
- `tests/integration/test_service_watcher.py` (195): `shutdown_safe_sleep` → **should mock the `asyncio.sleep` / time boundary** instead.
- `tests/unit/bus/test_duration_hold.py` (~9 sites: 251, 271, 293, 317, 343, 461, 494, 528): assigns a `MagicMock` to the private `listener.duration_config._timer`. The `DurationTimer` is effectively the time boundary, so mocking it is reasonable — the violation is reaching into `_timer` directly instead of via the public `attach_timer()` seam.
- `tests/unit/bus/test_bus_contract.py` (122): patches `bus_service._executor.register_listener` to simulate DB failure → should fail at the DB boundary.

### Cluster F — Vacuous assertions / cosmetic  **(LOW)**
- `tests/integration/test_history.py:78`: `mock_normalize.return_value = lambda x: x` → should be `side_effect=lambda x: x` (currently returns a function, not data; applied asymmetrically across the minimal/full branches). **(The known vacuous-assertion spot.)**
- `tests/integration/database/test_database_service.py` (488, 537, 555): `logger` patches — cosmetic, downgraded from auditor's "High."
- `tests/integration/database/test_database_service.py:505`: `get_db_size_mb` → mock the filesystem/DB boundary.

---

## Rollup

| Cluster | Severity | ~Sites | Files | In #1036? |
|---|---|---|---|---|
| A — WebsocketService | High | ~27 | 3 | partial (3 lines) |
| B — StateProxy | High | ~10 | 1 | partial (1 line) |
| C — AppLifecycle/AppHandler | High | ~9 | 3 | **no (new)** |
| D — bus_service helper | Medium (systemic) | ~30 | 3 | no |
| E — scheduler/watcher/timer/contract | Medium | ~27 | 5 | no |
| F — vacuous/cosmetic | Low | ~5 | 2 | partial (1 line) |

**Defensible violation count (excluding the get_states_raw false-positives and treating Cluster D as one decision):** ~55–65 genuine sites if D is included, ~25–35 high-value sites (Clusters A+B+C) if D is deferred.

## Recommended scoping

1. **Wave 1 (the issue's core, expanded):** Clusters A + B — WebsocketService and StateProxy. These are the two services #1036 named; fixing only the 5 cited lines would leave ~32 sibling violations in the same files. Mock the aiohttp/HA boundary once per file and redrive through public surfaces. Largest payoff.
2. **Wave 2:** Cluster C (AppLifecycle/AppHandler) — new, self-contained, 3 files.
3. **Wave 3 (optional / separate decision):** Cluster D (bus_service helper) — flag in design, decide whether the documented helper is worth unwinding.
4. **Fold in opportunistically:** Clusters E + F alongside whichever wave touches the same file (e.g. fix `test_history.py:78` and the DatabaseService logger/`get_db_size_mb` items when in those files).

**Pin:** the existing tests are green today; per refactoring discipline they are the behavioral contract. Each wave must keep them green, and the WebsocketService/StateProxy work in particular should be re-verified against the `system` + `e2e` suites (CLAUDE.md core-change rule), since those exercise the real boundaries the unit tests are currently mocking away.

## Open questions for design

- Is Cluster D (the deliberate `mock_add_listener` helper) in scope, or explicitly excluded? It's the single biggest site count and the most defensible to leave alone.
- For Cluster E's scheduler `__new__` doubles: keep as lightweight scaffolds, or migrate to `make_mock_hassette()` / a real harness SchedulerService?
- Should `get_states_raw` monkeypatching be migrated to `RecordingApi` for consistency, even though it's not a violation?
