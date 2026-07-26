---
task_id: "T03"
title: "Fix system status and add integration tests"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#6", "AC#1", "AC#2", "AC#3", "AC#6"]
---

## Summary

RuntimeQueryService's `get_system_status()` uses `ws.is_ready()` as a proxy for "HA connected." With T01 making `is_ready()` always True, this must switch to `ws.is_connected`. Then add integration tests that prove the full stack works: start hassette with WS mocked to never connect, verify the web server starts, apps bootstrap, and the health endpoint returns the correct degraded status. Run the full test suite and lint to confirm no regressions.

## Target Files

- modify: `src/hassette/core/runtime_query_service.py`
- modify: `CLAUDE.md`
- create: `tests/integration/test_dashboard_without_ha.py`
- read: `design/specs/018-dashboard-without-ha/design.md`
- read: `src/hassette/test_utils/web_mocks.py`

## Prompt

Make two changes:

1. **`src/hassette/core/runtime_query_service.py`** (line 258): Change `ws_connected = ws.is_ready()` to `ws_connected = ws.is_connected`. The `is_connected` property (defined at `websocket_service.py:213`) checks `self._connection_state == ConnectionState.CONNECTED`. The existing logic at lines 282-287 uses `ws_connected` and `ws.has_ever_connected` to derive the three-way status ("ok" / "degraded" / "starting") — this continues to work correctly with the switch.

2. **Create `tests/integration/test_dashboard_without_ha.py`** with these integration tests:

   **`test_webapi_ready_without_ha_connection`** (AC#3): Start hassette with WebsocketService mocked so that `serve()` never connects (no WebSocket handshake). Verify:
   - WebApiService reaches ready state
   - Apps bootstrap (check `app_handler.registry.get_full_snapshot()` returns manifests)
   - An HTTP GET to `/api/health` returns 200

   Use the `HassetteHarness` pattern from `tests/integration/`. The key is mocking WS's `serve()` to be a coroutine that never completes (e.g., awaits an `asyncio.Event` that's never set), so WS starts and calls `mark_ready()` via `on_initialize()` (from T01) but never reaches CONNECTED state.

   **`test_health_shows_starting_when_ws_never_connected`** (AC#6): Same setup as above. Query the system status (via `RuntimeQueryService.get_system_status()` or the `/api/health` endpoint) and assert `status == "starting"`. Also assert `websocket_connected == False`.

   **`test_full_suite_no_regressions`** (AC#1, AC#2): This is not a test to write — it's a verification step. After all code changes, run `ptest -n 4` to confirm the full test suite passes, and `prek -a` to confirm lint/type checks pass.

3. **Update `CLAUDE.md`** Architecture → Resource Hierarchy section: Note that StateProxy and ApiResource no longer depend on WebsocketService, and that WebsocketService marks ready unconditionally (lifecycle readiness ≠ HA connected). Update the `depends_on` references for StateProxy, ApiResource, and AppHandler.

   For the integration tests, follow existing patterns in `tests/integration/`:
   - Use `pytest.mark.asyncio` decorator
   - Use `make_mock_hassette()` or `HassetteHarness` depending on what level of wiring is needed
   - For the HTTP test, use `create_hassette_stub()` from `src/hassette/test_utils/web_mocks.py` or the HTTPX test client pattern from `tests/integration/web_api/`

## Focus

- `web_mocks.py` (line 190-191) already sets both `is_ready.return_value` and `has_ever_connected` on the WS mock. When creating stub-based tests, the mock is pre-wired for the new RQS logic.
- `RuntimeQueryService.get_system_status()` at line 258 is the ONLY place in the codebase that uses `ws.is_ready()` to check connection status — confirmed by grep. The switch to `ws.is_connected` is the only code change needed.
- The existing `has_ever_connected` check at lines 282-287 already correctly distinguishes "starting" from "degraded." The switch from `is_ready()` to `is_connected` just fixes the input to that logic.
- For the integration test, look at how `tests/integration/web_api/` tests set up the HTTPX test client against the FastAPI app. The pattern typically involves `create_hassette_stub()` to build a mock hassette, then mounting the router.
- `tests/integration/test_core.py:158` tests phased startup and wave ordering. The depends_on changes from T02 may affect wave composition. Verify this test still passes.
- Run verification commands: `ptest -n 4` for the test suite, `prek -a` for lint/type checks.

## Verify

- [ ] FR#1: WebApiService starts and serves HTTP responses when WebsocketService has not connected to HA — confirmed by the integration test.
- [ ] FR#6: System status endpoint reports "starting" when WS has never connected, confirmed by the integration test.
- [ ] AC#1: `ptest -n 4` passes with 0 failures.
- [ ] AC#2: `prek -a` passes with no errors.
- [ ] AC#3: Integration test starts hassette with WS mocked to never connect and verifies WebApiService is ready and HTTP 200 on `/api/health`.
- [ ] AC#6: Integration test verifies `/api/health` returns `status: "starting"` when WS has never connected.
