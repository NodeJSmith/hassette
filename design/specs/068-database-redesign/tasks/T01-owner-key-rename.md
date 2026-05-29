---
task_id: "T01"
title: "Rename app_key to owner_key via mechanical codemod"
status: "planned"
depends_on: []
implements: ["FR#12", "FR#13", "FR#14", "AC#5", "AC#9"]
---

## Summary
Rename every occurrence of `app_key` to `owner_key` across the entire codebase — backend, frontend, tests, and documentation. This is a mechanical find-and-replace that must land as a dedicated commit before any schema changes, since the ~613 occurrences would obscure structural diffs if bundled.

## Prompt
Perform a codemod renaming `app_key` to `owner_key` across the entire hassette codebase. This includes:

**Backend (src/hassette/):**
- DB column names in migration SQL and repository queries
- Pydantic model fields (`ListenerRegistration.app_key`, `ScheduledJobRegistration.app_key` in `core/registration.py`)
- All 10+ REST response models in `web/models.py` (e.g., `InvocationCompletedData.app_key`)
- WS payload fields in `events/hassette.py` (`InvocationCompletedPayload`, `ExecutionCompletedPayload`)
- Query service and repository references
- `runtime_query_service.py` meta dict values and method params
- `command_executor.py`, `bus_service.py`, `scheduler_service.py`, `app_lifecycle_service.py` param names
- `types/types.py` helper function `is_framework_key` if it takes `app_key` params

**Frontend (frontend/src/):**
- Dynamic dict key in `hooks/use-websocket.ts` (`msg.data.app_key` → `msg.data.owner_key`)
- Structural cast in `components/app-detail/recent-activity-section.tsx` (line ~126-127)
- `state/create-app-state.ts` signal names
- All other `.ts`/`.tsx` files referencing `app_key` or `appKey` (camelCase in TS)

**Tests:**
- All test files using `app_key` in assertions, fixtures, or mock data

**Documentation:**
- `CLAUDE.md`, docstrings, docs pages

**Approach:** Use `sed` or similar for the mechanical rename. Then manually verify the three frontend locations that need structural attention: `use-websocket.ts` dynamic dict key, `recent-activity-section.tsx` structural cast, and `create-app-state.ts` signal names. Run `uv run pyright` and `cd frontend && npm run build` to verify.

**Key constraint:** Do NOT rename `app_key` in `AppConfig` or application-level config — this rename targets the *telemetry/registration* field, not the app configuration key. Grep for context before renaming.

## Focus
- The rename must be exhaustive — AC#9 requires zero remaining references to `app_key` in production code.
- `recent-activity-section.tsx:126-127` has a structural type assertion `(e: { app_key: string })` that TypeScript type regeneration will NOT catch — it must be manually updated.
- `use-websocket.ts` uses `msg.data.app_key` as a dynamic dictionary key — string-based, not type-checked.
- `registration.py` has both `ListenerRegistration.app_key` and `ScheduledJobRegistration.app_key` — easy to miss.
- `test_utils/web_mocks.py` mocks return values that include `app_key` — must update.

## Verify
- [ ] FR#12: All DB column references use `owner_key` instead of `app_key`
- [ ] FR#13: All REST response models and WS payload fields use `owner_key`
- [ ] FR#14: All frontend files use `owner_key`/`ownerKey` instead of `app_key`/`appKey`
- [ ] AC#5: `uv run pyright` passes with zero errors
- [ ] AC#9: `grep -r "app_key" src/hassette/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx"` returns zero hits (excluding `AppConfig` and comments)
