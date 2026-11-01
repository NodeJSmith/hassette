# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: Per-instance log and blocking filters omit rows recorded before names were required

Status: open
Recorded: 2026-11-01 (3098)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/telemetry/helpers.py
- src/hassette/core/telemetry/blocking_queries.py
- src/hassette/web/dependencies.py

Issue:
Log and blocking filters moved from `instance_index` to `instance_name`. Rows written before #3095 hold a derived name like `PresenceApp.0`, or occasionally NULL, so they drop out of per-instance results. They stay in app-wide views until retention deletes them. One related edge: `AppRegistry` returns the same `Class.N` label for an index with no configured name, so such an index can match these old rows instead of returning empty, until they age out.

Why deferred:
The user accepted this as a limitation. Nothing is lost, it fades within one retention window (30 days by default), and only per-instance blocking views, `hassette blocking --instance` and client callers can see it. The docs already warn that per-instance views start empty after upgrading. An `IS NULL` fallback wouldn't help, because most old rows aren't NULL.

Recommended follow-up:
Fix it only if a user reports missing per-instance history after upgrading.

Acceptance criteria:
- Rows recorded before #3095 appear in per-instance log and blocking filters, or the report is closed because they have aged out.
