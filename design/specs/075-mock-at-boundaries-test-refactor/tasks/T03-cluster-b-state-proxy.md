---
task_id: "T03"
title: "Cluster B: drive StateProxy tests through the HA boundary"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#4", "FR#8", "AC#5"]
---

## Summary
Convert `tests/integration/test_state_proxy.py` so reconnect and cache-load behavior is driven through the public surface (`on_reconnect()`, `is_ready()`) with the HA boundary supplied by `RecordingApi`/the harness mock server, rather than by patching `load_cache`, `subscribe_to_events`, or `_emit_readiness_event`. Preserve the precise semantics of `mark_not_ready` assertions, including idempotency-guard call-count checks.

## Target Files
- modify: `tests/integration/test_state_proxy.py` — convert StateProxy MUT patches; retain `get_states_raw` patches
- read: `src/hassette/state_manager/` — StateProxy implementation (`on_reconnect`, `is_ready`, `load_cache`, `mark_not_ready`)
- read: `src/hassette/test_utils/recording_api.py` — the HA REST boundary double
- read: `design/specs/075-mock-at-boundaries-test-refactor/tasks/context.md`
- read: `design/specs/075-mock-at-boundaries-test-refactor/design.md`

## Prompt
For each prohibited StateProxy symbol patch in `test_state_proxy.py`, determine the test's MUT and act:

1. **Reconnect/cache-behavior tests that patch `load_cache` / `subscribe_to_events` / `_emit_readiness_event`** (these are the path under test): drive `on_reconnect()` for real, supply the HA boundary via `RecordingApi`/the harness mock server, and assert readiness transitions via `is_ready()` and emitted bus events.
2. **`mark_not_ready` sites — categorize each:**
   - *Pure spy asserting only "was called":* replace with an assertion on the resulting readiness transition (`is_ready()` / emitted not-ready event).
   - *Idempotency-guard spy asserting call-count* (verifying the `if not is_ready(): return` guard fired exactly once): preserve the semantics by asserting the **count of emitted not-ready `service_status` events**, NOT a bare `is_ready()` presence check. Do not weaken the assertion.
   - *Logic-skipping patch:* convert to drive through the boundary.
3. **Concurrency-gating tests (~lines 604–636)** that gate `load_cache`/`subscribe_to_events` to assert ordering: re-express by gating the `RecordingApi`/boundary response with an `asyncio.Event` and asserting observable ordering. Follow the startup-race pattern in context.md's Convention Examples — after `await asyncio.sleep(0)`, assert `not task.done()` to confirm the gate actually blocks before setting it (a single `sleep(0)` may not reach the await point — verify it does).
4. **Leave `get_states_raw` patches as-is** — that is the HA REST boundary, not a violation (context.md Key Decision 6). Do not flag or migrate them.

Run `tests/integration/test_state_proxy.py` and confirm green after the conversion.

## Focus
- `get_states_raw` is at `src/hassette/api/api.py:367`; it is the boundary StateProxy reads through. The harness already wires `RecordingApi` and a mock API server (see `tests/TESTING.md` — `with_state_proxy()` pulls bus + scheduler; `with_api_mock()` provides the mock HTTP server).
- `mark_not_ready` is public surface; several patches are spies, not logic-skips — read each carefully before converting (design.md `## Edge Cases` → "mark_not_ready idempotency-guard sites"). The classic failure here is replacing a `assert_called_once()` with a bare `assert not is_ready()`, which can't distinguish "called once, guarded" from "called twice, unguarded."
- The concurrency-gating sites are the trickiest — use the `asyncio.Event` boundary-gating pattern, not a `load_cache` stub, and watch the scheduling.
- Test-only; no production callers affected (gap check clean).

## Verify
- [ ] FR#1: No test in `test_state_proxy.py` patches its own MUT among `load_cache`/`subscribe_to_events`/`mark_not_ready`/`_emit_readiness_event`; mocks are limited to the HA boundary (`RecordingApi`/mock server, `get_states_raw`) and time.
- [ ] FR#4: Cache-load/reconnect tests drive `on_reconnect()`/`is_ready()` with the HA boundary via `RecordingApi`; idempotency-guard `mark_not_ready` assertions are preserved by counting emitted not-ready events, not weakened to a presence check.
- [ ] FR#8: Every changed test asserts an observable outcome; no configured-but-unasserted mocks remain.
- [ ] AC#5: Breaking `StateProxy.load_cache` (a representative method) causes at least one in-scope StateProxy test to fail.
