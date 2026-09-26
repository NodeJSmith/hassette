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
