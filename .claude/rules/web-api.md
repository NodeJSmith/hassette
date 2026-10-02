---
paths:
  - "src/hassette/web/**"
  - "src/hassette/core/telemetry/**"
---

# Hassette Web API — Python Conventions

## Shared Dependency Aliases

Import from `hassette.web.dependencies` instead of defining locally:

```python
from hassette.web.dependencies import RuntimeDep, TelemetryDep, SchedulerDep, HassetteDep, ApiDep
```

- `RuntimeDep` — live system state (app status, events, WebSocket)
- `TelemetryDep` — historical telemetry from the database (listeners, jobs, errors, summaries)
- `SchedulerDep` — live scheduler registry access (`get_all_jobs()`, `mark_job_removed()`)
- `HassetteDep` — the root Hassette instance (drop counters, ready event)
- `ApiDep` — Home Assistant REST/WebSocket API

## Shared Route Parameters

`dependencies.py` also owns the query/path parameter annotations. Annotate route parameters
with these instead of repeating a `Query(...)`/`Path(...)` call in every signature:

```python
from hassette.web.dependencies import AppKeyPath, LimitQuery, SinceQuery, SourceTierQuery

async def my_route(app_key: AppKeyPath, since: SinceQuery = None, limit: LimitQuery = 50) -> ...:
```

Per-app telemetry routes take the whole `instance_index`/`since`/`source_tier` filter set as one
injected dependency, and splat it into the query call:

```python
from hassette.web.dependencies import TelemetryFiltersDep

async def app_health(app_key: AppKeyPath, telemetry: TelemetryDep, filters: TelemetryFiltersDep) -> ...:
    agg = await telemetry.get_app_health_aggregates(app_key=app_key, **filters.query_kwargs)
```

FastAPI flattens a dependency's parameters into the operation, so the OpenAPI schema is identical
to declaring all three inline.

## Error Responses

Every error under `/api` is an RFC 9457 `application/problem+json` body with a `ProblemCode` in `code` (`hassette_wire/problems.py`). `src/hassette/web/errors.py` owns the whole mechanism: the code-to-status table, the handlers, the body builder, and the OpenAPI rewrite. The user-facing catalog is `docs/pages/web-ui/api-errors.md`.

- **Routes raise `WebApiError(ProblemCode.X, detail)`**, never `HTTPException`. The status comes from `CODE_STATUS`. Keep `from exc` chaining.
- **Middleware calls `problem_response()`**, never builds a body by hand. `tests/unit/web/test_error_mechanism_guard.py` fails on any `HTTPException(...)` or `{"detail": ...}` outside `errors.py`, and on any `ProblemCode` missing from the catalog page.
- **Declare operation-specific codes with `responses=problem_responses(...)`**. Compose shared-helper codes from the tuples next to the helpers in `routes/apps.py` (`APP_KEY_CODES`, `ACTION_CODES`, ...). Global codes (`GLOBAL_CODES`) are never declared per route. An autouse fixture in `tests/integration/web_api/conftest.py` fails any test where a route raises a code it doesn't declare.
- **A new code** goes in `ProblemCode`, `CODE_STATUS`, `CODE_DESCRIPTIONS` (if operation-specific), and the catalog page. Prefer adding a code over reusing one with a different meaning.
- **401 is reserved for authentication.** `DefaultDenyMiddleware` counts every outgoing 401 as a failed login, so only `invalid_token` and `not_authenticated` map to 401. A unit test pins this.
- **Never put the rejected value in `detail`.** The 422 summary uses only `loc` and `msg`; hassette's own request-model validators must not interpolate the validated value into their error message either, because it reaches `detail`.
- **Stability:** codes follow the wire contract's pre-1.0 policy. Renaming or removing a code, or changing its status, is a breaking change (`feat!:`, `BREAKING CHANGE:` footer, `tools/wire_compat_ignore.txt` if flagged). Adding one is not. The `detail` of routing errors (`not_found`, `method_not_allowed`) is not stable.
- **Not problem bodies:** `db_degrades_to` 503s, the inline 503 in `routes/executions.py`, `/api/health/ready`, and `/api/telemetry/status` return success models with a 503. They are data, not errors, and the CLI (`tolerate_503`) and load balancers read them as data. The OpenAPI rewrite matches on schema references, not status, so it leaves them alone.

## Telemetry Error Handling Pattern

Storage exceptions (`sqlite3.Error`, `OSError`, `ValueError`, `TimeoutError`) are **translated at the `TelemetryQueryService` boundary** into `TelemetryUnavailableError` (defined in `hassette.exceptions`).  The HTTP layer catches only that narrow domain type — never raw storage exceptions.

- `TelemetryQueryService.execute()` wraps its body in `try/except STORAGE_ERRORS` (the `(sqlite3.Error, OSError, ValueError, TimeoutError)` tuple, named once in `core/telemetry/helpers.py`) and re-raises as `TelemetryUnavailableError`.
- `get_all_app_summaries` in `summary_queries.py` has its own manual transaction that bypasses `execute()` — it carries the same translation wrapper.
- A non-DB `ValueError` raised inside a handler body (e.g. from `model_validate`, a key error, application logic) **is not** `TelemetryUnavailableError` and will propagate as HTTP 500.  This is the intended behavior.

### `db_degrades_to` — the preferred shape

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

- **Category C (silent-200 partial degradation):** DB failure sets a safe default and the handler continues with non-DB data (e.g. `dashboard_app_grid`'s `get_all_app_summaries` enrichment query).  Status stays 200.  Do not apply `db_degrades_to` to these sites.
- **Category D (multi-failure-mode):** The handler has two independent failure semantics that cannot be expressed by a single CM (e.g. `get_app_manifest`: 503 when the DB is unavailable vs. 404 for a genuinely unknown `app_key`).  Handle each failure mode inline.

**A vs. B:** ask "does any code after the query need to be skipped when the query fails?"  Post-query calls such as `live_execution_counts()` or `enrich_jobs_with_live_data`, and success-path response construction that reads the query result, must move inside the `with` block (category B) — a tail-return CM would otherwise run them against the pre-initialized default.  To find every site, grep `src/hassette/web/` for `db_degrades_to` and `TelemetryUnavailableError`.

## Route Registration Pattern

Add routers in `src/hassette/web/app.py`:

```python
from hassette.web.routes.my_module import router as my_router
app.include_router(my_router, prefix="/api")
```

Each router uses `APIRouter(prefix="/some-prefix", tags=["tag"])`. Use `response_model=` on every route decorator for correct OpenAPI output.
