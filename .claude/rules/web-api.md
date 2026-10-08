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

`TelemetryFiltersDep` defaults `instance_index` to 0, which fits views of one instance. A
multi-instance app's page with no `?instance=` is an app-wide overview (`MultiInstanceOverview`),
not instance 0. A route that feeds that view takes `OptionalInstanceIndexQuery` instead, where an
omitted index means every instance; `/app/{key}/blocking` is the example. Such a route declares
its filters inline, since the dependency's 0 default and its `source_tier` don't apply.

## Error Responses

Every error under `/api` is an RFC 9457 `application/problem+json` body with a `ProblemCode` in `code` (`hassette_wire/problems.py`). `src/hassette/web/errors.py` owns the whole mechanism: the code-to-status table, the handlers, the body builder, and the OpenAPI rewrite. The user-facing catalog is `docs/pages/web-ui/api-errors.md`.

- **Routes raise `WebApiError(ProblemCode.X, detail)`**, never `HTTPException`. The status comes from `CODE_STATUS`. Keep `from exc` chaining.
- **Middleware calls `problem_response()`**, never builds a body by hand. `tests/unit/web/test_error_mechanism_guard.py` fails on any `HTTPException(...)` or `{"detail": ...}` outside `errors.py`, and on any `ProblemCode` missing from the catalog page.
- **Declare operation-specific codes with `responses=problem_responses(...)`**. Compose shared-helper codes from the tuples next to the helpers in `routes/apps.py` (`APP_KEY_CODES`, `ACTION_CODES`, ...). Global codes (`GLOBAL_CODES`) are never declared per route. An autouse fixture in `tests/integration/web_api/conftest.py` fails any test where a route raises a code it doesn't declare.
- **A new code** goes in `ProblemCode`, `CODE_STATUS`, `CODE_DESCRIPTIONS` (if operation-specific), and the catalog page, and in `hassette_client`'s `CODE_ERRORS` (with its own exception class) or `GENERIC_CODES` (`client/src/hassette_client/errors.py`); a client test fails until it's in one. Prefer adding a code over reusing one with a different meaning.
- **401 is reserved for authentication.** `DefaultDenyMiddleware` counts every outgoing 401 as a failed login, so only `invalid_token` and `not_authenticated` map to 401. A unit test pins this.
- **Never put the rejected value in `detail`.** The 422 summary uses only `loc` and `msg`; hassette's own request-model validators must not interpolate the validated value into their error message either, because it reaches `detail`.
- **Stability:** codes follow the wire contract's pre-1.0 policy. Renaming or removing a code, or changing its status, is a breaking change (`feat!:`, `BREAKING CHANGE:` footer, `tools/wire_compat_ignore.txt` if flagged). Adding one is not. The `detail` of routing errors (`not_found`, `method_not_allowed`) is not stable.
- **Not problem bodies:** the two probes, `/api/health/ready` and `/api/telemetry/status`, return their status models with a 503. They are data, not errors, and the CLI (`tolerate_503`), `hassette_client` (`status_model_on_503`) and load balancers read them as data. The OpenAPI rewrite matches on schema references, not status, so it leaves them alone. No other route answers an error status with a success model.

## Client Coverage

Every route needs a typed method on `hassette_client.HassetteClient`, unless the test's `BROWSER_ONLY_OPERATIONS` names it with a reason. `client/tests/test_openapi_coverage.py` reads the committed `frontend/openapi.json`, so a new route or query parameter fails it until a method sends it and the test's `CALLS` table lists that method, passing every keyword filter. A new probe-style route that answers 503 with its status model also goes in that test's `STATUS_MODEL_503_METHODS`.

A route or response field the client starts depending on also needs an API schema bump in the same PR; see `.claude/rules/client-schema-floor.md`.

## Telemetry Error Handling Pattern

Storage exceptions (`sqlite3.Error`, `OSError`, `ValueError`, `TimeoutError`) are **translated at the `TelemetryQueryService` boundary** into `TelemetryUnavailableError` (defined in `hassette.exceptions`).  The HTTP layer catches only that narrow domain type — never raw storage exceptions.

- `TelemetryQueryService.execute()` wraps its body in `try/except STORAGE_ERRORS` (the `(sqlite3.Error, OSError, ValueError, TimeoutError)` tuple, named once in `core/telemetry/helpers.py`) and re-raises as `TelemetryUnavailableError`.
- `get_all_app_summaries` in `summary_queries.py` has its own manual transaction that bypasses `execute()` — it carries the same translation wrapper.
- A non-DB `ValueError` raised inside a handler body (e.g. from `model_validate`, a key error, application logic) **is not** `TelemetryUnavailableError` and will propagate as HTTP 500.  This is the intended behavior.

### Required queries: let the error propagate

When a route can't answer without a telemetry query, don't catch `TelemetryUnavailableError`. `telemetry_unavailable_handler` in `errors.py` turns it into a `telemetry_unavailable` problem (503) and logs a warning with the request path. The route declares the code with `responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE)` (composed with its other codes, if any). The handler answers through `http_exception_handler` as a `WebApiError`, so the autouse `problem_code_violations` fixture in `tests/integration/web_api/conftest.py` fails a route that lets it escape undeclared.

```python
@router.get("/foo", response_model=list[Foo], responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE))
async def foo(telemetry: TelemetryDep) -> list[Foo]:
    return await telemetry.get_foo(...)
```

No fallback value, no `response.status_code`, no `try`. Post-query work (`live_execution_counts()`, `enrich_jobs_with_live_data`) runs only on success because the exception skips it.

### Optional queries and probes: catch inline

Catch `TelemetryUnavailableError` yourself only when the route still has a useful answer without the query:

- **Enrichment (partial data at 200):** the route answers from other data and a failed enrichment query degrades to a safe default (e.g. the execution-logs route's UUIDv4 retention check). Log a warning with `exc_info` and keep going. A route whose rows carry nullable enrichment parts (`app_grid`'s `AppActivity`) reports a failed enrichment as its `null` part instead, and logs one summary warning naming the failed parts.
- **Probes:** `/api/telemetry/status` catches the health-check failure and answers its own `TelemetryStatusResponse(degraded=True)` with a 503 (see "Not problem bodies" above). Don't add another probe-shaped route without the same reason.

To find every inline site, grep `src/hassette/web/` for `TelemetryUnavailableError`.

## Route Registration Pattern

Add routers in `src/hassette/web/app.py`:

```python
from hassette.web.routes.my_module import router as my_router
app.include_router(my_router, prefix="/api")
```

Each router uses `APIRouter(prefix="/some-prefix", tags=["tag"])`. Use `response_model=` on every route decorator for correct OpenAPI output.
