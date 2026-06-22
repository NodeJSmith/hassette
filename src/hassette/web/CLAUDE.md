# Hassette Web API — Python Conventions

## Shared Dependency Aliases

Import from `hassette.web.dependencies` instead of defining locally:

```python
from hassette.web.dependencies import RuntimeDep, TelemetryDep, SchedulerDep, HassetteDep, ApiDep
```

- `RuntimeDep` — live system state (app status, events, WebSocket)
- `TelemetryDep` — historical telemetry from the database (listeners, jobs, errors, summaries)
- `SchedulerDep` — live scheduler heap access (`get_all_jobs()`, `mark_job_cancelled()`)
- `HassetteDep` — the root Hassette instance (drop counters, ready event)
- `ApiDep` — Home Assistant REST/WebSocket API

## Telemetry Error Handling Pattern (#1108b / #1114)

Storage exceptions (`sqlite3.Error`, `OSError`, `ValueError`, `TimeoutError`) are **translated at the `TelemetryQueryService` boundary** into `TelemetryUnavailableError` (defined in `hassette.exceptions`).  The HTTP layer catches only that narrow domain type — never raw storage exceptions.

- `TelemetryQueryService.execute()` wraps its body in `try/except (sqlite3.Error, OSError, ValueError, TimeoutError)` and re-raises as `TelemetryUnavailableError`.
- `get_all_app_summaries` in `summary_queries.py` has its own manual transaction that bypasses `execute()` — it carries the same translation wrapper.
- A non-DB `ValueError` raised inside a handler body (e.g. from `model_validate`, a key error, application logic) **is not** `TelemetryUnavailableError` and will propagate as HTTP 500.  This is the intended behavior.

### `db_degrades_to` — the preferred shape (#1108a)

Use `db_degrades_to(response)` for category-A and category-B sites instead of inlining `try/except`.  The CM catches `TelemetryUnavailableError`, logs a warning with `exc_info`, and sets `response.status_code = 503`.  It does **not** force a return — callers pre-initialize the result to the failure default and return at the tail:

```python
from hassette.web.dependencies import db_degrades_to

# Category A — query is the whole handler
rows: list[Foo] = []
with db_degrades_to(response):
    rows = await telemetry.get_foo(...)
return rows
```

```python
# Category B — post-query work must be skipped on failure; move it inside the with block
result: SomeResponse = SomeResponse(degraded=True)
with db_degrades_to(response):
    agg = await telemetry.get_aggregates(...)
    error_rate = compute_error_rate(agg)       # depends on agg — skipped on failure
    result = SomeResponse(degraded=False, error_rate=error_rate)
return result
```

**Warning:** any code between the `with` block and the tail `return` runs on **both** the success path and the failure path (against the pre-initialized default).  If that code would behave incorrectly against the default, move it inside the `with` block (category B shape).

### Category-C and category-D sites — intentional exceptions

These sites do **not** use `db_degrades_to`.  They catch `TelemetryUnavailableError` inline and return HTTP 200 with partial data — wrapping them in `db_degrades_to` would change their status to 503 and break the frontend contract.

- **Category C (silent-200 partial degradation):** DB failure sets a safe default and the handler continues with non-DB data (e.g. from `runtime.get_all_manifests_snapshot()`).  Status stays 200.  Do not apply `db_degrades_to` to these sites.
- **Category D (multi-failure-mode):** The handler has two independent failure semantics that cannot be expressed by a single CM.  Handle each failure mode inline.

### Site classification table — all 17 `except TelemetryUnavailableError` sites (#1108a + #1108b)

Categories: **A** = one-line wrap; **B** = post-query work must move inside the `with`; **C** = silent-200 EXCLUDED; **D** = multi-failure EXCLUDED.

| # | File | Line | Endpoint / function | Status on failure | Default returned | Category | Action |
|---|------|------|---------------------|-------------------|------------------|----------|----------------|
| 1 | `telemetry.py` | 68 | `telemetry_status` | 503 | `TelemetryStatusResponse(degraded=True)` | **B** | Move drop-counter + error-handler-failure code inside `with`; tail return |
| 2 | `telemetry.py` | 132 | `app_health` | 503 | `AppHealthResponse(error_rate=0.0, ...)` | **B** | Move `error_rate` computation and success `AppHealthResponse` inside `with`; tail return |
| 3 | `telemetry.py` | 176 | `app_listeners` | 503 | `[]` | **B** | Move `live_counts` fetch and list-comp inside `with` (both depend on `listeners`); tail return |
| 4 | `telemetry.py` | 206 | `app_activity` | 503 | `[]` | **A** | One-line wrap; `return` is inside the current `try` |
| 5 | `telemetry.py` | 234 | `app_jobs` | 503 | `[]` | **B** | Move `enrich_jobs_with_live_heap` call inside `with` (must skip on failure); tail return |
| 6 | `telemetry.py` | 259 | `list_executions` | 503 | `[]` | **A** | One-line wrap; `return` is inside the current `try` |
| 7 | `telemetry.py` | 276 | `listener_executions` | 503 | `[]` | **A** | One-line wrap; `return` is inside the current `try` |
| 8 | `telemetry.py` | 293 | `job_executions` | 503 | `[]` | **A** | One-line wrap; `return` is inside the current `try` |
| 9 | `telemetry.py` | 313 | `dashboard_app_grid` — `get_all_app_summaries` | 200 (no set) | `{}` | **C** | EXCLUDED — non-DB spine from `runtime.get_all_manifests_snapshot()` |
| 10 | `telemetry.py` | 328 | `dashboard_app_grid` — `get_per_app_activity_buckets` | 200 (no set) | `{}` (default unchanged) | **C** | EXCLUDED — same non-DB spine |
| 11 | `telemetry.py` | 332 | `dashboard_app_grid` — `get_per_app_last_errors` | 200 (no set) | `{}` (default unchanged) | **C** | EXCLUDED — same non-DB spine |
| 12 | `apps.py` | 61 | `get_app_manifests` — `get_recent_invocations_1h_all_apps` | 200 (no set) | `{}` | **C** | EXCLUDED — non-DB spine from `runtime.get_all_manifests_snapshot()` |
| 13 | `bus.py` | 38 | `get_listener_metrics` | 503 | `[]` | **B** | **DEFERRED to #1095** — the if/else dispatch collapses in #1095; migrate CM in that step |
| 14 | `executions.py` | 41 | `check_retention_expired_uuid4` (helper) | 200 (returns `False`) | `False` | **D** | EXCLUDED — silent false, no 503; part of multi-failure `get_execution_logs` |
| 15 | `executions.py` | 75 | `get_execution_logs` — record fetch | 503 | `LogsByExecutionResponse(records=[], ...)` | **D** | EXCLUDED — multi-failure: record fetch is 503, retention check is silent-false; separate semantics |
| 16 | `logs.py` | 54 | `get_logs` | 503 | `[]` | **A** | One-line wrap; list-comp + `return` are both inside the current `try` |
| 17 | `scheduler.py` | 38 | `all_jobs` | 503 | `[]` | **B** | Move `enrich_jobs_with_live_heap` call inside `with` (must skip on failure); tail return |

**Count:** A: 5, B: 6 (one deferred), C: 4, D: 2 — 17 total.  Sites migrated in #1108a: 10 (5 A + 5 B, excluding the #1095-deferred `get_listener_metrics` at row 13).

**B-site criterion:** "does any code after the query need to be skipped when the query fails?"  For sites 3, 5, 17: the post-query call (`live_execution_counts()`, `enrich_jobs_with_live_heap`) runs against an empty list today only because the explicit `return []` exits early — a tail-return CM would run it against the default.  For sites 1, 2: the success-path response construction uses data from the query result directly and must be skipped.

## Route Registration Pattern

Add routers in `src/hassette/web/app.py`:

```python
from hassette.web.routes.my_module import router as my_router
app.include_router(my_router, prefix="/api")
```

Each router uses `APIRouter(prefix="/some-prefix", tags=["tag"])`. Use `response_model=` on every route decorator for correct OpenAPI output.
