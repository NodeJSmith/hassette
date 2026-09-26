---
task_id: "T03"
title: "Add get_log_records_since function and REST route"
status: "done"
depends_on: ["T01"]
implements: ["FR#4", "FR#5", "FR#10", "AC#3"]
---

## Summary
Add a dedicated `get_log_records_since()` query function in `summary_queries.py` and a new `GET /logs/since/{since_id}` REST route in `logs.py`. This is a separate function and endpoint from the existing `get_log_records()` / `GET /logs/recent` — not a parameter overload. The new function uses `ORDER BY lr.id ASC` (not the existing `timestamp DESC, seq DESC`) to guarantee cursor-based completeness.

## Target Files
- modify: `src/hassette/core/telemetry/summary_queries.py`
- modify: `src/hassette/web/routes/logs.py`
- create: `tests/unit/core/test_log_records_since.py` (or add to existing `tests/unit/core/test_log_records.py`)
- create: `tests/integration/web_api/test_logs_since_endpoint.py` (or add to existing log endpoint tests)
- read: `src/hassette/web/dependencies.py` (for `TelemetryDep`, `db_degrades_to`, query param annotations)
- read: `design/specs/114-ws-log-notify-fetch/design.md`

## Prompt
In `src/hassette/core/telemetry/summary_queries.py`:

1. Add a new method `get_log_records_since()` to `TelemetryQueries` (or whichever class owns `get_log_records`). Signature:

```python
async def get_log_records_since(
    self,
    since_id: int,
    *,
    limit: int = DEFAULT_LOG_RECORDS_LIMIT,
    since: float | None = None,
    app_key: str | None = None,
    level: str | None = None,
    execution_id: str | None = None,
    source_tier: str | None = None,
) -> list[dict[str, Any]]:
```

2. The query is the same LEFT JOIN as `get_log_records()` but with:
   - A mandatory `WHERE lr.id > :since_id` clause (always present, not optional)
   - All the same optional filter clauses (`since`, `app_key`, `level`, `execution_id`, `source_tier`) combined via AND
   - `ORDER BY lr.id ASC LIMIT :limit` (not the existing `timestamp DESC, seq DESC`)

3. `since_id` is required (not optional) — this function always does cursor-based catch-up.

In `src/hassette/web/routes/logs.py`:

4. Add a new route `GET /logs/since/{since_id}` with path parameter `since_id: int`. Accept the same optional query params as the existing `GET /logs/recent` route (`limit`, `app_key`, `level`, `since`, `execution_id`, `source_tier`). Follow the same `db_degrades_to` pattern. Response model is `list[LogEntryResponse]`.

5. Reuse the same validation for `level` and `source_tier` as the existing `get_logs` route. Consider extracting the shared validation into a helper or dependency if it reduces duplication, but don't over-engineer it — the existing pattern is fine to copy.

6. Write unit tests for `get_log_records_since()`:
   - Returns only records with `id > since_id`
   - Orders by `id ASC`
   - Respects filter params (`app_key`, `level`, `source_tier`, `since`, `execution_id`) combined with `since_id`
   - Returns empty list when no records match

7. Write integration tests for the new route:
   - `GET /logs/since/0` returns all records (ordered by id ASC)
   - `GET /logs/since/{N}` returns only records after N
   - Filters compose with `since_id` (e.g., `?app_key=foo` only returns matching records after the cursor)

## Focus
- `get_log_records()` (lines 270-315) uses `ORDER BY lr.timestamp DESC, lr.seq DESC` — the new function must use `ORDER BY lr.id ASC`. This is the whole reason for a separate function instead of an overloaded parameter.
- The existing `get_log_records()` is called from `logs.py:get_logs`, `executions.py:get_execution_logs` (via `get_log_records_by_execution`), and `cli/commands/log.py`. None of those should change.
- `helpers.py` in `core/telemetry/` imports from `summary_queries` — check that `get_log_records_since` doesn't need to be re-exported through `helpers.py` (probably not — the route imports from `summary_queries` via `TelemetryDep`).
- Follow the `db_degrades_to` pattern from the existing `get_logs` route (Category A site — one-line wrap).
- The `LogEntryResponse` model now has `id: int` from T01, so response validation will include it automatically.

## Verify
- [ ] FR#4: `GET /logs/since/{N}` returns only records with `id > N`, as a separate endpoint from `/logs/recent`
- [ ] FR#5: Response includes full linking metadata (`execution_kind`, `listener_id`, `job_id`) via the LEFT JOIN — same enrichment as `/logs/recent`
- [ ] FR#10: `get_log_records_since()` orders by `lr.id ASC`; `get_log_records()` is unchanged (still `timestamp DESC, seq DESC`)
- [ ] AC#3: `GET /logs/since/{N}` returns records ordered by `id ASC` with full linking metadata; `GET /logs/recent` remains unchanged
