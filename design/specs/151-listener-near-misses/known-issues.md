# Known Issues

Real issues found while building this feature and intentionally left unfixed.

The entries below are rare-case ship-challenge findings, each accepted as a limitation on the challenge's recommendation.

## KI-001: One entry that fails to render loses its whole flush batch

Status: open
Recorded: 2026-11-12 (1817)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/listener_miss_recorder.py

Issue:
`ListenerMissRecorder.flush()` builds every row in the same `try` as the write. If `build_row` raises for one entry, every entry in the 30-second batch is dropped and counted under `LISTENER_MISS_FLUSH_FAILED`.

Why deferred:
No path to a render failure is known. `build_row` raises only for a listener without a `db_id`, which `reporter_for` never binds. `summarize_trigger` never raises, and a filter summary that raises would already have failed at registration. The loss is still counted and warned about.

Recommended follow-up:
If a flush-failure WARNING ever shows a render error, build rows one entry at a time, skipping and counting the bad one.

Acceptance criteria:
- A test where one entry's summary raises shows the other entries written and one counted as lost.

## KI-002: A persistent failure in `record()` would log an ERROR per dropped event

Status: open
Recorded: 2026-11-12 (1817)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/listener_miss_recorder.py

Issue:
`record()` catches `Exception` and calls `LOGGER.exception` on every failing call, unpaced. A bug that makes it raise on every call would log a traceback per rejected event on a busy topic.

Why deferred:
`record()` only reads `time.time()` and updates a dict with values it builds itself, so no input is known to make it raise. A flood would also make such a bug obvious at once.

Recommended follow-up:
If it ever floods, pace the log with a timestamp as `count_loss` does.

Acceptance criteria:
- A test with a raising `record` body shows one ERROR per pacing interval.

## KI-003: A new near-miss reason code needs a table-rebuild migration

Status: open
Recorded: 2026-11-12 (1817)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/migrations_sql/025.sql
- wire/src/hassette_wire/literals.py

Issue:
`listener_misses.reason` has a `CHECK (reason IN (...))`. SQLite can't alter a CHECK, so a new reason (for example the global event filter, which this change scopes out) needs a table rebuild as well as a `ListenerMissReason` change.

Why deferred:
CHECK-plus-Literal is the house convention for constrained vocabularies, and `test_wire_check_parity.py` pins this column against the wire literal. A rebuild migration is cheap pre-V1.

Recommended follow-up:
Write the rebuild migration when a new reason lands, following the other CHECK rebuilds.

Acceptance criteria:
- The new reason's rows insert, and `test_wire_check_parity.py` passes.

## KI-004: An unknown listener id returns an empty miss list

Status: open
Recorded: 2026-11-12 (1817)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/web/routes/telemetry.py
- src/hassette/core/telemetry/registration_queries.py

Issue:
`GET /api/telemetry/listener/{listener_id}/misses` (and `hassette listener <id> --misses`) returns `[]` for an id that doesn't exist. That reads the same as "no misses".

Why deferred:
The sibling `/listener/{listener_id}/executions` route behaves the same way. A fix belongs to both routes, the client's error mapping and `client_compat`, which goes beyond this change.

Recommended follow-up:
Return 404 for an unknown listener on both per-listener routes, in one change.

Acceptance criteria:
- Both routes return 404 for a missing listener row, and the CLI prints a not-found error.

## KI-005: A backwards clock step can leave an older event in a row's last-event columns

Status: open
Recorded: 2026-11-12 (1817)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/telemetry/repository.py

Issue:
The upsert replaces the last-event columns only when `excluded.last_ts >= last_ts`. If the host clock steps back within an hour across a restart, counts still add, but the row keeps the older event's values.

Why deferred:
The effect is cosmetic, and execution rows share the clock dependence. Replacing unconditionally would let a late-committing older batch overwrite a newer event instead.

Recommended follow-up:
None unless hosts report clock steps; then order by a per-process sequence rather than wall time.

Acceptance criteria:
- A row's last-event columns match the last event recorded, with the clock stepped back between two flushes.
