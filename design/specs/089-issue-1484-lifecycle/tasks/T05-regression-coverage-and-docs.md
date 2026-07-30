---
task_id: "T05"
title: "Finish no-HA regressions and docs"
status: "planned"
depends_on: ["T01", "T02", "T03", "T04"]
implements: ["FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "FR#25", "FR#26", "FR#29", "FR#32", "FR#33", "FR#34", "AC#2", "AC#3", "AC#4", "AC#17", "AC#18", "AC#20", "AC#23", "AC#24", "AC#26"]
---

## Summary
Add the final cross-component regressions that prove the new lifecycle holds under real startup ordering, no-HA operation, delayed recovery, and web/UI surfaces. This task is the integration/system/e2e backstop the design calls for, and it also updates `CLAUDE.md` so future work reflects the new coordinator, stricter initial state requirements, and no-HA bootstrap behavior. Keep the docs change scoped to architecture guidance only; there is no docs-site update in this issue.

## Target Files
- modify: `CLAUDE.md`
- modify: `tests/integration/test_dashboard_without_ha.py`
- modify: `tests/system/conftest.py`
- modify: `tests/system/test_startup_without_ha.py`
- modify: `tests/e2e/test_dashboard_without_ha.py`
- modify: `tests/integration/test_state_proxy.py`
- modify: `tests/integration/test_apps.py`
- modify: `tests/integration/web_api/test_endpoints.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- modify: `tests/unit/core/test_app_lifecycle_service_operations.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- read: `src/hassette/core/runtime_query_service.py`
- read: `src/hassette/core/state_proxy.py`
- read: `src/hassette/web/routes/apps.py`

## Prompt
Implement the remaining cross-component regression coverage from `## Test Strategy` plus the `## Documentation Updates` section.

Update the no-HA integration, system, and e2e tests so they assert the approved behavior: the web API/dashboard starts while Home Assistant is unavailable, no app instance bootstraps before the coordinator releases, delayed Home Assistant recovery bootstraps apps only after successful state capability, manual start/reload before release returns the explicit retryable response, repeated config/file changes before release coalesce, shutdown cancels unresolved bootstrap waits promptly, and health stays on the existing `starting` / `degraded` / `ok` meanings. Use deterministic gates, not sleeps, for delayed-connect and shutdown-wait assertions.

Update `CLAUDE.md` to document AppBootstrapCoordinator ownership, strict initial bootstrap prerequisites, StateProxy's separate lifecycle-versus-capability semantics, websocket external readiness meaning, and the changed no-HA startup behavior. Do not add docs-site pages or richer dashboard lifecycle phases.

## Focus
- `tests/integration/test_dashboard_without_ha.py`, `tests/system/test_startup_without_ha.py`, and `tests/e2e/test_dashboard_without_ha.py` currently assert the old degraded-app-startup behavior; this task is where those end-to-end expectations change.
- `tests/system/conftest.py` is a reverse dependency because `session_ready()` currently requires `app_handler.is_ready()`, which will now be coordinator-driven and must still allow no-HA dashboard startup scenarios to be tested deterministically.
- `CLAUDE.md` must preserve the design's non-goals and existing health semantics while explaining the new coordinator/state capability split.
- Keep this task focused on cross-component proofs and docs. Unit-level coverage belongs in the earlier implementation tasks.

## Verify
- [ ] FR#3: No-HA startup tests prove app bootstrap stays blocked until external websocket readiness exists.
- [ ] FR#4: Delayed-connect tests prove apps remain blocked until the first successful initial snapshot.
- [ ] FR#5: Delayed-connect tests prove bootstrap waits for snapshot plus journal commit completion, not just raw websocket connection.
- [ ] FR#6: Integration/system/e2e no-HA tests prove the web API and dashboard remain available while apps wait.
- [ ] FR#7: Delayed Home Assistant recovery tests prove apps bootstrap without restarting Hassette.
- [ ] FR#25: `tests/integration/test_apps.py` proves a post-release disconnect leaves existing app instances registered and does not re-block a subsequent allowed lifecycle operation.
- [ ] FR#26: Health endpoint and websocket-connected payloads still report only `starting`, `degraded`, or `ok`.
- [ ] FR#29: Shutdown tests prove unresolved bootstrap waits are canceled without delaying framework shutdown.
- [ ] FR#32: Route-level regressions prove manual start/reload before release return the explicit retryable response.
- [ ] FR#33: Cross-component reconciliation tests prove repeated pre-release config/file changes collapse to one latest desired state.
- [ ] FR#34: `tests/integration/test_state_proxy.py` proves one current-generation poll/timer retry runs after recoverable failure and an obsolete generation's pending retry is canceled.
- [ ] AC#2: With Home Assistant unavailable, the web API is usable while no app instance is bootstrapped.
- [ ] AC#3: When Home Assistant becomes available later, apps bootstrap after successful snapshot and journal commit without process restart.
- [ ] AC#4: Recoverable initial connection/snapshot/journal failures leave apps blocked while recovery continues.
- [ ] AC#17: `tests/integration/test_state_proxy.py` observes stale capability after disconnect while `tests/integration/test_apps.py` observes the same running app instance remains registered.
- [ ] AC#18: System health remains `starting` before first connection, `degraded` after losing one, and `ok` while connected.
- [ ] AC#20: Shutdown cancels the waiting bootstrap coordinator cleanly.
- [ ] AC#23: Manual HTTP start/reload before release returns the explicit retryable status and retains no waiting task.
- [ ] AC#24: Repeated config/file changes before release reconcile once using the latest desired state after release.
- [ ] AC#26: `tests/integration/test_state_proxy.py` observes successful convergence through poll-or-timer retry and no execution from the superseded retry.
