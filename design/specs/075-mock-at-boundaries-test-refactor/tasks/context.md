# Context: Mock at boundaries in core service tests (issue #1036)

## Problem & Motivation
Several core tests patch Hassette's own internal methods instead of mocking only true system boundaries (HA API, the aiohttp websocket, time, the DB). When a test overwrites the very method whose behavior it claims to verify — e.g. a reconnect-cache test patching `StateProxy.load_cache`, or a cleanup test patching `WebsocketService.partial_cleanup` — that logic never runs, so the test passes whether or not the logic is correct. This gives false regression confidence in websocket reconnection, state cache, and app lifecycle: exactly the subsystems where "it seemed to work" is least trustworthy. Issue #1036 named five spots; an audit found the pattern across seven files.

## Visual Artifacts
None.

## Key Decisions
1. **The unit of analysis is the method-under-test (MUT), not "any patch on a real object."** The violation is patching the method (or path) a test asserts about. Stubbing a *collaborator* of the MUT is legitimate and often correct.
2. **Dual-role symbols.** `partial_cleanup`, `mark_ready`, `_emit_readiness_event` are MUTs in dedicated tests (convert to boundary mocks) but collaborators in `serve()` / `start_recv_and_subscribe` tests (keep + annotate). Classification is per-test, by MUT.
3. **`serve()`-loop tests are NOT converted.** Early-drop/reconnect tests stub `make_connection` as a collaborator of `serve()`. Driving them through a fake-ws recv sequence would hang (the subscribe Future needs a real recv frame; `task_bucket.spawn` needs a real task). Keep the stubs, add `# boundary-exempt: collaborator of <MUT>` annotations.
4. **`build_fake_ws()` stays a thin aiohttp stub.** Do NOT enrich it to script the HA auth/recv protocol — that makes it a second protocol implementation (change amplification). Stub `authenticate`/`subscribe_events` as collaborators instead. The helper moves to `src/hassette/test_utils/` so unit tests can import it.
5. **A CI guard enforces the lesson structurally.** `tools/check_internal_patches.py` flags MUT patches in the in-scope files unless annotated `# boundary-exempt:`. Mirrors the existing `tools/frontend/check_*.py` guards. Lands as the capstone (after conversions), because a guard landing mid-conversion would fail CI on not-yet-converted patches.
6. **`get_states_raw` is the HA REST boundary, left as-is** — not a violation; #1036 names it as the injection point.
7. **AC#4 is a hard merge gate:** system + e2e CI jobs must be green on the PR branch (these exercise the real aiohttp/HA boundaries the unit tests mock).

## Constraints & Anti-Patterns
- **No production-code behavior changes.** The only `src/` edit is the additive relocation of `build_fake_ws()` into `test_utils/`. If a test can't be redriven without a source change, that's a PR-review discussion, not a silent `src/` edit.
- **Keep the pin green at every step** — each file's tests pass after that file is converted, before moving on.
- **Never weaken an assertion** to make a boundary version pass (e.g. call-count → presence). `mark_not_ready` idempotency-guard spies → count emitted not-ready events, not a bare `is_ready()` check.
- **`build_fake_ws()` carries no HA protocol knowledge.**
- **Out of scope (do NOT touch):** Cluster D (`bus_service.add_listener` / `mock_add_listener` helper), the scheduler `__new__` doubles in `test_scheduler_service_reschedule.py`, `get_states_raw` patches, and the Cluster E/F files (`test_scheduler_mode.py`, `test_service_watcher.py`, `test_duration_hold.py`, `test_bus_contract.py`, `test_database_service.py`).

## Design Doc References
- `## Architecture → Guard scope and the dual-role principle` — the canonical prohibited-symbol enumeration and the per-test MUT classification rule.
- `## Architecture → Cluster A/B/C` — per-cluster conversion approach and sequencing.
- `## Edge Cases` — serve()/start_recv hang risk, auth handshake, early-drop two-tier retry, concurrency gating, mark_not_ready precision.
- `## Replacement Targets` — A1 (convert) vs A2 (annotate) symbol classification.
- `## Convention Examples` — the target boundary-mock form, the legitimate A2 collaborator-stub form, the startup-race gating pattern.
- `## Acceptance Criteria` — AC#1–7, including the hard system+e2e gate (AC#4) and the sanity spot-check (AC#5).

## Convention Examples

### Boundary-mock pattern for connection-method MUTs (A1 — the model to copy)
Target form for `tests/integration/test_websocket_service.py` (`test_connect_ws_sets_ws_and_authenticates`) — current test has the same shape but the `authenticate` stub is not yet annotated; the annotation is part of this work:

```python
async def test_connect_ws_sets_ws_and_authenticates(websocket_service: WebsocketService) -> None:
    """connect_ws sets self._ws and calls authenticate."""
    fake_ws = build_fake_ws()
    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=fake_ws)

    websocket_service.authenticate = AsyncMock()  # boundary-exempt: collaborator of connect_ws

    await websocket_service.connect_ws(fake_session)   # REAL connect_ws (the MUT) runs

    assert websocket_service._ws is fake_ws
    websocket_service.authenticate.assert_awaited_once()
```

DO mock `fake_session.ws_connect` (the aiohttp boundary) and run the real MUT. DON'T patch `connect_ws` itself when it is the MUT.

### Legitimate collaborator stub in an orchestration-MUT test (A2 — keep + annotate, do NOT convert)
`tests/integration/test_websocket_service.py` — `test_early_drop_retries_and_succeeds` (~lines 558–618):

```python
# serve() is the MUT; make_connection is its collaborator.
async def fake_make_connection(_session):
    ...
websocket_service.make_connection = fake_make_connection  # boundary-exempt: collaborator of serve()
```

This is correct, not the anti-pattern. The test verifies `serve()`'s outer retry loop by counting `make_connection` calls. Do NOT drive it via a fake-ws recv sequence (it would hang). Add the annotation; the CI guard then accepts it.

### Startup-race / gating pattern for StateProxy ordering assertions
```python
gate = asyncio.Event()
mock_boundary.side_effect = lambda *_: gate.wait()   # gate the HA boundary, not load_cache
task = asyncio.create_task(state_proxy.on_reconnect())
await asyncio.sleep(0)
assert not task.done()          # confirm the gate actually blocks before setting it
gate.set()
await task
```

## Prohibited-symbol enumeration (the CI guard's input)
```
WebsocketService: make_connection, connect_ws, dispatch, respond_if_necessary,
                  partial_cleanup, authenticate, mark_ready,
                  _emit_readiness_event, subscribe_events,
                  send_connection_established_event
StateProxy:       load_cache, subscribe_to_events, mark_not_ready,
                  _emit_readiness_event
Lifecycle:        start_app, stop_app, reload_app, resolve_only_app,
                  handle_crash, detect_changes, refresh_config
```
`task_bucket.spawn` is deliberately excluded — it is a method on a different object, not on the service/proxy/lifecycle under guard.
