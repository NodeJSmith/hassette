---
task_id: "T03"
title: "Extract UNION arm builder helper"
status: "planned"
depends_on: ["T01"]
implements: ["FR#9", "AC#6"]
---

## Summary

Add a `handler_job_union_arms()` helper function to `src/hassette/core/telemetry/helpers.py` that generates the handler/job UNION ALL SQL fragment. Refactor the 3 UNION methods in `execution_queries.py` to call this helper instead of inlining the repeated boilerplate. Method signatures stay unchanged. Depends on T01 because `execution_queries.py`'s telemetry_models imports must already be updated.

## Target Files

- modify: `src/hassette/core/telemetry/helpers.py`
- modify: `src/hassette/core/telemetry/execution_queries.py`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Add a helper function to `src/hassette/core/telemetry/helpers.py`:

```python
def handler_job_union_arms(
    handler_select: str,
    job_select: str,
    *,
    extra_handler_where: str = "",
    extra_job_where: str = "",
    since: float | None = None,
    source_tier: QuerySourceTier = "app",
    instance_index: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build handler UNION ALL job SQL fragment with merged params."""
```

The function builds the two-arm UNION pattern used by all 3 methods:
- Handler arm: `FROM executions e_h JOIN listeners l ON l.id = e_h.listener_id WHERE e_h.kind = 'handler'`
- Job arm: `FROM executions e_j JOIN scheduled_jobs sj ON sj.id = e_j.job_id WHERE e_j.kind = 'job'`

It calls `since_clause` and `source_tier_clause` internally (with `_hi`/`_je` suffixes for the aliases) and handles the param-deduplication convention documented in `execution_queries.py` lines 119-123.

Refactor each of the 3 methods in `execution_queries.py`:
- `get_app_recent_activity` (lines 95-194): call the helper, wrap with `ORDER BY timestamp DESC LIMIT :limit`
- `get_per_app_activity_buckets` (lines 196-266): call the helper, wrap with `GROUP BY app_key, bucket_idx` + SUM/CASE
- `get_per_app_last_errors` (lines 268-316): call the helper, wrap with `ROW_NUMBER() OVER (PARTITION BY app_key ...)`

Do NOT change method signatures or return types.

## Focus

- The param-deduplication convention: both arms bind the same `:source_tier` and `:since` parameter names. The second call's params dict is intentionally discarded. The helper must replicate this — call `source_tier_clause`/`since_clause` twice (once per alias) and merge only the first call's params.
- `instance_index` handling: when provided, adds `AND l.instance_index = :instance_index` to the handler arm and `AND sj.instance_index = :instance_index` to the job arm.
- Each method passes different SELECT column lists — these are the `handler_select` and `job_select` arguments.
- The `app_key` filter (`AND l.app_key = :app_key` / `AND sj.app_key = :app_key`) is method-specific (only `get_app_recent_activity` uses it) — pass it via `extra_handler_where`/`extra_job_where`.
- `get_per_app_activity_buckets` does NOT use `since_clause` — it has a dual time bound (`>= :since AND < :now`) plus a `bucket_idx` expression in its SELECT list. Pass the dual bound via `extra_handler_where`/`extra_job_where`, and the bucket_idx expression via `handler_select`/`job_select`. The helper's `since` parameter should be left as `None` for this method.

## Verify

- [ ] FR#9: all 3 UNION methods call `handler_job_union_arms()` instead of inlining the UNION boilerplate
- [ ] AC#6: method signatures unchanged; `prek -a` passes; `ptest -- tests/integration/telemetry -n 4` passes
