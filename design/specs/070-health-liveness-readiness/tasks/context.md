# Context: Health Endpoints, Status Taxonomy, and Fatal-Exit Observability

## Problem & Motivation

When Home Assistant goes down, a running Hassette instance enters an external reboot loop. A single `/api/health` endpoint conflates liveness ("restart me?") with readiness ("connected to HA?"), and the status taxonomy can't tell "still booting" (`starting`) apart from "booted fine, then lost HA." A dropped WebSocket makes `get_system_status()` report `starting` → HTTP 503 → a Docker healthcheck driving `willfarrell/autoheal` restarts the container → still can't reach HA → loops. This is the textbook liveness anti-pattern (a dependency check inside the restart signal). A second gap: Hassette already self-terminates on a genuinely fatal failure, but exits `0` whether the shutdown was a clean SIGTERM or a fatal crash, so `systemd Restart=on-failure` can't tell them apart.

## Visual Artifacts

None.

## Key Decisions

1. **Ever-connected latch lives on the WebSocket service**, set inside `_set_connection_state()` at the `CONNECTED` transition (the single chokepoint), exposed as a read-only `ever_connected` property. `RuntimeQueryService.get_system_status()` reads it to report `degraded` (latched + not connected) vs `starting` (never connected). The `proxy_ready` fallback is removed.
2. **Three endpoints, split by question.** `/api/health` = always-200 aggregate (the handler sets no status code); `/api/health/live` = liveness; `/api/health/ready` = readiness (200 only when `ok`, else 503).
3. **Liveness is "the process can answer"** — no `is_live()` predicate, no dependency check, no service-state reduction. Rationale: Hassette self-shuts-down on fatal failure, so a responsive process is by definition live; a hung event loop fails the probe naturally (the async handler can't run); HA-down never touches it. A computed predicate over service state was rejected (transient false-positive window on a bouncing service, misses the hung-loop case, more complex).
4. **Self-shutdown-on-fatal is the deliberate, validated model** (matches OTP/systemd/Kubernetes). Not being replaced — only made observable.
5. **Fatal-exit observability:** a failure-driven shutdown exits non-zero (reusing `run.py`'s existing `FatalError → SystemExit(1)`); a clean SIGTERM exits 0. The crash is already persisted to the telemetry DB via `SessionManager.on_service_crashed` → `finalize_session` — this is confirmed and test-covered, not rebuilt.
6. **No fourth status literal.** The `ok`/`degraded`/`starting` triple plus the latch is sufficient. `SystemStatusResponse` body shape is unchanged.

## Constraints & Anti-Patterns

- **Liveness must reflect only whether the process can answer.** No HA-connection check, no per-service status reduction. The moment liveness consults a dependency or a service status, it can flip on a recoverable condition — the restart-storm anti-pattern this work eliminates.
- The latch is one-way for the process lifetime; never cleared on disconnect.
- Do not add a fourth status literal (`reconnecting` etc.).
- The fatal-exit path must run the normal graceful teardown (telemetry flush, session finalize) **before** the non-zero exit.
- Do not change the restart/budget supervision logic (restart types, intensity/period, restart-vs-give-up). Only the fatal-shutdown *exit signaling* changes.
- **No log-capture tests.** Verify the fatal path via exit code and the persisted telemetry session row, never by asserting on log output.
- `CRASHED` is always terminal (recoverable failures emit `FAILED`, handled by `restart_service`); every `CRASHED` triggers `ServiceWatcher.shutdown_if_crashed`.

## Design Doc References

- `## Problem` — the reboot loop and the silent-exit gap.
- `## Functional Requirements` / `## Acceptance Criteria` — FR#1–FR#9, AC#1–AC#12.
- `## Architecture` — Latch, Status taxonomy, Endpoints, Shutdown model & fatal-exit observability, Models, CLI.
- `## Edge Cases` — disconnect, exhaustion, fatal error, hung loop, clean vs fatal exit.
- `## Test Strategy` — existing tests to adapt, new coverage, stub `ever_connected`.
- `## Impact` — changed files, behavioral invariants, blast radius.

## Convention Examples

### Health route handler (thin route, status code only where it belongs)

Only readiness sets a status code; `/api/health` and `/api/health/live` return their body at 200. (Target shape — the current `health.py` still has the `starting → 503` rule, which is removed.)

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

### Status unit test (mock-hassette fixture, direct method call)

```python
def test_system_status_ws_connected_reflects_readiness(self, runtime: RuntimeQueryService) -> None:
    runtime.hassette.websocket_service.is_ready.return_value = False
    status = runtime.get_system_status()
    assert status.websocket_connected is False
```

DO drive status via the mocked `websocket_service.is_ready` / `ever_connected` on the `runtime` fixture. DON'T assert on log output to verify a state transition. For the fatal-exit path, assert on the exit code and the persisted telemetry session row, not on logs.
