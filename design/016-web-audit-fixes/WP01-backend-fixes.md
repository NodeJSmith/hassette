# WP01: Backend Fixes

**Lane:** todo
**Estimated scope:** 6 fixes across 7 backend Python files

## Changes

### 1. Fix hardcoded avg_job_duration_ms (#393)

**Files:**
- `src/hassette/core/telemetry_models.py` — Add `avg_duration_ms: float = 0.0` to `JobGlobalStats`
- `src/hassette/core/telemetry_query_service.py` — Add `COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms` to the job query SQL in `get_global_summary()` (both session-filtered and unfiltered branches). Map the new column into `JobGlobalStats` construction.
- `src/hassette/web/routes/telemetry.py:185` — Replace `avg_job_duration_ms=0.0` with `summary.jobs.avg_duration_ms or 0.0`

**Test:** Verify `/dashboard/kpis` returns `0.0` when no job executions exist, and returns a positive value when job executions with non-zero duration exist.

### 2. Remove dead compute_app_grid_health (#395)

**Files:**
- `src/hassette/web/telemetry_helpers.py` — Delete `compute_app_grid_health()` function (lines 153–181)

**Test:** None needed. Grep confirms zero callers.

### 3. Remove stub /scheduler/history (#396)

**Files:**
- `src/hassette/web/routes/scheduler.py` — Delete the `get_job_history` endpoint (lines 52–59)
- May need to remove unused `JobExecutionResponse` import

**Test:** Update or remove any existing test asserting this endpoint exists.

### 4. Improve WS drop observability (#400)

**Files:**
- `src/hassette/core/runtime_query_service.py:327` — Change `self.logger.debug(...)` to `self.logger.warning("Dropping message for slow WebSocket client (total clients: %d)", len(self._ws_clients))`

**Test:** None needed (log level change).

### 5. Add response models to mutation endpoints (#401)

**Files:**
- `src/hassette/web/models.py` — Add `ActionResponse(BaseModel)` with `status: str`, `app_key: str`, `action: str`
- `src/hassette/web/routes/apps.py` — Add `response_model=ActionResponse` to start/stop/reload, change return type
- `src/hassette/web/routes/config.py` — Create and apply `ConfigResponse` model from `_CONFIG_SAFE_FIELDS`

**Test:** Verify OpenAPI schema shows typed response fields (not bare `object`).

### 6. Fix bus.py return type annotation (#402)

**Files:**
- `src/hassette/web/routes/bus.py:21` — Change `-> list[ListenerSummary]` to `-> list[ListenerMetricsResponse]`

**Test:** None needed (type annotation fix, runtime behavior unchanged).

## Acceptance criteria

- [ ] Dashboard KPI shows non-zero avg job duration when data exists
- [ ] `compute_app_grid_health` no longer exists in codebase
- [ ] `/scheduler/history` endpoint removed
- [ ] WS message drops logged at WARNING level
- [ ] Mutation endpoints have typed response models in OpenAPI
- [ ] `bus.py` return annotation matches response_model
- [ ] All existing tests pass
