# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: `live_server_ws_inject` fixture still duplicates the uvicorn bring-up/teardown logic extracted into `uvicorn_server.py`

Status: open
Run: 54
Source: T07
Reason not fixed now: needs-decision
Observed in: T07
Affected files:
- tests/e2e/conftest.py:406-480
- src/hassette/test_utils/uvicorn_server.py:20-72

Issue:
T07's fixer passes extracted the shared live-uvicorn-server bring-up/teardown sequence
(free-port bind, `uvicorn.Config`/`uvicorn.Server` construction, daemon-thread start,
connection-poll loop, `should_exit`/`thread.join` teardown) into
`src/hassette/test_utils/uvicorn_server.py` (`get_free_port`, `start_uvicorn_server`,
`stop_uvicorn_server`), and migrated three of the four `tests/e2e/conftest.py` fixtures that
previously hand-rolled it (`live_server`, `live_server_starting`, `live_server_ws`). The fourth,
`live_server_ws_inject` (lines 406-480), was left un-migrated: it still inlines the identical
free-port + `uvicorn.Config`/`Server` + thread-start + poll-loop (lines 422-460, byte-for-byte the
same poll logic as `start_uvicorn_server`) and the identical stop sequence (lines 474-478,
byte-for-byte the same as `stop_uvicorn_server`). A future change to the poll timeout, the
connection-refused backoff, or the startup error message — all now centralized in
`uvicorn_server.py` — will silently miss this fixture, and the two implementations can drift
independently. Both the code reviewer (MEDIUM, iteration N) and the integration reviewer (HIGH,
iteration 3 final) independently flagged this as the same underlying gap.

Why deferred:
This fixture also patches `server.startup` to capture the server's running event loop before
starting the thread (`broadcast_sync`'s `asyncio.run_coroutine_threadsafe` needs a live loop
reference), which `start_uvicorn_server()` has no hook for today — that need is a legitimate
reason it couldn't call the shared helper as-is. Closing the gap requires an actual API decision
between two shapes reviewers proposed (add an `on_startup: Callable | None` hook to
`start_uvicorn_server()` that's invoked from inside the patched `server.startup`, vs. extract just
the "wait until accepting connections" poll loop into its own reusable helper e.g.
`wait_for_server_ready(port)` that both `start_uvicorn_server()` and this fixture call), and the
findings-fix loop's fixer-pass budget for T07 is exhausted. This is test-infrastructure
duplication only — the production auth-check code in `web/routes/ws.py` this task actually
implements is unaffected and independently verified correct by both reviewers.

Recommended follow-up:
Pick one of the two shapes above, apply it to `start_uvicorn_server()`, and migrate
`live_server_ws_inject` to call the shared helper the same way the other three fixtures do —
removing the duplicated poll-loop and stop-sequence code from `tests/e2e/conftest.py`.

Acceptance criteria:
- `live_server_ws_inject` no longer hand-rolls `uvicorn.Config`/`Server` construction, the
  connection-poll loop, or the stop sequence — it calls `start_uvicorn_server()` /
  `stop_uvicorn_server()` (or their extended signatures) like `live_server_ws`.
- The event-loop capture (`broadcast_sync`'s requirement) still works via whichever hook
  mechanism is added.
- No behavior change to the `broadcast_sync` API or any test that depends on this fixture.
