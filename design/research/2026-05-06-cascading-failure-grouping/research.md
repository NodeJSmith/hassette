---
proposal: "Investigate whether the Hassette telemetry data model supports detecting and grouping cascading failures (e.g., 'WebSocket disconnected -> 12 handlers affected') for an activity feed redesign."
date: 2026-05-06
status: Draft
flexibility: Exploring
motivation: "Planning an activity feed redesign; prior art research identified cascading failure grouping (Pattern 5) as high-value for Hassette since WebSocket disconnects cause many simultaneous handler failures that flood the feed."
constraints: "Must work with the existing SQLite telemetry database. No new external dependencies for the grouping logic. Should be implementable as a query-layer or thin backend feature, not a fundamental schema redesign."
non-goals: "Not designing the full activity feed UX — this research focuses on whether the data supports grouping, not how to present it."
depth: normal
---

# Research Brief: Cascading Failure Grouping Feasibility

**Initiated by**: Investigation into whether Hassette's telemetry data model can detect and group failures that share a common root cause (e.g., WebSocket disconnect causing N handler failures).

## Context

### What prompted this

The prior art research brief (`/tmp/claude-mine-prior-art-ESWTHO/brief.md`) identified cascading failure grouping as Pattern 5 — used by Datadog, PagerDuty, and Azure Monitor. For Hassette specifically, this is high-value: when Home Assistant goes down or the WebSocket disconnects, every handler that tries to call the HA API fails with the same error. Today those show as N separate error rows in the activity feed, flooding it with symptoms when the root cause is one line.

### Current state

#### What data exists today

The telemetry database stores rich error context on every failure. Both `handler_invocations` and `job_executions` tables include:

| Column | Type | Content |
|--------|------|---------|
| `execution_start_ts` | REAL | Unix epoch float, sub-second precision |
| `status` | TEXT | `'success'`, `'error'`, `'cancelled'`, `'timed_out'` |
| `error_type` | TEXT | Python exception class name (e.g., `'ConnectionClosedError'`, `'TimeoutError'`, `'FailedMessageError'`) |
| `error_message` | TEXT | Exception message string |
| `error_traceback` | TEXT | Full traceback (up to 8192 chars), nullable |
| `session_id` | INTEGER | FK to sessions table |
| `listener_id` / `job_id` | INTEGER | FK to the registration table |
| `source_tier` | TEXT | `'app'` or `'framework'` |
| `execution_id` | TEXT | UUID4 per execution |
| `trigger_context_id` | TEXT | HA event_id that triggered this invocation (handler_invocations only) |

The `listeners` table provides `app_key`, `handler_method`, and `topic` via JOIN. The `sessions` table records session-level error info (error_type, error_message) for crashes.

The `ActivityFeedEntry` model currently exposes: `status`, `timestamp`, `app_key`, `handler_name`, `duration_ms`, `error_type`, `kind`. The `error_type` field is already present — it comes from the `handler_invocations.error_type` / `job_executions.error_type` column.

#### How errors flow through the system

1. **Error capture**: `track_execution()` in `src/hassette/utils/execution.py` catches exceptions, records `type(exc).__name__` as `error_type` and `str(exc)` as `error_message`. This happens uniformly for both handler invocations and job executions.

2. **Record creation**: `CommandExecutor._build_record()` builds a `HandlerInvocationRecord` or `JobExecutionRecord` with the error fields populated.

3. **Persistence**: Records are batched and written to SQLite via `TelemetryRepository.persist_batch()`.

4. **Query**: `TelemetryQueryService.get_activity_feed()` returns `ActivityFeedEntry` objects with `error_type` from the JOIN query. `get_recent_errors()` returns richer `HandlerErrorRecord` / `JobErrorRecord` with traceback.

#### What exception types handlers see during WebSocket disconnect

When Home Assistant goes down or the WebSocket drops, handlers that call the API see one of these error types:

- **`ConnectionClosedError`** — raised by `send_json()` when `self.connected` is False (WebSocket not established)
- **`RetryableConnectionClosedError`** — raised by `_raw_recv()` when WebSocket closes/errors; also set on pending `_response_futures`
- **`FailedMessageError`** — raised by `send_and_wait()` on timeout, or by `_respond_if_necessary()` when HA returns an error
- **`TimeoutError`** — if the handler's own timeout fires while waiting for an API call that never completes
- **`ResourceNotReadyError`** — if the API session is not connected
- **`aiohttp.ClientConnectorError`** / **`aiohttp.ClientOSError`** — REST API calls that fail at the transport level

The critical insight: **handlers that don't call the HA API during their execution won't fail during a WebSocket disconnect**. Only handlers that actively invoke `self.api.call_service()`, `self.api.get_state()`, etc., will see the error. Handlers that only process event data (which they already received) complete successfully.

This means cascading failures are not universal — they affect a subset of handlers proportional to how many make API calls. But for systems with many active handlers, a disconnect can still produce a burst of 10-50+ simultaneous failures.

### Key constraints

- SQLite is the only data store (no Elasticsearch, no Redis)
- Grouping must be query-time or thin backend logic — no persistent "incident" table
- Must handle both `handler_invocations` and `job_executions` uniformly
- The existing `idx_hi_status_time` and `idx_hi_time` indices are available for efficient querying

## Feasibility Analysis

### Answer to the five specific questions

**Q1: Does ActivityFeedEntry include error_type/error_message fields?**
Yes. `ActivityFeedEntry` already has `error_type: str | None`. The underlying query JOINs to `handler_invocations.error_type` / `job_executions.error_type`. `error_message` is NOT currently in `ActivityFeedEntry` but IS in the database and in `HandlerErrorRecord`/`JobErrorRecord`. Adding it to the feed entry would be a one-field model change + SQL column addition to the UNION ALL query.

**Q2: When the WebSocket disconnects, what exception type do handlers see?**
Primarily `ConnectionClosedError`, `FailedMessageError`, and `TimeoutError`. The `error_type` values stored in the DB will be the Python class names: `"ConnectionClosedError"`, `"FailedMessageError"`, `"TimeoutError"`. These are consistent enough to group on — a burst of `ConnectionClosedError` errors within a short window strongly signals a WebSocket disconnect. The `error_message` provides additional disambiguation (e.g., `"WebSocket connection is not established"` for `ConnectionClosedError`).

**Q3: Is there a temporal correlation signal?**
Yes, and it is strong. All fields use `execution_start_ts` (Unix epoch float with sub-second precision). When a WebSocket drops:
- The `WebsocketService` fires `HASSETTE_EVENT_WEBSOCKET_DISCONNECTED`
- Any in-flight API calls fail nearly simultaneously
- Subsequent handler invocations that call the API also fail quickly (ConnectionClosedError is immediate, not a timeout)

In practice, cascading failures cluster within 0-5 seconds. A 10-30 second window would capture virtually all related failures with minimal false positives.

**Q4: Does the backend store enough data for "N handlers failed with the same error_type within T seconds"?**
Yes. The query would be:
```sql
SELECT error_type, COUNT(*) as affected_count,
       MIN(execution_start_ts) as first_ts,
       MAX(execution_start_ts) as last_ts
FROM (
    SELECT error_type, execution_start_ts FROM handler_invocations
    WHERE status IN ('error', 'timed_out') AND execution_start_ts >= :since
    UNION ALL
    SELECT error_type, execution_start_ts FROM job_executions
    WHERE status IN ('error', 'timed_out') AND execution_start_ts >= :since
) combined
GROUP BY error_type, CAST((execution_start_ts - :window_start) / :bucket_width AS INTEGER)
HAVING COUNT(*) >= :threshold
```
The existing `idx_hi_status_time` and `idx_je_status_time` indices make this efficient.

**Q5: What alternative grouping strategies exist?**
See Options below.

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Query layer | `telemetry_query_service.py` (1 new method) | Low | Low — additive, no existing query changes |
| Telemetry models | `telemetry_models.py` (1-2 new models) | Low | Low — new models only |
| Web route | `web/routes/telemetry.py` (1 new endpoint or modified activity feed) | Low | Low — new endpoint |
| Frontend | `error-feed.tsx` or new component | Med | Med — UX design decisions |
| Schema migration | Only if adding `error_message` to `ActivityFeedEntry` | Low | Low — additive column in query, no DDL |

### What already supports this

1. **`error_type` is already captured and queryable** — every failure records the Python exception class name. This is the primary grouping key.
2. **Sub-second `execution_start_ts`** — temporal clustering is precise enough for windowed grouping.
3. **`session_id` on every record** — can scope grouping to the current session, avoiding cross-session noise.
4. **Existing indices** — `idx_hi_status_time` and `idx_je_status_time` support efficient error-time queries.
5. **`get_recent_errors()` already does a UNION ALL** across both tables with JOINs to listener/job metadata — this query pattern is proven and can be extended.
6. **`ActivityFeedEntry` already has `error_type`** — the grouping key is already in the frontend data model.
7. **Real-time WS events** — `WsInvocationCompletedPayload` and `WsExecutionCompletedPayload` both include `error_type`, enabling client-side grouping for live updates.

### What works against this

1. **No "incident" or "event group" concept in the schema** — grouping is purely derived at query time. This means no stable group ID for pagination, no ability to annotate/resolve a group, and the grouping can shift as the time window moves.
2. **No index on `error_type`** — queries that GROUP BY `error_type` within a time window will scan the relevant time range. For Hassette's typical data volume (hundreds to low thousands of records per hour) this is fine. At scale it would need a composite index.
3. **`error_type` granularity** — `"TimeoutError"` is common for both cascading failures (API call times out because WS is down) and unrelated slowness (handler genuinely slow). The `error_message` disambiguates but is free-text and harder to group on.
4. **No causal link in the data** — the DB doesn't record "this failure was caused by the WebSocket being down." Grouping is inferred from temporal + error_type correlation, not causation. This is the same limitation that Datadog/PagerDuty face — they use heuristics, not proof.

## Options Evaluated

### Option A: Query-Time Temporal + Error-Type Grouping (Recommended)

**How it works**: Add a new `TelemetryQueryService` method (e.g., `get_grouped_errors()`) that queries errors within a time window, applies a two-pass grouping algorithm:

1. **First pass**: Fetch recent errors ordered by `execution_start_ts DESC`.
2. **Second pass** (Python, not SQL): Walk the sorted list and merge consecutive errors with the same `error_type` that fall within a configurable gap threshold (e.g., 30 seconds). Each group becomes a single entry with `error_type`, `count`, `first_ts`, `last_ts`, `affected_app_keys`, and representative `error_message`.

The grouping runs entirely in the query service — no schema changes, no persistent state. The frontend receives pre-grouped data and renders "ConnectionClosedError -- 12 handlers across 3 apps (14:32:01 - 14:32:04)" as a single collapsible row.

For real-time updates via WebSocket, the frontend can do client-side grouping using the same algorithm on the `WsInvocationCompletedPayload` stream — group by `error_type` within a sliding window.

**Pros**:
- Zero schema changes — works with existing DB
- The `error_type` field is already populated on every failure record
- Temporal clustering is a natural fit for cascading failures (they happen within seconds)
- Can be shipped incrementally: backend grouping first, then frontend rendering
- Reversible — if the heuristic is wrong, just remove the grouping layer
- Handles both handler and job failures uniformly via the existing UNION ALL pattern

**Cons**:
- Heuristic-based — two unrelated `TimeoutError` failures within 30 seconds would be incorrectly grouped
- No stable group ID for pagination or deep-linking
- Grouping parameters (gap threshold, minimum count) need tuning
- Groups shift as the time window moves (a group of 12 might split into 8+4 as the window slides)

**Effort estimate**: Small. One new query service method (~50-80 lines including Python grouping), one new or modified route, frontend component changes.

**Dependencies**: None.

### Option B: Error-Type-Only Grouping (Simpler)

**How it works**: Instead of temporal windows, simply group errors by `error_type` within the requested time range. The activity feed becomes "ConnectionClosedError: 12 failures in the last hour" rather than showing 12 individual rows.

This is what the `get_per_app_last_errors()` query already approximates — it finds the most recent error per app. Extending it to count by `error_type` across all apps is straightforward.

**Pros**:
- Simplest possible implementation — a single `GROUP BY error_type` in SQL
- No tuning parameters
- Works well for the dashboard error feed where the time window is fixed (last 24h)

**Cons**:
- Loses temporal information — a `ConnectionClosedError` from 6 hours ago and one from 2 minutes ago end up in the same group
- Cannot distinguish "one disconnect caused 12 failures" from "12 separate intermittent failures over 24 hours"
- Not useful for the chronological activity feed — only for summary/badge views

**Effort estimate**: Small. Modify existing `get_recent_errors()` query to include a `GROUP BY` path, or add a lightweight summary endpoint.

**Dependencies**: None.

### Option C: Session-Event-Correlated Grouping (More Precise)

**How it works**: Instead of pure temporal heuristics, correlate failures with known system events. The `sessions` table records `error_type` when the session crashes. The `WebsocketService` fires `HASSETTE_EVENT_WEBSOCKET_DISCONNECTED`. If a `connectivity` event (WebSocket disconnect) is recorded in the system, all errors within T seconds after that event are tagged as belonging to that incident.

This requires a new lightweight "system_events" table (or reuse of the sessions table) that records when the WebSocket disconnected/reconnected. The grouping query then becomes: "find all errors that occurred between a disconnect and the next reconnect."

**Pros**:
- Causal, not heuristic — directly links failures to the root cause event
- No false positives from unrelated `TimeoutError` failures
- Natural grouping boundaries (disconnect -> reconnect defines the incident window)
- The events already exist in the bus (`HASSETTE_EVENT_WEBSOCKET_DISCONNECTED`, `HASSETTE_EVENT_WEBSOCKET_CONNECTED`) — they just aren't persisted to the DB

**Cons**:
- Requires a new table or column to persist connectivity events — schema migration needed
- Only handles WebSocket-disconnect cascades — doesn't generalize to other failure modes (e.g., a bad HA config causing all `call_service` calls to fail with `FailedMessageError`)
- More complex implementation — need to persist events, correlate them, handle edge cases (disconnect without reconnect, multiple disconnects in rapid succession)
- The `session_id` column partially serves this role already (all failures within a session share the same session_id) but sessions span the entire uptime, not individual incidents

**Effort estimate**: Medium. New migration for system events table, event persistence in `WebsocketService` or a new observer, modified query service method, frontend changes.

**Dependencies**: None (events already exist; just need to persist them).

## Concerns

### Technical risks

- **TimeoutError ambiguity**: `TimeoutError` is the most common error during both cascading failures (API call hanging because WS is down) and genuine handler slowness. Option A would incorrectly group unrelated timeouts that happen to cluster temporally. Mitigation: require a minimum group size (e.g., 3+ failures) before grouping, and use `error_message` as a secondary discriminator when `error_type` is `TimeoutError`.

- **Performance of grouping query**: The UNION ALL + time-range scan is already proven by `get_recent_errors()`. Adding Python-side grouping on the result set (typically 10-50 rows for a dashboard view) adds negligible overhead. No concern here for Hassette's scale.

### Complexity risks

- **Tuning the gap threshold**: Too small (5s) misses slow-propagating cascades; too large (60s) groups unrelated failures. The right value depends on the user's handler count and API call patterns. Making this configurable adds complexity. Starting with 30s and observing real behavior is the pragmatic path.

- **Frontend rendering**: Grouped errors need a different visual treatment than individual errors — collapsible rows, affected count, time range display. This is a UX design task that is separable from the backend work.

### Maintenance risks

- **Heuristic drift**: The grouping heuristic is based on current error propagation patterns. If a future change makes errors propagate differently (e.g., circuit breaker that rate-limits API failures), the grouping parameters may need adjustment.

## Open Questions

- [ ] What minimum group size should trigger grouping? (2+ feels too aggressive; 3+ or 5+ may be more appropriate)
- [ ] Should the gap threshold be configurable, or is a fixed 30-second window sufficient for all users?
- [ ] Should grouped errors be expandable to show individual failures, or just link to the error detail page?
- [ ] Does the `error_message` for `ConnectionClosedError` include enough detail to distinguish "WS down" from "WS reconnecting" scenarios?
- [ ] Should the real-time WS feed send pre-grouped data, or should the frontend do client-side grouping?
- [ ] Would it be valuable to persist connectivity events (Option C) as a future enhancement even if starting with Option A?

## Recommendation

**Start with Option A (Query-Time Temporal + Error-Type Grouping).** The data model already has everything needed. The `error_type` field is consistently populated, timestamps have sub-second precision, and the existing UNION ALL query pattern in `get_recent_errors()` provides a proven template.

The implementation is small (one new query method, one route, frontend component), reversible if the heuristic doesn't work well, and ships value immediately. Option C (session-event correlation) is a worthwhile follow-up that adds precision, but it requires a schema migration and is not needed to prove the concept.

Option B is too coarse for the activity feed but could be useful separately for summary badges ("12 errors of type X today").

Key tuning parameters to decide before implementation:
- **Gap threshold**: 30 seconds (captures fast-propagating cascades without grouping unrelated failures)
- **Minimum group size**: 3 (avoids grouping two coincidental failures)
- **Group display**: Show `error_type`, count, time range, and list of affected `app_key` values

### Suggested next steps

1. **Prototype the grouping query** — add `get_grouped_errors()` to `TelemetryQueryService` with the two-pass algorithm (SQL fetch + Python grouping). Test against a real DB with simulated disconnect failures.
2. **Design the grouped error UX** — decide on the visual treatment (collapsible row, badge count, drill-down behavior). This is a `/mine.define` or `/i-shape` task.
3. **Consider persisting connectivity events** as a future enhancement (Option C) — file a GitHub issue to track the idea of a `system_events` table for WebSocket connect/disconnect timestamps, which would enable causal grouping later.

## Sources

- Prior art brief: `/tmp/claude-mine-prior-art-ESWTHO/brief.md`
- Azure Monitor smart groups: https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence/observability
- Datadog related alert grouping: https://www.datadoghq.com/blog/dashboards-monitors-at-scale/
