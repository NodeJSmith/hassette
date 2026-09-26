# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Unused `WsLogPayload` compat alias reappeared in generated WS types

Status: open
Run: 144
Source: impl-review
Reason not fixed now: out-of-scope
Observed in: T06 (schema regen), originally flagged in T04's Focus section
Affected files:
- frontend/src/api/ws-types.ts
- scripts/generate-ws-types.cjs

Issue:
`WsLogPayload` type alias (`frontend/src/api/ws-types.ts:145`, emitted by `scripts/generate-ws-types.cjs:38`) has zero real consumers anywhere in `frontend/src/` — T04 removed the store's use of it (`pushLog`/`logBuffer`/`getLogEntries`/`logVersion`), but the generator script still hardcodes the alias with a compat comment claiming "a couple of frontend log-table call sites still reference it," which is no longer true.

Why deferred:
Fixing it requires editing the code-generation script (`scripts/generate-ws-types.cjs`) and regenerating `ws-types.ts`, which falls outside every task's Target Files list (T01-T06) — none of the six tasks owned the generator script itself, only its output. A one-line generator edit is low-risk but is a discrete, out-of-scope follow-up rather than a fix folded into this run's task boundaries.

Recommended follow-up:
Remove the `WsLogPayload` alias and its inaccurate compat comment from `scripts/generate-ws-types.cjs`, then regenerate `ws-types.ts` via `uv run python scripts/export_schemas.py --types` and confirm no other generated/hand-written file references it.

Acceptance criteria:
- `grep -r WsLogPayload frontend/src/ scripts/` returns no matches.
- `uv run python tools/check_schemas_fresh.py` still passes after regeneration.

## KI-002: Dead `"log"` message-type branch left in ws.py's send filter

Status: open
Run: 144
Source: cross-file-review
Reason not fixed now: out-of-scope
Observed in: T01 (added the log_hint gate alongside the existing log gate)
Affected files:
- src/hassette/web/routes/ws.py

Issue:
`_send_from_queue`'s filter (lines 71-79) still branches on `msg_type == "log"` (min-level filtering keyed on `message.get("data", {}).get("level", "")`), but no producer anywhere in the codebase emits a WS message shaped `{"type": "log", ...}` anymore — `LogWsMessage` was fully removed and replaced by `LogHintWsMessage`. Confirmed via repo-wide grep: the only two `"log"` references left are the two conditionals inside this same function. The branch is unreachable and references a payload shape belonging to a type that no longer exists, with nothing in the file explaining whether this is intentional (e.g., tolerance for an un-upgraded client) or leftover.

Why deferred:
The design doc's instruction for T01 was to "extend" the filter to also match `log_hint`, not to remove the old `"log"` branch — removing it now would be a design deviation not authorized by any task, even though it's a one-line, low-risk cleanup.

Recommended follow-up:
Either delete the dead `if msg_type == "log":` branch and simplify to a single `log_hint`-only check, or add a one-line comment explaining why `"log"` is deliberately kept (if there's a real reason, e.g. defensive tolerance for stale server code mid-rollout).

Acceptance criteria:
- `grep -n '"log"' src/hassette/web/routes/ws.py` shows either zero matches (branch removed) or a branch accompanied by an explanatory comment.

## KI-003: `use-log-data.test.ts` hardcodes the source module's timing constants as bare literals

Status: open
Run: 144
Source: clean-code
Reason not fixed now: needs-decision
Observed in: T05, T06 (clean-code review, run 144)
Affected files:
- frontend/src/components/shared/log-table/use-log-data.test.ts
- frontend/src/components/shared/log-table/use-log-data.ts

Issue:
`use-log-data.ts` defines `HINT_DEBOUNCE_MS`, `HINT_MAX_WAIT_MS`, `CATCH_UP_MIN_DELAY_MS`, `CATCH_UP_INITIAL_BACKOFF_MS`, `CATCH_UP_BACKOFF_MULTIPLIER`, and `PERIODIC_RESYNC_MS` as module-local constants (not exported). `use-log-data.test.ts` repeats their numeric values (`200`, `500`, `100`, `1000`, `1500`, `2250`, `5000`) as bare literals dozens of times across the hint-triggered catch-up, periodic re-sync, catch-up cancellation, and base-query merge test blocks, deriving test wait/backoff headroom from them by hand in comments (e.g. "debounce (200ms) + 3 retries at 1000/1500/2250ms backoff"). Bumping any one constant in the source module would silently desync every test's hardcoded timing math instead of failing loudly.

Why deferred:
Fixing this requires a design decision (export the constants from `use-log-data.ts` for test consumption, or introduce a shared test-only timing-constants module) plus a careful, non-mechanical rewrite of every literal and its dependent arithmetic across a ~650-line test file — a broad edit with real risk of silently changing test timing behavior if any single substitution is wrong. That's outside a clean-code pass's fix-in-place scope.

Recommended follow-up:
Export the timing constants from `use-log-data.ts` (or move them to a shared constants module) and update the test file to import and reference them instead of re-deriving the numbers by hand.

Acceptance criteria:
- `use-log-data.test.ts` contains no hardcoded debounce/backoff/resync millisecond literals that duplicate `use-log-data.ts`'s constants.
- The test suite (`cd frontend && npm run test:coverage`) still passes after the rework.

## KI-004: `CATCH_UP_FETCH_LIMIT` is manually kept in sync with the backend's `MAX_QUERY_LIMIT` via a comment only

Status: open
Run: 144
Source: clean-code
Reason not fixed now: needs-decision
Observed in: T05 (clean-code review, run 144)
Affected files:
- frontend/src/components/shared/log-table/constants.ts
- src/hassette/schemas/query_constants.py

Issue:
`CATCH_UP_FETCH_LIMIT = 500` (`frontend/src/components/shared/log-table/constants.ts:314-318`) is documented as matching the backend's `MAX_QUERY_LIMIT` (`src/hassette/schemas/query_constants.py:10`), but nothing enforces that beyond a comment — the two values can silently diverge on a future change to either side.

Why deferred:
Closing this gap for real means either generating the frontend value from the backend constant (extending the existing OpenAPI/WS schema codegen pipeline) or adding a dedicated freshness check similar to `tools/check_schemas_fresh.py`. Both are cross-cutting codegen/tooling decisions beyond a clean-code pass's fix-in-place scope.

Recommended follow-up:
Either emit `MAX_QUERY_LIMIT` into the generated frontend types/constants so `CATCH_UP_FETCH_LIMIT` can reference it directly, or add a lightweight CI check that fails when the two literal values diverge.

Acceptance criteria:
- A code change to either `MAX_QUERY_LIMIT` or `CATCH_UP_FETCH_LIMIT` alone either fails CI or is no longer possible (single source of truth).

## KI-005: `useLogData()` is a ~140-line hook blending multiple concerns

Status: open
Run: 144
Source: clean-code
Reason not fixed now: needs-decision
Observed in: T05 (clean-code review, run 144)
Affected files:
- frontend/src/components/shared/log-table/use-log-data.ts

Issue:
`useLogData()` (`frontend/src/components/shared/log-table/use-log-data.ts:239-380`) is about 140 lines and inlines several distinct concerns in one function body: base-query orchestration, hint debounce/maxWait timer bookkeeping, an abort-controller lifecycle for in-flight catch-up runs, a serialized promise chain guarding against overlapping catch-up executions, and a periodic-resync interval side effect.

Why deferred:
Splitting this into named sub-hooks or helpers is a structural change with real behavior risk (the debounce/backoff/abort/promise-chain logic is exactly the kind of timing-sensitive code this repo's own bug-investigation conventions call out as needing a characterization test first — see CLAUDE.md's "Regression test patterns for this project"). That pin-then-refactor sequencing is out of scope for a clean-code pass.

Recommended follow-up:
Decompose `useLogData()` into focused sub-hooks (e.g. a hint-debounce hook, a catch-up-with-backoff hook, a periodic-resync hook) after writing characterization tests for the current timing behavior, per `refactoring-discipline.md`.

Acceptance criteria:
- `useLogData()` is under ~50 lines and delegates to named, independently testable helpers/hooks for debounce, catch-up backoff, and periodic resync.
- Existing `use-log-data.test.ts` behavior (or its pinned equivalent) still passes unchanged.
