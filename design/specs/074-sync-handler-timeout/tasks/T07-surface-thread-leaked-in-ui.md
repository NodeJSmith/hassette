---
task_id: "T07"
title: "Surface thread-leaked marker in web API and monitoring UI"
status: "done"
depends_on: ["T06"]
implements: ["FR#3"]
---

## Summary
Make the `thread_leaked` marker visible where operators watch executions: add it to the web API response/WebSocket model, regenerate the frontend types and schemas, and display it in the monitoring UI alongside the timeout status. A field persisted in the DB but never surfaced is, per the project's design-completeness rule, a bug — the leak must be observable in the UI, not just queryable in SQLite.

## Prompt
1. **Backend model** — add `thread_leaked` to `ExecutionCompletedData` in `src/hassette/web/models.py:248-270` (and any other execution response/WS model that mirrors execution-record fields — search `web/models.py` for `status`/`duration_ms` siblings). Default it so older messages without the field still validate.

2. **Regenerate schemas and types** — run `uv run python scripts/export_schemas.py --types` (regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`). In a worktree, first `cd frontend && npm install` (per `.claude/rules/frontend-worktree.md`). `ws-types.ts` is generated, never hand-edited.

3. **UI** — display the leak marker in the executions/handlers monitoring view. Find the component that renders execution rows / the timeout status (search `frontend/src` for where `status`/`timed_out` is rendered) and add a clear indicator (badge/icon) when `thread_leaked` is set, distinct from a plain timeout. Follow the CSS-module + shared-component conventions in `CLAUDE.md` (use the shared `Badge` component rather than raw `ht-badge`). Keep it quiet — a small marker, not a loud banner.

4. **Verify the build** — `cd frontend && npm run build` must pass with the regenerated types. Run any frontend tests covering the executions view.

5. **Visual check** — capture a before/after of the executions view via the project's demo/visual-QA path if practical (per the UI memory: real HA + hassette + Vite, not the e2e mock). At minimum confirm the marker renders for a `thread_leaked=1` row.

Because this changes a UI surface, run `uv run nox -s e2e` before the task is considered done (do not run `pytest -n auto`).

## Focus
- Schema freshness is enforced by CI (`tools/check_schemas_fresh.py` pre-push; `tests.yml` git-diff on `ws-types.ts`/`generated-types.ts`). Regenerate and commit the generated files or CI fails.
- The WS `ExecutionCompletedData` is the live execution feed; the field must be optional/defaulted so a backend that hasn't been restarted (or an in-flight message) doesn't break the frontend parse.
- This is a quiet, secondary signal — match the design's intent ("a friend tapping you on the shoulder"), not an alarm. Use the shared `Badge`/`Chip` component and existing tokens; do not add raw hex or new global CSS classes (see `CLAUDE.md` CSS architecture + `tokens.css`).
- Gap-check origin: this task closes the `web/models.py` → frontend-types gap surfaced during planning.

## Verify
- [ ] FR#3: `thread_leaked` appears in the execution web/WebSocket model, the regenerated frontend types include it, and the monitoring UI renders a distinct marker for a leaked-thread execution (verified in a built frontend, not just source).
