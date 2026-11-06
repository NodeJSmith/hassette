# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A cached state without `context` skips the immediate fire and drops the duration recheck

Status: open
Recorded: 2026-11-06 (3676)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/duration_hold_adapters.py
- src/hassette/bus/duration_hold.py

Issue:
`make_synthetic_state_event` reads `current_state["context"]` directly. A cached state without `context` raises `KeyError`: the immediate fire is skipped with a WARNING, and the duration fire-time recheck is dropped.

Why deferred:
`HassStateDict` marks `context` as `Required`; Home Assistant and the testing factories always set it. A guard would hide a malformed cache entry instead of surfacing it.

Recommended follow-up:
Read `context` defensively if user test suites are found seeding raw state dicts without it through the harness.

Acceptance criteria:
- A context-less cached state fires normally, with NULL trigger context, and a test pins it.

## KI-002: An extraction break logs one traceback per listener per event

Status: open
Recorded: 2026-11-06 (3676)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/execution_record_builder.py

Issue:
If a payload-shape change breaks trigger extraction for every event, each matching listener's run logs its own `LOGGER.exception` traceback, and log records persist to the same SQLite database.

Why deferred:
It needs an upstream payload break to trigger, the failure is loud rather than silent, and a latch would add state to a stateless path.

Recommended follow-up:
Add a first-occurrence latch if log-table growth from this is ever observed.

Acceptance criteria:
- A broken payload logs one traceback per failure location, with later failures counted or logged briefly.

## KI-003: Trigger values are serialized in full before truncation

Status: open
Recorded: 2026-11-06 (3676)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/execution_record_builder.py

Issue:
`format_trigger_value` runs `json.dumps` on the whole value and then cuts it to 255 characters, per listener per event.

Why deferred:
Only a large, fast-changing tracked attribute pays a meaningful cost, and no profile shows it on the hot path.

Recommended follow-up:
Add a bounded encode or size pre-check if a profile of a real install shows `format_trigger_value` as hot.

Acceptance criteria:
- Serialization cost is bounded by the 255-character cap, verified by a profile or benchmark.

## KI-004: `hassette execution --json` reports a failed lookup the same as a missing record

Status: open
Recorded: 2026-11-06 (3676)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/cli/commands/log.py

Issue:
Both a failed execution lookup and a missing record produce `"execution": null` with exit 0; the failure reason goes to stderr only.

Why deferred:
D6 ratified the lenient contract, and the dual-failure case is uncommon.

Recommended follow-up:
Add an `execution_error` key when #3677 extends the `--json` object, if a stdout-only consumer needs it.

Acceptance criteria:
- A stdout-only consumer can tell a failed lookup from a missing record.

## KI-005: Pre-023 handler rows carry an all-None `trigger` object

Status: open
Recorded: 2026-11-06 (3676)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/telemetry/execution_queries.py

Issue:
Handler rows written before migration 023 get an `ExecutionTrigger` with every field None, so `if execution.trigger:` is true for them.

Why deferred:
The documented rule ("set on every handler row") is consistent, the rows age out under retention, and the one in-repo consumer checks fields.

Recommended follow-up:
Return `trigger=None` for all-NULL handler rows if an external consumer is found branching on `trigger is None`.

Acceptance criteria:
- `trigger is None` means "nothing recorded" and the docstring says so.
