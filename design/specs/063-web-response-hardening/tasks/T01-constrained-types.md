---
task_id: "T01"
title: "Define constrained types and apply to all model fields"
status: "planned"
depends_on: []
implements: ["FR#1", "AC#1"]
---

## Summary
Create the constrained type definitions (one StrEnum, six Literal aliases) and apply them to every model field that currently uses bare `str` for an enumerated value. This covers telemetry models, web response models, and WebSocket payload models. Also fix the `_health_status_from_summary()` function to return `"excellent"` instead of `"unknown"` for zero-invocation apps, and annotate the classification helper return types with their corresponding Literals. Write unit tests confirming Pydantic rejects out-of-range values.

## Prompt
1. **Create `InvocationStatus` StrEnum** in `src/hassette/types/types.py` alongside `SourceTier`:
   ```python
   class InvocationStatus(StrEnum):
       SUCCESS = "success"
       ERROR = "error"
       CANCELLED = "cancelled"
       TIMED_OUT = "timed_out"
   ```
   Verify the complete value set by checking CHECK constraints in `src/hassette/migrations/versions/001_initial_schema.py` and `005_add_timed_out_status.py`, and grepping for status string assignments in `src/hassette/core/command_executor.py`.

2. **Create Literal aliases** in `src/hassette/web/models.py` (top of file, after imports):
   - `ManifestStatus = Literal["disabled", "blocked", "running", "failed", "stopped"]` — verify values against `src/hassette/core/app_registry.py:255`
   - `ErrorRateClass = Literal["good", "warn", "bad"]` — verify against `src/hassette/web/telemetry_helpers.py` `classify_error_rate()` return values
   - `HealthStatus = Literal["excellent", "good", "warning", "critical"]` — verify against `classify_health_bar()` return values. Note: does NOT include `"unknown"` — see step 5.
   - `ListenerKind = Literal["state change", "service call", "event"]` — verify against `_listener_kind_from_topic()` in `src/hassette/web/mappers.py:152-156`

3. **Extract `SystemHealthStatus`** — `Literal["ok", "degraded", "starting"]` already typed at `src/hassette/core/domain_models.py:62`. Create an alias in `src/hassette/web/models.py` and apply to `SystemStatusResponse.status`.

4. **Apply types to model fields:**
   - `src/hassette/core/telemetry_models.py`: `InvocationStatus` on `HandlerInvocation.status` (line 104), `JobExecution.status` (line 173), `ActivityFeedEntry.status` (line 282). `LOG_LEVEL_TYPE` (from `src/hassette/types/types.py:18`) on `LogRecord.level` (line 319).
   - `src/hassette/web/models.py`:
     - `ResourceStatus` (from `src/hassette/types/enums.py:84`) on `AppInstanceResponse.status`, `ServiceInfoResponse.status`
     - `ManifestStatus` on `AppManifestResponse.status`, `DashboardAppGridEntry.status`
     - `SystemHealthStatus` on `SystemStatusResponse.status`
     - `ErrorRateClass` on `AppHealthResponse.error_rate_class`, `DashboardAppGridEntry.error_rate_class`
     - `HealthStatus` on `AppHealthResponse.health_status`, `DashboardAppGridEntry.health_status`
     - `ListenerKind` on `ListenerWithSummary.listener_kind`
     - `InvocationStatus` on `InvocationCompletedData.status` (line 209), `ExecutionCompletedData.status` (line 220)
     - `SourceTier | None` on `LogEntryResponse.source_tier` (line 135)
     - `LOG_LEVEL_TYPE` on `LogEntryResponse.level`

5. **Fix `_health_status_from_summary()`** in `src/hassette/web/telemetry_helpers.py` — change the `total == 0` branch (around line 101) to return `"excellent"` instead of `"unknown"`. This aligns with the 503 fallback path at `src/hassette/web/routes/telemetry.py:143`.

6. **Annotate classification helper return types** in `src/hassette/web/telemetry_helpers.py`:
   - `classify_error_rate() -> ErrorRateClass`
   - `classify_health_bar() -> HealthStatus`

7. **Write unit tests** in a new file `tests/integration/web_api/test_model_types.py`:
   - Test that `InvocationStatus` rejects `"bogus"` via `pytest.raises(ValidationError)` on a model using the field
   - Test that `ManifestStatus` rejects values outside the 5-value set
   - Test that `ResourceStatus` accepts all 9 values (including transient states)
   - Test that `HealthStatus` rejects `"unknown"`
   - Test that `ErrorRateClass` rejects `"ok"` (not in the 3-value set)
   - Test that `ListenerKind` rejects `"custom"` (not in the 3-value set)
   - Test that `LOG_LEVEL_TYPE` rejects `"WARN"` (non-standard)

## Focus
- `ResourceStatus` already exists as a StrEnum at `src/hassette/types/enums.py:84` with 9 values. Import it; do not recreate it.
- `LOG_LEVEL_TYPE` already exists at `src/hassette/types/types.py:18`. Import it; do not recreate it as `LogLevel`.
- `SourceTier` already exists at `src/hassette/types/types.py:21`. Import it directly.
- The frontend `APP_STATUS_MAP` in `frontend/src/utils/status.ts:8-24` already handles all 9 `ResourceStatus` values — confirms they appear in production.
- `InvocationCompletedData.status` and `ExecutionCompletedData.status` (WebSocket models at `web/models.py:209, 220`) must also get `InvocationStatus` — same values as HTTP.
- Pydantic v2 coerces string values to StrEnum members automatically on model construction and serializes back to plain strings in JSON.

## Verify
- [ ] FR#1: Every field with an enumerated value set uses a constrained type — `HandlerInvocation.status`, `JobExecution.status`, `ActivityFeedEntry.status`, `LogRecord.level`, `AppInstanceResponse.status`, `ServiceInfoResponse.status`, `AppManifestResponse.status`, `DashboardAppGridEntry.status`, `SystemStatusResponse.status`, `AppHealthResponse.error_rate_class`, `AppHealthResponse.health_status`, `DashboardAppGridEntry.error_rate_class`, `DashboardAppGridEntry.health_status`, `ListenerWithSummary.listener_kind`, `InvocationCompletedData.status`, `ExecutionCompletedData.status`, `LogEntryResponse.source_tier`, `LogEntryResponse.level`
- [ ] AC#1: Unit tests confirm Pydantic rejects out-of-range values for all constrained types; `pyright` passes with no new type errors
