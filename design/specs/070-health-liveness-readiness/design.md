# Design: Health Endpoints, Status Taxonomy, and Fatal-Exit Observability

**Date:** 2026-06-05
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-06-05-health-status-lifecycle-modeling/research.md

## Problem

When Home Assistant goes down, a running Hassette instance enters an external reboot loop. The cause is a single `/api/health` endpoint that conflates two unrelated questions — "should you restart me?" (liveness) and "are you connected to HA?" (readiness) — into one signal, and a status taxonomy that cannot tell "still booting" apart from "booted fine, then lost HA."

Concretely: when the WebSocket drops, `StateProxy.on_disconnect()` clears its cache and calls `mark_not_ready()`. `RuntimeQueryService.get_system_status()` then sees `ws_connected=False` and `proxy_ready=False` and reports `"starting"`, which `/api/health` maps to HTTP 503. External restart tooling (a Docker healthcheck driving `willfarrell/autoheal`) reads 503 as "unhealthy, restart me." Restarting cannot make HA return, so the instance boots, still can't reach HA, reports `"starting"`/503 again, and loops.

This is the single most-documented anti-pattern in the health-check literature (Kubernetes, Spring Boot, ASP.NET, AWS Well-Architected all warn against it): a dependency check living in the signal that triggers restarts. The `"degraded"` status (HTTP 200) that PR #975 introduced to handle this is unreachable during a sustained outage: `on_disconnect()` revokes proxy readiness before `get_system_status()` runs, so the instance falls through to `"starting"`. (It surfaces only in the brief race window before `on_disconnect()` fires — which is why the current `degraded` integration test happens to pass.)

A second, related gap surfaces once liveness is correct: Hassette already self-terminates on a genuinely fatal failure (a PERMANENT service exhausting its restart budget, or a fatal error), but it does so **silently** — `run_forever()` returns normally and the process exits `0` whether the shutdown was a clean SIGTERM or a fatal crash. A supervisor using systemd `Restart=on-failure` therefore won't restart after a fatal exit, because exit `0` reads as success. The self-shutdown model is correct; it just isn't legible to the layer that's supposed to react to it.

## Goals

- A booted instance that loses the HA WebSocket never reports a restart-worthy signal. The reboot loop stops, and restart automation targets a liveness signal that ignores HA connectivity entirely.
- Separate three questions into three endpoints: liveness ("is the process able to serve at all — restart me?"), readiness ("route traffic to me / am I fully functional?"), and the human aggregate (`/api/health`).
- The status taxonomy distinguishes "never finished booting" (`starting`) from "booted, lost HA" (`degraded`) via a one-way ever-connected latch.
- **Liveness reflects only whether the process can serve a request — no dependency check and no service-state reduction.** This is the central anti-pattern the work eliminates. Readiness is a reduction over the aggregate status.
- Fatal, unrecoverable failures self-terminate the process **observably**: a non-zero exit code (so `Restart=on-failure` reacts), a clear top-level log line naming the cause, and the crash recorded to the telemetry database before exit. This makes Hassette's existing self-shutdown model legible to external supervisors.
- The latch, the endpoint split, and the fatal-exit observability ship together in one PR.

## Non-Goals

- No per-dependency IETF `health+json` `checks` map in the payload this round (deferred to a follow-up; see Open Questions).
- No new monitoring-UI affordance that surfaces liveness and readiness as separate indicators (a follow-up issue will be filed; the UI continues to show one status driven by the corrected taxonomy).
- **No change to the restart/budget supervision logic** — restart types, sliding-window intensity/period budgets, and the restart-vs-give-up decisions in `ServiceWatcher` are correct and untouched. The fatal-shutdown path is extended only to propagate a non-zero exit code and a clear log; the *decision* to shut down on PERMANENT exhaustion is unchanged.
- **No change to the self-shutdown model itself.** Fatal failure → self-terminate → external restart is the deliberate, validated choice (see Architecture → Shutdown model). This work makes that model observable, it does not replace it with a stay-alive-and-report-dead model.
- No change to how `StateProxy` handles its cache on disconnect (retaining last-known state for softer degradation is a separate, larger question).

## User Scenarios

### Operator (self-hosting Hassette behind Docker + autoheal): keep the instance alive across HA outages
- **Goal:** Run Hassette unattended; have it survive HA restarts without manual intervention.
- **Context:** Hassette in a container with a Docker `healthcheck` and `willfarrell/autoheal` watching an `autoheal=true` label.

#### HA restarts while Hassette is running

1. **HA goes down** (update, reboot, network blip).
   - Sees: Hassette logs "WebSocket disconnected"; the WS service begins TRANSIENT reconnect.
   - Then: `/api/health` continues returning HTTP 200 with body `status: "degraded"`; `/api/health/live` returns 200.
2. **autoheal polls the configured liveness endpoint.**
   - Sees: 200 — healthy.
   - Decides: no restart.
   - Then: Hassette stays up, retrying the WS connection.
3. **HA returns.**
   - Sees: WS reconnects, `StateProxy` resyncs, status returns to `ok`.
   - Then: full function resumes with no restart having occurred.

### Operator: cold start while HA is unreachable

1. **Hassette starts but HA is down from the outset.**
   - Sees: status `starting`; `/api/health/ready` returns 503 (not ready to serve); `/api/health/live` returns 200 (process is fine).
   - Then: a healthcheck wired to liveness does not restart it; a readiness-gated load balancer does not route to it yet. When HA appears, status advances to `ok`.

### Operator: a core service dies unrecoverably

1. **A PERMANENT service (Bus or Scheduler) exhausts its restart budget.**
   - Sees: Hassette logs the failing service and reason at ERROR, records the crash to the telemetry session, and shuts down.
   - Then: the process exits with a **non-zero** status. The external restart policy (`restart: unless-stopped`, or systemd `Restart=on-failure`) starts a fresh process from a clean state. `/api/health/live` plays no part here — the process is gone, so probes get connection-refused, which *is* the liveness signal.
2. **Operator later inspects what happened.**
   - Sees: the prior session in the telemetry DB carries the failure status and reason, surviving the restart; the final log lines name the fatal cause.

### Platform / infra integrator: wire the right probe

1. **Choosing which endpoint to monitor.**
   - Sees: docs stating `/api/health/live` = restart signal (HA-independent), `/api/health/ready` = traffic/functional signal, `/api/health` = human/aggregate (always 200 while serving). For container restart-on-fatal, the process exiting non-zero is the primary signal; the liveness probe catches the secondary case of a hung-but-not-exited process.
   - Decides: points container restart automation at `/api/health/live` (and/or relies on the restart policy reacting to a non-zero exit), load-balancer routing at `/api/health/ready`.

## Functional Requirements

- **FR#1** The WebSocket service exposes a one-way "ever connected" latch that becomes true the first time the connection reaches `CONNECTED` and never reverts for the process lifetime.
- **FR#2** `get_system_status()` reports `degraded` when the latch is set and the WebSocket is not currently connected, and reserves `starting` for when the latch has never been set.
- **FR#3** `get_system_status()` reports `ok` when the WebSocket is currently connected, unchanged from today.
- **FR#4** A liveness signal is exposed at `GET /api/health/live` that returns HTTP 200 whenever the process can serve the request. It performs no dependency check and no service-state reduction — HA being down, or any individual service being degraded, never changes its response.
- **FR#5** A readiness signal is exposed at `GET /api/health/ready` that returns HTTP 200 only when the aggregate status is `ok`, and 503 when the status is `degraded` or `starting`.
- **FR#6** `GET /api/health` returns HTTP 200 for `ok`, `degraded`, and `starting`. The handler never returns 503. Its response body continues to carry the full system status including the `ok`/`degraded`/`starting` value.
- **FR#7** A failure-driven shutdown terminates the process with a non-zero exit status; an operator-initiated shutdown (SIGTERM) terminates with exit status zero. Failure-driven covers any service reaching `CRASHED` — which is always terminal and always triggers a full shutdown (PERMANENT budget exhaustion or a fatal error, regardless of restart type) — and a startup failure (session-tracking init or required services failing to start).
- **FR#8** The CLI `hassette status` command surfaces the corrected status taxonomy without erroring when the instance is `degraded` or `starting` (a status query is not itself a failure).
- **FR#9** A fatal service crash is persisted to the telemetry database — the active session is marked with the failure status — before the process exits, so the cause survives the restart.

## Edge Cases

- **Web API disabled (`web_api.run = False`):** no health endpoints exist; the latch and status logic are inert. The fatal-exit path is independent of the web API and still applies. No regression.
- **PERMANENT service exhausts its budget (terminal):** the supervisor records the crash to the telemetry session and triggers shutdown; the process exits non-zero; the external restart policy starts a fresh process. The graceful teardown (telemetry flush, session finalize) runs *before* the non-zero exit, so the crash record is durable.
- **Event loop wedged (hung, not crashed):** no service is `CRASHED`, but the async `/api/health/live` handler can't run, so a liveness probe times out — liveness correctly fails. (A service-state reduction would have missed this, since all services still report `RUNNING`.)
- **Clean shutdown (SIGTERM / `docker stop` / operator stop):** the process exits `0`. systemd `Restart=on-failure` does not restart it; `docker stop` is honored. Only a *fatal* exit is non-zero.
- **TRANSIENT/TEMPORARY service exhausted (e.g. database past its cooldown limit → `EXHAUSTED_DEAD`, file watcher dead):** does NOT trigger a fatal exit — exhaustion of a non-critical service sets `EXHAUSTED_DEAD` (not `CRASHED`), so `shutdown_if_crashed` never fires; the process stays alive and serving, function degrades gracefully, and `/api/health/live` stays 200.
- **Any service raises a fatal error (`fatal_error_name`):** emits `CRASHED` regardless of restart type → the universal `shutdown_if_crashed` reaction → full shutdown → non-zero exit. Fatal means fatal, even for a TRANSIENT service. (A *recoverable* failure emits `FAILED`, not `CRASHED`, and is restarted within budget — it never reaches this path.)
- **Status queried during the brief startup window before any service is `RUNNING`:** `starting`; `/ready` 503; `/live` 200 (the process is serving).

## Acceptance Criteria

- **AC#1** With the latch set and the WebSocket reporting not-connected, `get_system_status().status == "degraded"` (regression test for the reboot loop). Maps to FR#1, FR#2.
- **AC#2** With the latch never set and the WebSocket not connected, `get_system_status().status == "starting"`. Maps to FR#2.
- **AC#3** `GET /api/health` returns 200 with body `status == "degraded"` for a booted, WS-disconnected instance. Maps to FR#6, FR#2.
- **AC#4** `GET /api/health/ready` returns 503 when status is `degraded` or `starting`, and 200 when `ok`. Maps to FR#5.
- **AC#5** `GET /api/health/live` returns 200 while the WS is disconnected and during the startup window — its response never depends on HA connectivity or service state. Maps to FR#4.
- **AC#6** `GET /api/health` returns 200 for `ok`, `degraded`, and `starting`; the handler never returns 503. Maps to FR#6.
- **AC#7** The OpenAPI schema and generated frontend types regenerate cleanly and the frontend builds against the status response. Maps to FR#6.
- **AC#8** `hassette status` against a `degraded` or `starting` instance prints the status without a non-zero exit attributable to the health code. Maps to FR#8.
- **AC#9** `GET /api/health` returns 200 with body `status == "ok"` when the WebSocket is connected (baseline unchanged). Maps to FR#3.
- **AC#10** A fatal shutdown (a PERMANENT service exhausting its budget) causes the process to exit with a non-zero status code. Maps to FR#7.
- **AC#11** An operator/SIGTERM shutdown causes the process to exit with status code 0. Maps to FR#7.
- **AC#12** After a fatal service crash, the active session row in the telemetry database carries the failure status, written before shutdown completes. Maps to FR#9.

## Key Constraints

- **Liveness must reflect only whether the process can answer.** No HA-connection check, no per-service status reduction. The moment liveness consults a dependency or a service status, it can flip on a recoverable condition — the exact restart-storm anti-pattern this work exists to eliminate.
- Do not add a fourth status literal (e.g. `reconnecting`). The `ok`/`degraded`/`starting` triple plus the latch fully expresses the states; a new literal would ripple through the domain model, web models, mappers, frontend types, tests, and docs for no gain.
- The latch is one-way for the process lifetime. It must not be cleared on disconnect (clearing it would reintroduce the `starting` conflation).
- The latch reads existing lifecycle state and lives at the WS transition chokepoint; it must not introduce a parallel status-tracking mechanism alongside `ResourceStatus`/`ready_event`.
- The fatal-exit path must run the normal graceful teardown (telemetry flush, session finalize) **before** the non-zero exit. A fatal exit that skips teardown loses the crash record.

## Dependencies and Assumptions

- The latch is set inside `WebsocketService._set_connection_state()` — the single chokepoint all connection transitions pass through (`websocket_service.py:135`) — so it cannot be bypassed and does not depend on bus-event delivery or timing.
- `RuntimeQueryService.get_system_status()` (`runtime_query_service.py:269`) already reads `self.hassette.websocket_service.is_ready()`; reading `ever_connected` alongside it requires no new wiring.
- The fatal-exit code reuses the existing exit-code machinery: `cli/commands/run.py:45` runs `asyncio.run(run_server(config))` inside a `try` that already maps `FatalError → SystemExit(1)` (`run.py:52`). The change is to make `run_forever()` raise `FatalError` after a fatal-triggered teardown, rather than returning normally.
- The crash-persistence requirement (FR#9) is **largely already implemented**: `SessionManager.on_service_crashed` (`session_manager.py:93`) subscribes to `CRASHED` status events and `finalize_session` (`:118`) preserves the failure status to the DB during teardown. This design confirms that path holds under the fatal-shutdown sequence and adds test coverage; it does not build it from scratch.
- Depends on the worktree's frontend install + schema regeneration toolchain (`scripts/export_schemas.py --types`, `cd frontend && npm install && npm run build`) per `.claude/rules/frontend-worktree.md`.
- The deployment-side `autoheal` re-enable and pointing the Docker healthcheck at `/api/health/live` happen in the separate `homelab` repo, out of scope for this PR but documented as follow-up guidance.

## Architecture

The change spans the web/runtime layer (latch, status taxonomy, endpoints) and a small, contained extension to the shutdown/exit path.

**Latch (`src/hassette/core/websocket_service.py`).** The "ever connected" fact belongs to the service that owns the connection lifecycle. The WebSocket service already routes every transition through one chokepoint — `_set_connection_state()` — and already tracks `connection_state` and `_connected_at`. Add an instance attribute `_ever_connected: bool = False` in `__init__`, set `self._ever_connected = True` inside `_set_connection_state()` whenever the new state is `ConnectionState.CONNECTED`, and expose a read-only `ever_connected` property. Setting it inside the transition — rather than from the `HASSETTE_EVENT_WEBSOCKET_CONNECTED` bus event — makes it true synchronously the instant the connection lands: no async hop, no processing-gap race.

Nothing existing already encodes this. `_connected_at` resets to `None` on disconnect, and `ConnectionState` is current-state-only — a reconnecting instance and a cold-booting one both sit in `CONNECTING`. A single boolean set at the transition chokepoint is the minimal honest addition.

Note: `RuntimeQueryService` already has an `_on_ws_connected` handler subscribed to the connected bus event (`runtime_query_service.py:111`, `:202`), but its job is broadcasting connectivity to WS dashboard clients — it is not where the latch is set.

**Status taxonomy (`src/hassette/core/runtime_query_service.py`).** `RuntimeQueryService` stays a pure reader of lifecycle state. In `get_system_status()`, change the status reduction from:

```python
if ws_connected:
    status = "ok"
elif proxy_ready:
    status = "degraded"
else:
    status = "starting"
```

to key the middle tier off the latch read from the WebSocket service:

```python
ws = self.hassette.websocket_service
if ws.is_ready():
    status = "ok"
elif ws.ever_connected:
    status = "degraded"
else:
    status = "starting"
```

The `proxy_ready` fallback is dropped. It was never a reliable `degraded` signal: during a sustained outage `StateProxy.on_disconnect()` revokes `proxy_ready` before `get_system_status()` runs, so the instance falls through to `starting` — the bug. It is reachable only in the race window before `on_disconnect()` fires, which is why the current `degraded` integration test happens to pass. The latch replaces this race-prone fallback with a deterministic signal. The existing `degraded` test is updated to drive `ever_connected`.

**Endpoints (`src/hassette/web/routes/health.py`).** Keep one handler for the aggregate and add two. No `is_live()` predicate exists — liveness is the absence of a check:
- `GET /api/health` — returns the full `SystemStatusResponse`, always HTTP 200 while the process can answer. The handler no longer sets any status code; it just returns the body. This supersedes PR #975's `starting → 503` rule.
- `GET /api/health/live` — returns 200 with a minimal liveness body. No conditional, no dependency or service-state check. If the process is healthy enough to run the handler, it is live; if the event loop is wedged the handler can't run and the probe times out; if the process has exited the probe gets connection-refused.
- `GET /api/health/ready` — readiness: 200 when `get_system_status().status == "ok"`, else 503. This is the only one of the three with a status-code conditional.

**Shutdown model (decision) and fatal-exit observability (`src/hassette/core/core.py`, `service_watcher.py`, `server.py`).** Hassette's chosen model is **self-terminate on fatal failure, then rely on an external restart policy** — the same model Erlang/OTP uses at the node level and Docker/systemd/Kubernetes use via restart policies. This was deliberately re-examined against the prior art: keeping a process alive in a "dead" state (the alternative) produces a zombie that serves stale data and risks split-brain (e.g. Bus alive, Scheduler dead, half-broken automations firing from an undefined state). Since Hassette's PERMANENT services (`BusService`, `SchedulerService`) are foundational, a clean restart from a fresh process is the correct recovery, and every Hassette deployment already has an external restarter. Self-shutdown is *why* liveness can be a trivial "process responds" check: there is no state where Hassette is alive, answering HTTP, and should be externally killed — it kills itself.

Today the model is silent. Crashes converge on one reactive chokepoint: every `CRASHED` event triggers `ServiceWatcher.shutdown_if_crashed` (`service_watcher.py:449`, subscribed to `CRASHED` at `:569`), which calls `await self.hassette.shutdown()`. `CRASHED` is always terminal — recoverable failures emit `FAILED` (handled by `restart_service` at `:563`) and never reach here — so a single handler covers every crash-driven shutdown. (The inline `shutdown()` calls at `:196` and `:352` are redundant with it; idempotent, so harmless.) Separately, two startup-failure branches in `run_forever()` call `shutdown()` and return early: session-tracking init failure (`core.py:465`) and required services failing to start (`:488`). All of these return from `run_forever()` normally today, so `server.main` → `run.py` exits `0` — indistinguishable from an operator SIGTERM. The extension:

1. **One chokepoint for crash-driven fatals:** set a `Hassette` field (e.g. `self._fatal_shutdown_reason: str | None`, carrying the failing service and reason from the event) inside `shutdown_if_crashed`, before it tears down. This single site covers PERMANENT exhaustion and fatal-error crashes alike.
2. **Startup-failure fatals:** the two early-return branches in `run_forever()` (`:465`, `:488`) set the same fatal reason instead of returning silently.
3. **Surface it as a non-zero exit:** when the fatal reason is set, `run_forever()` raises `FatalError(reason)` rather than returning, reusing `run.py`'s existing `except FatalError → SystemExit(1)` (`run.py:52`). An operator SIGTERM (`request_shutdown`) leaves the flag unset → `run_forever()` returns normally → exit `0`. The exact resumption wiring — how `run_forever()`'s `shutdown_event.wait()` (`core.py:506`) unblocks after `shutdown_if_crashed` runs in a bus-handler task — is confirmed and wired during implementation; the contract is "fatal reason set ⇒ non-zero exit, after graceful teardown."
4. **Clear log:** emit a top-level ERROR/CRITICAL record at the fatal-exit point naming the service and reason, distinct from the normal "Hassette stopped." line.
5. **Telemetry already persists the crash:** `SessionManager.on_service_crashed` (`session_manager.py:93`, subscribed to `CRASHED` at `:52`) sets the session error and `finalize_session` (`:118`) writes it during the graceful teardown that precedes the non-zero exit, satisfying FR#9. The work is to confirm ordering and add a test.

**Models (`src/hassette/web/models.py`, `src/hassette/core/domain_models.py`).** `SystemStatusResponse` and `SystemStatus` keep their shape (no `checks` map in v1). A small liveness response model (`status`, `live: bool`) and readiness response model (`status`, `ready: bool`) are added for the two new routes. The `SystemHealthStatus` literal (`ok`/`degraded`/`starting`) is unchanged.

**CLI (`hassette status`).** Resolves the spirit of issue #976: because `/api/health` now returns 200 for `degraded`/`starting`, the CLI's `client.get()` no longer hits the `_handle_http_error` path for those states, so it prints the real status object instead of an error envelope. Verify the command's display logic handles all three states.

The `Resource` lifecycle, `RestartSpec`, and `ServiceWatcher`'s restart logic are read-only inputs here (validating prior-art Pattern 3/4, which Hassette already implements internally). The only new state is the WS service's `_ever_connected` latch and the `Hassette` fatal-shutdown flag; the watcher's restart decisions are unchanged.

## Replacement Targets

- `src/hassette/web/routes/health.py` — the PR #975 rule `if status_data.status == "starting": response.status_code = 503` is **removed outright**, not replaced by another conditional: `/api/health` returns 200 unconditionally while serving. The old single-endpoint readiness-coded behavior is superseded by the three-endpoint split.
- The implicit "`/api/health` is the readiness signal" contract is replaced by "`/api/health` is the always-200 aggregate; `/api/health/ready` is readiness; `/api/health/live` is liveness." Docs and any internal callers move accordingly.
- The silent `exit 0` on fatal shutdown is replaced by a non-zero exit via the existing `FatalError → SystemExit(1)` path. Implementers extend `run_forever()` to raise rather than return on a fatal-flagged shutdown.

## Convention Examples

### Health route handler (thin route, status code only where it belongs)

The convention to follow is the route *shape*: a thin handler that injects `RuntimeDep` (and `Response` only when a non-200 code is possible), reads runtime state, and returns a mapped response model. Of the three health routes, only readiness sets a status code — `/api/health` and `/api/health/live` just return their body at 200. The current `health.py` still has the `starting → 503` rule on `/api/health`; that conditional is the Replacement Target and is removed, not extended.

**Source:** `src/hassette/web/routes/health.py` (target shape — readiness is the only route with a conditional)

```python
@router.get("/health/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}})
async def get_ready(runtime: RuntimeDep, response: Response) -> ReadinessResponse:
    status_data = runtime.get_system_status()
    ready = status_data.status == "ok"
    if not ready:
        response.status_code = 503
    return readiness_response_from(status_data, ready=ready)


@router.get("/health/live", response_model=LivenessResponse)
async def get_live() -> LivenessResponse:
    # Liveness is the absence of a check: reaching this line means the loop can serve.
    return LivenessResponse(status="live")
```

### Status reduction over child services

**Source:** `src/hassette/core/runtime_query_service.py` (`get_system_status`)

```python
services = [
    ServiceInfo(
        name=child.class_name,
        status=child.status.value if hasattr(child, "status") else "unknown",
        ...
    )
    for child in self.hassette.children
    if hasattr(child, "status")
]
```

### Status unit test (mock-hassette fixture, direct method call)

**Source:** `tests/unit/core/test_runtime_query_service.py`

```python
def test_system_status_ws_connected_reflects_readiness(self, runtime: RuntimeQueryService) -> None:
    runtime.hassette.websocket_service.is_ready.return_value = False
    status = runtime.get_system_status()
    assert status.websocket_connected is False
```

DO drive status via the mocked `websocket_service.is_ready` / `ever_connected` on the `runtime` fixture. DON'T assert on log output to verify a state transition (project rule: no log-capture tests) — for the fatal-exit path, assert on the exit code and the persisted telemetry session row, not on log lines.

## Alternatives Considered

- **Latch-only, no endpoint split (the minimal hotfix alone).** Reshapes the status word but doesn't fix the loop on its own — a healthcheck still pointed at `/api/health` would keep restarting during an HA outage. Rejected as a complete solution; the latch ships *with* the split.
- **Endpoint split without the latch.** Stops the loop (liveness ignores HA), but leaves `degraded` unreachable during sustained outages — `StateProxy.on_disconnect()` revokes `proxy_ready` first — so a healthy-but-disconnected instance reports `starting` to the CLI and UI. Rejected: the latch is three lines and the difference between a true status word and a false one.
- **Computed `is_live()` predicate over service state** (`any PERMANENT service CRASHED/EXHAUSTED_DEAD`, as the research first sketched). Rejected after grounding it in the supervisor: a PERMANENT service is briefly `CRASHED` while *bouncing within budget*, so the predicate has a transient false-positive window; PERMANENT services never reach `EXHAUSTED_DEAD` (they route to `CRASHED → shutdown`); and the predicate misses a hung event loop entirely. Because Hassette self-shuts-down on real fatal failure, a "process responds" liveness is both simpler and *more* correct — it catches the hung-loop case the reduction misses.
- **Stay-alive-and-report-dead (zombie) model.** Keep the process running after a core service dies and report `unhealthy` via liveness for an external supervisor to kill. Rejected: produces a zombie serving stale data, risks split-brain among partially-alive services, and requires the fragile computed predicate above. Self-terminate + external restart (the chosen model) recovers from a clean state and matches OTP/systemd/Kubernetes practice.
- **Additive `/api/health` (keep PR #975 codes, only add `/live` + `/ready`).** Leaves `/api/health` as a foot-gun (a naive healthcheck pointed at it still loops). Rejected in favor of making `/api/health` always-200 while serving.
- **Add a fourth status literal `reconnecting`.** Ripples through models/mappers/frontend/tests/docs for no functional gain over `degraded` + the latch. Rejected.
- **IETF `health+json` per-dependency `checks` map now.** Better diagnostics, but expands payload + frontend + tests this round. Deferred to a follow-up.
- **Do nothing (rely on the deployment-side autoheal label removal already applied).** Stops the loop operationally but leaves the wrong signal in the product; every other user with autoheal hits the same trap. Rejected.

## Test Strategy

### Existing Tests to Adapt
- `tests/integration/web_api/test_endpoints.py` (`TestHealthEndpoints`, ~lines 30–46) — two assertions change: `test_health_returns_503_when_starting` (~line 39) must expect **200** (the handler no longer returns 503); `test_health_returns_200_when_degraded` (~line 30) currently reaches `degraded` via the default-`True` `state_proxy.is_ready` and must instead drive `websocket_service.ever_connected` (the `proxy_ready` fallback is gone). Add cases for `/api/health/live` (always 200) and `/api/health/ready` (200 only when `ok`).
- `create_hassette_stub` (test helper) — expose `ever_connected` as an explicit mock attribute (default `True`, matching the existing `is_ready=True` default) so health tests assert against a real value rather than MagicMock's auto-truthy attribute.
- `tests/unit/core/test_runtime_query_service.py` (`TestSystemStatus`) — extend with the latch cases (AC#1, AC#2). The existing `degraded` test must drive `websocket_service.ever_connected`; the `or proxy_ready` fallback is removed.
- WebSocket service unit tests — add coverage that `ever_connected` starts `False`, flips `True` on the `CONNECTED` transition, and stays `True` across a subsequent disconnect. (FR#1)
- `tests/unit/web/test_mappers.py` — verify no breakage after the liveness/readiness model additions; `SystemHealthStatus` literal unchanged.
- `tests/integration/web_api/test_dashboard_api.py` — mocks `get_system_status`; confirm new endpoints don't break dashboard wiring.
- `tests/system/test_cli_smoke.py` (~line 94) and `tests/unit/cli/test_commands_status.py` — confirm `hassette status` handles all three states without an error envelope (FR#8).

### New Test Coverage
- Unit (FR#1): on the WebSocket service, `ever_connected` starts false, the `CONNECTED` transition sets it, and it survives a later disconnect. (AC#1)
- Unit (FR#2): `get_system_status` returns `degraded` when the WS service reports `ever_connected` + not-ready, and `starting` when never connected. (AC#1, AC#2)
- Integration (FR#4, FR#5, FR#6): `/api/health` returns 200 for all three states; `/api/health/live` returns 200 regardless of WS/service state; `/api/health/ready` returns 200 only for `ok`. (AC#3, AC#4, AC#5, AC#6, AC#9)
- Integration/unit (FR#7): a fatal-flagged shutdown (simulate a PERMANENT service reaching the watcher's exhaustion path) causes `run_forever()` to raise `FatalError` / the entry path to exit non-zero; a SIGTERM/operator shutdown exits 0. (AC#10, AC#11)
- Integration (FR#9): after a `CRASHED` event for a PERMANENT service, the session row in the telemetry DB carries the failure status, written before teardown completes. Assert on the persisted row, not on logs. (AC#12)
- Schema/build (AC#7): regenerate schemas/types; frontend build passes.

### Tests to Remove
No tests to remove — the `starting → 503` assertion is adapted (changed expectation), not deleted.

## Documentation Updates

- `docs/pages/cli/configuration.md` — update the health-check example to point restart automation at `/api/health/live`; remove the `status == "starting"` 503 expectation; note that a fatal exit is non-zero (so `Restart=on-failure` reacts) while HA outages stay 200.
- `docs/pages/getting-started/docker/troubleshooting.md` — add a "Hassette restarts whenever HA goes down" entry pointing at the liveness endpoint + the autoheal guidance.
- `docs/pages/core-concepts/database-telemetry.md` (status table, ~lines 79–80) — reflect that `/api/health` is always 200 while serving, and that a fatal crash is recorded to the session before exit.
- New/extended health-endpoint reference describing `/api/health`, `/api/health/live`, `/api/health/ready`, their codes, the self-shutdown-on-fatal behavior (non-zero exit), and which signal to use for restart vs routing (the user-facing guidance peer frameworks lack).
- `CHANGELOG.md` is release-please-managed — convey user-facing intent via the PR title/commit type (`feat`), not a manual edit.

## Impact

### Changed Files
- `src/hassette/web/routes/health.py` — `/api/health` becomes always-200 (remove the `starting → 503` conditional); add `/api/health/live` (unconditional 200) and `/api/health/ready` (200/503) (cross-cutting: external contract).
- `src/hassette/core/websocket_service.py` — `_ever_connected` attribute, set in `_set_connection_state()` on the `CONNECTED` transition; `ever_connected` property.
- `src/hassette/core/runtime_query_service.py` — status reduction reads `websocket_service.ever_connected` (drop the `proxy_ready` fallback). No `is_live()` predicate.
- `src/hassette/core/core.py` — `_fatal_shutdown_reason` flag; the two startup-failure branches (`:465`, `:488`) set it; `run_forever()` raises `FatalError` instead of returning when it is set; top-level fatal-exit log line.
- `src/hassette/core/service_watcher.py` — `shutdown_if_crashed` (`:449`, the universal `CRASHED` reaction) sets the fatal reason before tearing down (restart/budget decisions unchanged).
- `src/hassette/core/session_manager.py` — verify (not rebuild) that the crash is finalized to the session before teardown; add coverage.
- `src/hassette/web/models.py` — liveness/readiness response models (additive); `SystemHealthStatus` unchanged.
- `src/hassette/web/mappers.py` — mapper(s) for the new response models.
- `openapi.json`, `frontend/src/api/generated-types.ts`, `ws-schema.json`/`ws-types.ts` — regenerated.
- Tests and docs per the sections above.

<!-- Gap check 2026-06-06: reverse-dependency sweep of /api/health, get_system_status, SystemStatusResponse consumers. 1 awareness note + 2 verified-no-change: web/routes/ws.py:100 (get_system_status broadcast consumer — shape unchanged, behavior improves) → T01 Focus; tests/system/conftest.py:304 wait_for_web_server already accepts 200|503 → no change (T02 Focus); frontend /api/health mocks (handlers.ts:177, diagnostics.test.tsx) mock unchanged shape, none assert starting→503 → T02 Focus verifies frontend build/tests pass. No unlisted consumer requires a code change. -->


### Behavioral Invariants
- The `ok`/`degraded`/`starting` status literal set and `SystemStatusResponse` body shape do not change — the UI and CLI consumers keep working.
- `ok` is still computed from current WS connectivity (FR#3).
- The restart/budget supervision logic (restart types, intensity/period, restart-vs-give-up) is untouched; only the fatal-shutdown *exit signaling* changes.
- A clean (SIGTERM/operator) shutdown still exits 0 — only fatal shutdowns become non-zero.
- The web UI continues to render a single status; no UI contract change.

### Blast Radius
- External: anything polling `/api/health` sees `starting` flip from 503 to 200 (the intended fix) — a deliberate, documented change. Restart tooling should move to `/api/health/live` and/or rely on the now-non-zero fatal exit.
- External: supervisors using systemd `Restart=on-failure` will now correctly restart after a fatal crash (previously masked by exit 0). `restart: unless-stopped` behavior is unchanged (it restarts regardless of code).
- Internal: `hassette status` CLI behavior improves for non-`ok` states (resolves #976's spirit).
- Deployment (separate repo): re-enable the `autoheal` label and point the Docker healthcheck at `/api/health/live`.

## Open Questions

None blocking. Two tracked follow-ups (to be filed as issues, not resolved here):
1. Monitoring UI: surface liveness vs readiness as distinct indicators.
2. Payload: adopt an IETF `health+json`-style per-dependency `checks` map.
