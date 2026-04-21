# Frontend in Worktrees

Git worktrees do not share `node_modules/`. Before running frontend builds, tests, or type generation in a worktree, install dependencies:

```bash
cd frontend && npm install
```

One-time per worktree. `package-lock.json` is shared via the worktree's file copy, so installs are deterministic.

## Schema regeneration

After modifying backend response models (`web/models.py`, `telemetry_models.py`) or route signatures:

1. Regenerate OpenAPI spec and WebSocket schema:
   ```bash
   uv run python scripts/export_schemas.py
   ```
2. Regenerate TypeScript types:
   ```bash
   cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts
   ```
3. Rebuild the frontend to verify:
   ```bash
   cd frontend && npm run build
   ```

CI checks schema freshness via `tools/check_schemas_fresh.py` — if you skip step 1-2, the pre-push hook will catch it.
