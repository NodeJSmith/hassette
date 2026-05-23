---
task_id: "T06"
title: "Add execution endpoint with UUIDv7 and remove old path"
status: "done"
depends_on: ["T01"]
implements: ["FR#7", "FR#8", "AC#7", "AC#8"]
---

## Summary
Create the new `GET /api/executions/{execution_id}` endpoint, switch execution ID generation from UUIDv4 to UUIDv7 (via `uuid_utils`), remove the old `/api/logs/by-execution/{id}` route, and update the CLI design spec. The new endpoint extracts the timestamp from UUIDv7 IDs to determine `retention_expired` without a DB lookup, with a fallback to the existing DB query for historical UUIDv4 IDs.

## Prompt
1. **Add `uuid-utils` dependency** to `pyproject.toml`. Pin to a compatible version range.

2. **Switch execution ID generation** in `src/hassette/core/command_executor.py`:
   - Line 421: change `execution_id = str(uuid.uuid4())` to `execution_id = str(uuid_utils.uuid7())`
   - Line 491: same change
   - Import `uuid_utils` at the top of the file
   - Update the `import uuid` if it's no longer needed (check for other `uuid` usage in the file first)

3. **Create `src/hassette/web/routes/executions.py`:**
   ```python
   router = APIRouter(prefix="/executions", tags=["executions"])

   @router.get("/{execution_id}", response_model=LogsByExecutionResponse)
   async def get_execution_logs(
       execution_id: str,
       hassette: HassetteDep,
       response: Response,
       limit: int = Query(default=500, ge=1, le=5000),
   ) -> LogsByExecutionResponse:
   ```
   - Validate execution_id format: try to parse as UUID. If it's UUIDv7 (version == 7), extract the embedded millisecond timestamp for retention check. If it's UUIDv4 or other version, fall back to `_repo.check_execution_predates_retention_cutoff()` using `hassette.config.logging.log_retention_days` (not `database.retention_days`), consistent with `routes/logs.py:102`.
   - Call `_repo.get_log_records_by_execution(execution_id, limit=limit + 1)` for log records
   - Build and return `LogsByExecutionResponse` with `records`, `truncated`, `retention_expired`
   - Wrap in `try/except DB_ERRORS` → 503 pattern per `routes/logs.py:79-87`

4. **Register the router** in `src/hassette/web/app.py`:
   - Add `from hassette.web.routes.executions import router as executions_router`
   - Add `app.include_router(executions_router, prefix="/api")`

5. **Remove the old route** from `src/hassette/web/routes/logs.py`:
   - Remove `get_logs_by_execution()` function and its `@router.get("/by-execution/{execution_id}")` decorator
   - Remove any imports that become unused after the deletion

6. **Update execution_id docstrings** in `src/hassette/core/telemetry_models.py`:
   - `HandlerInvocation.execution_id` (line 110): change "UUID4 string" to "UUID string (UUIDv7 for new executions, UUIDv4 for historical)"
   - `JobExecution.execution_id` (line 179): same change

7. **Update the CLI design spec** at `/home/jessica/source/hassette/.claude/worktrees/cli/design/specs/063-cli-query-tool/design.md`:
   - Find the command table entry mapping `hassette execution <uuid>` to `GET /api/logs/by-execution/{id}`
   - Change to `GET /api/executions/{execution_id}`

8. **Write tests** in a new file `tests/integration/web_api/test_execution_endpoint.py`:
   - Happy path: mock `_repo.get_log_records_by_execution` to return records, verify 200 + correct `LogsByExecutionResponse`
   - Truncation: mock returns `limit+1` records, verify `truncated=True`
   - UUIDv7 retention: construct a UUIDv7 with a timestamp older than `log_retention_days`, mock returns empty, verify `retention_expired=True`
   - UUIDv4 fallback: pass a UUIDv4, mock `check_execution_predates_retention_cutoff` to return True, verify `retention_expired=True`
   - Empty recent: UUIDv7 with recent timestamp, mock returns empty, verify `retention_expired=False`
   - DB error: mock raises `sqlite3.OperationalError`, verify 503
   - Old path 404: `GET /api/logs/by-execution/some-id` returns 404

## Focus
- Study the existing `get_logs_by_execution()` in `src/hassette/web/routes/logs.py:68-108` — the new endpoint mirrors its logic.
- `LogsByExecutionResponse` is defined at `src/hassette/web/models.py:138-141` — reuse it directly.
- For UUIDv7 timestamp extraction: `uuid_utils.uuid7()` returns a standard `uuid.UUID` object. UUIDv7's first 48 bits are a Unix timestamp in milliseconds. Use `uuid_obj.time` or bit extraction: `timestamp_ms = (uuid_obj.int >> 80) & 0xFFFFFFFFFFFF`.
- The `_repo` pattern: `from hassette.core import telemetry_repository as _repo` — follow the convention in `logs.py`.
- The `check_execution_predates_retention_cutoff` function takes `(execution_id, cutoff_timestamp)` — compute cutoff as `time.time() - hassette.config.logging.log_retention_days * 86400`.
- The test fixtures in `tests/integration/web_api/conftest.py` provide `mock_hassette` and `client`. Use `@patch` on `_repo` methods following the pattern in `test_endpoints.py`.

## Verify
- [ ] FR#7: `GET /api/executions/{execution_id}` returns `LogsByExecutionResponse` with log records
- [ ] FR#8: `GET /api/logs/by-execution/{execution_id}` returns 404; the route handler is removed from `logs.py`
- [ ] AC#7: Tests confirm happy path, truncation, retention expiry (UUIDv7 and UUIDv4 fallback), empty results, and DB error handling
- [ ] AC#8: Tests confirm old path returns 404; CLI design spec at `worktree-cli/design/specs/063-cli-query-tool/design.md` updated to reference `/api/executions/{execution_id}`
