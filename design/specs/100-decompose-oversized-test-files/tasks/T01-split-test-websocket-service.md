---
task_id: "T01"
title: "Split tests/integration/test_websocket_service.py into a websocket/ subpackage"
status: "done"
depends_on: []
implements: ["FR#1", "AC#1"]
---

## Target Files

- delete: `tests/integration/test_websocket_service.py`
- create: `tests/integration/websocket/__init__.py`
- create: `tests/integration/websocket/conftest.py`
- create: `tests/integration/websocket/test_connection.py`
- create: `tests/integration/websocket/test_dispatch.py`
- create: `tests/integration/websocket/test_reconnect.py`
- create: `tests/integration/websocket/test_subscribe_events_retry.py`

## Prompt

`tests/integration/test_websocket_service.py` is 1200 lines and exceeds the repo's 800-line file
threshold (closes issue #1578). Split it into a new `tests/integration/websocket/` subpackage —
this directory currently has no sibling-file split convention (unlike `tests/integration/bus/`,
`tests/integration/web_api/`, `tests/integration/telemetry/`, which are already organized as
subpackages), so this task establishes that pattern for websocket tests.

Steps:

1. Read the full current file: `tests/integration/test_websocket_service.py`. Identify the shared
   `websocket_service` fixture (and any other shared fixtures/helpers used across multiple test
   classes/functions) — these move to a new `tests/integration/websocket/conftest.py`.
2. Create `tests/integration/websocket/__init__.py` (empty file, makes it a package if needed —
   check whether sibling subpackages like `tests/integration/bus/` have an `__init__.py`; match
   whatever convention they use, including if they use none).
3. Create `tests/integration/websocket/conftest.py` holding the shared `websocket_service` fixture
   and any other cross-file shared setup.
4. Split the remaining content into topic files by the natural groupings already visible in the
   test names/classes:
   - `test_connection.py` — connection/auth tests (message id/connection-state helpers,
     `authenticate`, `raw_recv`, `connect_ws`, `start_recv_and_subscribe`)
   - `test_dispatch.py` — `send_json`/`send_and_wait`/dispatch tests
   - `test_reconnect.py` — `disconnect`, `partial_cleanup`, the `FailingConnection` helper class,
     early-drop/reconnect retry tests (~lines 723-1128 in the original file), and
     `send_connection_lost_event`
   - `test_subscribe_events_retry.py` — the `TestSubscribeEventsRetry` class (~line 1130 onward)
   Adjust the exact split boundaries as needed once you've read the file — the goal is that each
   resulting file is well under 800 lines and each file's tests are thematically coherent, not
   that the boundaries match these line numbers exactly.
5. Every moved test must keep its exact assertions and setup — this is a pure move, not a rewrite.
   Preserve all necessary imports in each new file.
6. Delete the original `tests/integration/test_websocket_service.py` once all its content has been
   redistributed.
7. Give each new file a short module docstring naming the sibling files it complements (see the
   pattern in `tests/unit/core/test_app_lifecycle_service_coverage.py` for the style — 3-5 lines,
   not a long essay).

## Verify

- [ ] FR#1: `tests/integration/test_websocket_service.py` no longer exists; `tests/integration/websocket/` contains `__init__.py`, `conftest.py`, and topic-split test files covering connection/auth, send/dispatch, disconnect/reconnect-retry, and `TestSubscribeEventsRetry`.
- [ ] AC#1: `uv run pytest tests/integration/websocket/ -v` passes. Test count (`--collect-only -q` line count) matches what `git show HEAD:tests/integration/test_websocket_service.py | uv run pytest --collect-only -q -` reported before the split. Every file in `tests/integration/websocket/` is under 800 lines (`wc -l tests/integration/websocket/*.py`).
