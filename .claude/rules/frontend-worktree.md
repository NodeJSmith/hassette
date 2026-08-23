# Frontend in Worktrees

Git worktrees do not share `node_modules/`. Before running frontend builds, tests, or type generation in a worktree, install dependencies:

```bash
cd frontend && npm install
```

One-time per worktree. `package-lock.json` is shared via the worktree's file copy, so installs are deterministic.

## Schema regeneration

After modifying backend response models (`web/models.py`, `src/hassette/schemas/*.py`) or route signatures:

1. Regenerate schemas and all TypeScript types in one command:
   ```bash
   uv run python scripts/export_schemas.py --types
   ```
   This regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`, and `ws-validator.generated.ts`.

2. Rebuild the frontend to verify:
   ```bash
   cd frontend && npm run build
   ```

Individual type generation can also be run standalone:
- REST API types: `cd frontend && npm run types`
- WebSocket types: `cd frontend && npm run ws-types`
- WS validators: `cd frontend && npm run validators`

`ws-types.ts` is generated from `ws-schema.json` via `scripts/generate-ws-types.cjs` — do not edit it by hand. `ws-validator.generated.ts` is generated from `ws-schema.json` via `scripts/compile-validators.cjs` — do not edit it by hand.

The pre-push hook (`tools/check_schemas_fresh.py`) checks `ws-schema.json` and `openapi.json` freshness locally. CI additionally checks `ws-types.ts`, `generated-types.ts`, and `ws-validator.generated.ts` via git-diff in `.github/workflows/tests.yml`.
