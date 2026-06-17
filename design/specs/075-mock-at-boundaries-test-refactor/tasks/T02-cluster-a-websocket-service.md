---
task_id: "T02"
title: "Cluster A: convert WebsocketService MUT patches, annotate collaborators"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#8", "AC#5"]
---

## Summary
Convert the WebsocketService tests across three files so that connection-method tests run the real method against a fake aiohttp websocket (mocking only `ws_connect`), and orchestration tests (`serve()` loop, `start_recv_and_subscribe()`) keep their collaborator stubs with explicit `# boundary-exempt:` annotations. This is the largest cluster and the core of the refactor: it classifies each patch per method-under-test (MUT), converting genuine MUT patches and annotating legitimate collaborator stubs.

## Target Files
- modify: `tests/integration/test_websocket_service.py` — convert A1 connection-method MUT patches; annotate A2 collaborator stubs
- modify: `tests/unit/core/test_ws_connection_state.py` — classify per MUT; convert/annotate
- modify: `tests/unit/core/test_websocket_readiness_events.py` — mostly A2 isolation tests (annotate); convert any true MUT patches
- read: `src/hassette/core/websocket_service.py` — the code under test (connection/dispatch/cleanup/serve logic)
- read: `src/hassette/test_utils/ws_mocks.py` — `build_fake_ws()` (relocated in T01)
- read: `design/specs/075-mock-at-boundaries-test-refactor/tasks/context.md`
- read: `design/specs/075-mock-at-boundaries-test-refactor/design.md`

## Prompt
For EACH patch/reassignment of a prohibited WebsocketService symbol in the three files, first determine the **method under test (MUT)** for that test, then classify and act:

**A1 — the MUT is a connection-level method** (`connect_ws`, `dispatch`, `respond_if_necessary`, `partial_cleanup` in a dedicated cleanup test, `authenticate` in an auth test), OR `mark_ready`/`_emit_readiness_event` is patched to *short-circuit readiness* (prevent the real method running so the test can assume a ready state):
- Run the real MUT. Build a `fake_session = MagicMock()` with `fake_session.ws_connect = AsyncMock(return_value=build_fake_ws())`, and drive the real `connect_ws`/`serve`/MUT path.
- Stub only the MUT's collaborators (e.g. `authenticate` when testing `connect_ws`), each annotated `# boundary-exempt: collaborator of <MUT>`.
- Assert readiness/connection-established outcomes by subscribing a real bus listener and checking the emitted event — NOT by patching the emit methods.
- Follow the Convention Examples in context.md exactly (the `test_connect_ws_sets_ws_and_authenticates` shape).

**A2 — the MUT is the `serve()` reconnect loop or `start_recv_and_subscribe()`:**
- The stubs of `make_connection`, `partial_cleanup`, `subscribe_events`, `send_connection_established_event`, `task_bucket.spawn`, and call-count stubs of `mark_ready`/`_emit_readiness_event` are COLLABORATORS. Keep them. Add `# boundary-exempt: collaborator of <MUT>` to each.
- Do NOT attempt to drive these through a fake-ws recv sequence — it will hang (the subscribe Future needs a real recv frame; `task_bucket.spawn` needs a real task). See design.md `## Edge Cases`.
- Where the test asserts a side effect, route the assertion through the bus (e.g. `hassette.send_event` capture) where it isn't already.

**Early-drop / reconnect tests** (`test_early_drop_*`, `test_service_status_stays_running_during_early_drop`, reconnect-sequence tests) are A2: `make_connection` is a collaborator of `serve()`. Annotate, do not convert. They verify the OUTER `serve()` `while True:` loop (`websocket_service.py:240`), distinct from `make_connection`'s inner `@retry` on `ws_connect` failure (~380–395).

**`build_fake_ws()` stays thin.** Do not add HA protocol/handshake/recv scripting. For serve()/connect-driven tests where `authenticate` is a collaborator, stub `authenticate` (as the existing model test does).

After each file, run it and confirm green before moving to the next. Then run the full websocket test set.

## Focus
- `make_connection(session)` → `connect_ws(session)` → `session.ws_connect(...)` at `websocket_service.py:303`; the `@retry` inner function is ~380–395; the outer early-drop loop is at line 240.
- `test_websocket_service.py` already contains the correct A1 pattern (`fake_session.ws_connect = AsyncMock(return_value=fake_ws)` in `test_connect_ws_sets_ws_and_authenticates`) — copy it. Known A1-vs-A2 sites: `partial_cleanup` is the MUT in `test_partial_cleanup_*` (convert) but a collaborator in the early-drop tests (annotate, ~lines 601/642/677/777/865).
- `test_websocket_readiness_events.py`: `test_mark_ready_after_connect_emits_event` (~line 131) runs the real `start_recv_and_subscribe()` and stubs `task_bucket.spawn`/`send_connection_established_event`/`subscribe_events` — this is A2; keep + annotate. Its `mark_ready` call-count assertion is a collaborator stub (A2), not an A1 short-circuit.
- The dual-role symbols (`partial_cleanup`, `mark_ready`, `_emit_readiness_event`) appear in BOTH categories across these files — classify each occurrence by its test's MUT (context.md Key Decision 2).
- This task's WebsocketService changes are the core-service edits that trigger the system + e2e merge gate (CLAUDE.md core-change rule). The authoritative branch-level verification of that gate (AC#4) lives in the capstone task T05, after all conversions land — not here, because a branch-wide CI gate can't be satisfied before T03/T04 exist. Still, sanity-run the WS-relevant system/e2e behavior if feasible.
- Reverse-dependency gap check found no production callers affected (test-only).

## Verify
- [ ] FR#1: In all three files, no test reassigns or `patch.object`-patches its own MUT; mocks are limited to `ws_connect`/time boundaries and annotated MUT collaborators.
- [ ] FR#2: Connection-method tests (`connect_ws`/`dispatch`/`respond_if_necessary`/dedicated `partial_cleanup`/`authenticate`) run the real method against `build_fake_ws()` and assert readiness via emitted bus events, not by patching emit methods.
- [ ] FR#3: `serve()`/`start_recv_and_subscribe` tests retain their collaborator stubs (`make_connection`, `partial_cleanup`, `subscribe_events`, `send_connection_established_event`, `task_bucket.spawn`, `mark_ready`/`_emit_readiness_event` call-count stubs), each carrying a `# boundary-exempt: collaborator of <MUT>` annotation, and none is converted to a fake-ws recv sequence.
- [ ] FR#8: Every changed test asserts an observable outcome (returned value, emitted event, recorded call, or public state); no mock is configured but never asserted on.
- [ ] AC#5: Breaking `WebsocketService.partial_cleanup` (a representative method) causes at least one in-scope WebsocketService test to fail — demonstrating the real method now runs.
