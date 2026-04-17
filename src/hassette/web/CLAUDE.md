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

## DB_ERRORS Catch Pattern

Use the shared `DB_ERRORS` tuple to suppress database failures gracefully (never 500 on transient DB errors):

```python
from hassette.web.routes.telemetry import DB_ERRORS

try:
    result = await telemetry.some_query()
except DB_ERRORS:
    LOGGER.warning("Failed to fetch ...", exc_info=True)
    response.status_code = 503
    return []
```

`DB_ERRORS = (sqlite3.Error, OSError, ValueError)` — all three are suppressed uniformly.

## Route Registration Pattern

Add routers in `src/hassette/web/app.py`:

```python
from hassette.web.routes.my_module import router as my_router
app.include_router(my_router, prefix="/api")
```

Each router uses `APIRouter(prefix="/some-prefix", tags=["tag"])`. Use `response_model=` on every route decorator for correct OpenAPI output.
