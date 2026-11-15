# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: Drop accounting and the session-manager lookup are not themselves guarded

Status: open
Recorded: 2026-11-15 (3678)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/session_manager.py
- src/hassette/core/telemetry/lifecycle_rows.py

Issue:
`count_lifecycle_drop` (counter increment, config read, WARNING) runs inside the writer's `except` handler, and `record_lifecycle_change` increments the counter after its lookup guard, so a failure in either escapes into the status owner. The lookup's `except Exception` also counts any lookup failure as "not wired" at DEBUG.

Why deferred:
Accepted in the ship-time challenge's re-evaluation of the guard (Findings 1, 3, 4): every `Hassette` and `make_mock_hassette()` provide `pipeline_counters` and `config`, and the accessor's only raise is the not-wired `RuntimeError`.

Recommended follow-up:
Guard the accounting tail, or narrow the lookup catch, if a harness that builds partial `Hassette` objects appears or the accessor gains logic that can fail otherwise.

Acceptance criteria:
- A partial `Hassette` driving a status owner records a counted drop instead of raising.

## KI-002: A dropped run of rows that returns to its starting state leaves no gap in the from_status chain

Status: open
Recorded: 2026-11-15 (3678)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/session_manager.py
- src/hassette/migrations_sql/026.sql

Issue:
D8's reading contract detects missing rows by a `from_status` break. Rows dropped as a closed cycle (a whole flap, or RUNNING to FAILED to STARTING to RUNNING) keep the chain intact, so a past session reads as continuously up. `LIFECYCLE_ROWS_DROPPED` lives only in memory.

Why deferred:
Accepted as a rare-case limitation in the ship-time challenge (Finding 8); matches D8 and every surveyed peer.

Recommended follow-up:
If #4084 needs to mark a past session as incomplete, persist the drop count on `sessions` at finalize (a `dropped_lifecycle` column), as the executor drop counters already are.

Acceptance criteria:
- A past session whose writer dropped rows says so in the read path.

## KI-003: ConnectionDetails.cause is stored untruncated

Status: open
Recorded: 2026-11-15 (3678)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/telemetry/lifecycle_rows.py

Issue:
`cause` holds `describe_failure(exc)` text with no length cap, repeated on each CONNECTING row after a failure.

Why deferred:
Accepted as a rare-case limitation (Finding 9): no other persisted error text in the schema is capped, and aiohttp/ssl messages are normally one line.

Recommended follow-up:
Cap `cause` in `ConnectionDetails` if long exception messages show up in real reconnect logs.

Acceptance criteria:
- A long exception message stores at most the capped length per row.

## KI-004: The paced drop WARNING reports only the first drop in its window

Status: open
Recorded: 2026-11-15 (3678)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/session_manager.py

Issue:
`count_lifecycle_drop` logs the first drop per pacing window with no suppressed count, and nothing reads `LIFECYCLE_ROWS_DROPPED`, so an episode's size isn't visible from the logs.

Why deferred:
Accepted as a rare-case limitation (Finding 10); `ApiWriteRecorder.warn_drop` has the same shape.

Recommended follow-up:
Carry a suppressed count into the next WARNING (in `WarnPacer`, for every paced site), or surface the counter in status output.

Acceptance criteria:
- A drop episode's size is visible from the logs or status.

## KI-005: Retention by ts can leave a mid-session hole after a backward clock step

Status: open
Recorded: 2026-11-15 (3678)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/retention_targets.py

Issue:
The lifecycle target deletes `ts < cutoff`, and `ts` can step back, so rows near the cutoff may be deleted out of `id` order; #4084 would briefly show a "rows missing" break instead of a lost head.

Why deferred:
Accepted as a rare-case limitation (Finding 11): cosmetic, transient, and only on rows about `retention_days` old.

Recommended follow-up:
Delete lifecycle rows by an `id` bound per session if #4084 starts alerting on breaks.

Acceptance criteria:
- After a backward clock step, retention leaves each session's surviving rows a contiguous `id` suffix.

## KI-006: write_lifecycle_row assumes the event-loop thread without saying so

Status: open
Recorded: 2026-11-15 (3678)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/session_manager.py

Issue:
`write_lifecycle_row` calls `asyncio.Queue.put_nowait`, which isn't thread-safe; its docstring says it serves sync callers but not that they must be on the loop thread.

Why deferred:
Accepted as a rare-case limitation (Finding 12): every current caller is on the loop, like the rest of the async core.

Recommended follow-up:
Document or enforce loop-thread-only if a threaded caller (sync executor, user thread) can reach a status owner.

Acceptance criteria:
- A threaded caller either can't reach the writer or is marshalled onto the loop.
