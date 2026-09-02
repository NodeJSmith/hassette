---
task_id: "T04"
title: "Regenerate schemas, update docs, and verify build"
status: "done"
depends_on: ["T01", "T02", "T03"]
implements: ["AC#13", "AC#14"]
---

## Summary

Final integration task: regenerate the OpenAPI spec and TypeScript types, update the CLI docs page with the new subcommands and flags, and verify that lint, type checking, and the frontend build all pass. This runs after all implementation tasks are complete.

## Target Files

- modify: `frontend/openapi.json`
- modify: `frontend/src/api/generated-types.ts`
- modify: `docs/pages/cli/commands.md`
- read: `design/specs/107-instance-actions-ui-cli/design.md`

## Prompt

### Schema regeneration

Run the standard schema regeneration command:

```bash
uv run python scripts/export_schemas.py --types
```

This regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`, and `ws-validator.generated.ts`. The backend routes for per-instance actions already exist, so the OpenAPI spec may already contain them — regenerate regardless to ensure freshness.

### Documentation updates

Update `docs/pages/cli/commands.md`:

1. **Subcommands table** (around line 92-98): Add three rows for `start`, `stop`, `reload` with their descriptions and API endpoints.

2. **Per-command Flags table** (around line 150): Add entries showing `--instance` as accepted by `start`, `stop`, `reload` with action-appropriate wording: "Targets a specific app instance (index or name)" rather than the existing "Filters to..." used by read-only commands. Add `--yes` as accepted by `stop` and `reload` with description "Skip confirmation prompt".

3. **Shared Flags table** (around line 347): Update the `--instance` entry to include `start`, `stop`, `reload` in its list of commands that accept it, and update the description text to cover both uses: e.g., "Filters to (read commands) or targets (action commands) a specific app instance (index or name)."

### Build verification

Run lint and type checking:

```bash
prek -a
```

Run the frontend build:

```bash
cd frontend && npm run build
```

Both must pass with zero errors.

## Focus

- The schema regeneration command is `uv run python scripts/export_schemas.py --types` per CLAUDE.md, not `export_schemas.py` alone.
- `docs/pages/cli/commands.md` has three distinct tables that mention `--instance`: the per-command Subcommands table, the per-command Flags table, and the Shared Flags table further down. All three need updates.
- Use action-appropriate wording for `--instance` on the mutating commands: "Targets a specific app instance" not "Filters to a specific app instance" — the latter implies a query filter, not an action target.
- The `--yes` flag only applies to `stop` and `reload`, not `start`.
- If `prek -a` or `npm run build` fails, fix the issues before marking complete. Common causes: import ordering (ruff), unused imports after regeneration, type mismatches from regenerated types.

## Verify

- [ ] AC#13: `prek -a` passes (lint + type check) with zero errors
- [ ] AC#14: `cd frontend && npm run build` succeeds with regenerated types
