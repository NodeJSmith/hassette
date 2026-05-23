---
task_id: "T07"
title: "Update frontend paths and regenerate schemas"
status: "done"
depends_on: ["T01", "T02", "T03", "T04", "T05", "T06"]
implements: ["AC#9", "AC#11", "AC#12"]
---

## Summary
Update the frontend to use the new `/api/executions/{execution_id}` path, update the MSW test handler, regenerate the OpenAPI spec and TypeScript types from the modified backend, and verify the full test suite passes. This is the final task — it depends on all prior tasks because schema regeneration must capture all backend changes.

## Prompt
1. **Install frontend dependencies** (worktree has no `node_modules`):
   ```bash
   cd frontend && npm install
   ```

2. **Update the API client** in `frontend/src/api/endpoints.ts`:
   - Find the function that calls `/api/logs/by-execution/` (around line 110-111)
   - Change the path to `/api/executions/`
   - Update the function name if it's called `getLogsByExecution` — rename to `getExecutionLogs` or similar to match the new path semantics

3. **Update the MSW mock** in `frontend/src/test/handlers.ts`:
   - Line ~134: change `http.get("/api/logs/by-execution/:execution_id", ...)` to `http.get("/api/executions/:execution_id", ...)`

4. **Search for any other references** to the old path in `frontend/src/`:
   ```
   Grep: "logs/by-execution" or "logs-by-execution" in frontend/src/
   ```
   Update any additional references found.

5. **Regenerate OpenAPI spec:**
   ```bash
   uv run python scripts/export_schemas.py
   ```

6. **Regenerate TypeScript types:**
   ```bash
   cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts
   ```

7. **Verify the frontend builds:**
   ```bash
   cd frontend && npm run build
   ```
   Fix any TypeScript errors from the tightened types (bare `string` fields becoming union literals). Frontend components using `status` fields may need updated type annotations or switch/case branches.

8. **Run the full backend test suite:**
   ```bash
   timeout 300 uv run pytest -n 2 -x
   ```

9. **Run Pyright:**
   ```bash
   uv run pyright
   ```

10. **Verify schema freshness** — the CI check `tools/check_schemas_fresh.py` must pass:
    ```bash
    uv run python tools/check_schemas_fresh.py
    ```

## Focus
- The `generated-types.ts` file is 2018 lines — after regeneration, `string` fields on affected models will become union types (e.g., `"success" | "error" | "cancelled" | "timed_out"`). TypeScript callers that were using `string` comparisons will still work. Callers with exhaustive switch/case may need a new branch.
- The frontend `APP_STATUS_MAP` in `frontend/src/utils/status.ts` already handles all `ResourceStatus` values — no changes expected there.
- The `openapi.json` file lives at `frontend/openapi.json` — the export script writes there.
- Check for any `generated-types.ts` imports that reference `ActivityFeedEntry`, `HandlerInvocation`, `JobExecution`, `JobSummary` — these model types may have changed shape (new `InvocationStatus` enum type in the schema).

## Verify
- [ ] AC#9: Frontend code calls `/api/executions/{execution_id}` — no references to `/api/logs/by-execution/` remain in `frontend/src/`
- [ ] AC#11: `openapi.json` and `generated-types.ts` are regenerated; `tools/check_schemas_fresh.py` passes; Literal types appear as string enums in the OpenAPI spec
- [ ] AC#12: `uv run pytest -n 2` passes with no failures; `uv run pyright` passes with no new errors; `cd frontend && npm run build` succeeds
