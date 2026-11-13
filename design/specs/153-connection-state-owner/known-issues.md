# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: The set-before-report order in the RUNNING gate is unpinned

Status: open
Recorded: 2026-11-13 (4091)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/websocket_service.py
- tests/unit/core/test_ws_connection_state.py

Issue:
`wait_for_core_running` sets WAITING_FOR_CORE before awaiting `report_connection_status`, so anything the readiness event wakes reads the new state. The unit test stubs `report_connection_status`, so swapping the two lines fails no test.

Why deferred:
Nothing woken by the readiness event reads `connection_state` today, so a swap has no consumer to break. The user accepted it as a rare-case limitation at the ship-time challenge.

Recommended follow-up:
When a readiness-event consumer starts reading `connection_state` (#3678 or #4101), make the `report_connection_status` stub record the state at call time and assert WAITING_FOR_CORE.

Acceptance criteria:
- A test fails if `report_connection_status` is awaited before the WAITING_FOR_CORE set.

## KI-002: The single-writer rule for connection state is enforced only by review

Status: open
Recorded: 2026-11-13 (4091)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/websocket_service.py
- src/hassette/core/websocket_io.py

Issue:
`set_connection_state` is the only writer of `_connection_state` under `src/` after `__init__` (D9), but the attribute is a plain field. A future direct write under `src/` would skip the ever-connected latch, the connected-event and generation clear, and the transition check, and nothing would fail.

Why deferred:
The rule holds today and has never been broken, and HA core's `set_state` enforces nothing either. Review checks it through the "Connection State Has One Writer" question in `src/hassette/core/REVIEW.md`. Per encode-lessons, a mechanism waits until the instruction fails. The user accepted it as a rare-case limitation at the ship-time challenge.

Recommended follow-up:
If a direct `src/` writer ever lands, add a test that greps `src/` for `_connection_state\s*=` and allows only `__init__` and `set_connection_state`.

Acceptance criteria:
- A direct assignment to `_connection_state` under `src/` outside the two allowed sites fails CI.
