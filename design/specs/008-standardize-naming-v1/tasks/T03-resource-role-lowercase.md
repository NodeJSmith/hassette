---
task_id: "T03"
title: "Normalize ResourceRole values to lowercase via auto()"
status: "done"
depends_on: []
implements: ["FR#8", "AC#3"]
---

## Summary
Change `ResourceRole` in `src/hassette/types/enums.py` from explicit Title-case string values to `auto()`, producing lowercase values that match every other `StrEnum` in the file. Regenerate the OpenAPI schema and frontend types. Fix frontend test fixtures that use invalid role values.

## Target Files
- modify: `src/hassette/types/enums.py`
- modify: `frontend/src/pages/diagnostics.test.tsx`
- modify: `frontend/src/api/generated-types.ts` (via schema regeneration)
- read: `src/hassette/core/runtime_query_service.py`
- read: `src/hassette/web/models.py`
- read: `design/specs/008-standardize-naming-v1/design.md`
- read: `design/specs/008-standardize-naming-v1/tasks/context.md`

## Prompt
Normalize `ResourceRole` enum values to lowercase.

**Step 1: Modify `ResourceRole` in `src/hassette/types/enums.py`**

Change from explicit Title-case strings to `auto()`:

```python
# Before (around line 247)
class ResourceRole(StrEnum):
    CORE = "Core"
    BASE = "Base"
    SERVICE = "Service"
    RESOURCE = "Resource"
    APP = "App"
    UNKNOWN = "Unknown"

# After
class ResourceRole(StrEnum):
    CORE = auto()
    BASE = auto()
    SERVICE = auto()
    RESOURCE = auto()
    APP = auto()
    UNKNOWN = auto()
```

Verify `auto` is already imported at the top of `enums.py` (it should be — other enums use it).

**Step 2: Verify no downstream code changes needed**

Read `src/hassette/core/runtime_query_service.py` (lines 181, 276) and `src/hassette/web/models.py` (line 62). These use `data.role.value` and `svc.role` to serialize the enum — they will naturally produce lowercase values now. No code changes needed in these files.

**Step 3: Fix frontend test fixtures**

In `frontend/src/pages/diagnostics.test.tsx`, the fixtures use:
- `role: "core"` (lines 38, 48) — already lowercase, matches new values
- `role: "storage"` (lines 134, 254) — NOT a valid `ResourceRole` value at all

Change `"storage"` to a valid lowercase `ResourceRole` value (e.g., `"service"`) in the test fixtures.

**Step 4: Regenerate OpenAPI schema and frontend types**

```bash
uv run python scripts/export_schemas.py --types
cd frontend && npm run build
```

**Step 5: Verify**

```bash
grep -n '"Core"\|"Service"\|"App"\|"Base"\|"Resource"\|"Unknown"' src/hassette/types/enums.py
```
This should return no matches.

## Focus
- All code referencing `ResourceRole.SERVICE`, `ResourceRole.APP`, etc. uses the enum member names, not string values. Member names are unchanged — only `.value` changes. No code changes needed outside `enums.py` and the test fixtures.
- `ResourceRole` has no database persistence (confirmed: `src/hassette/schemas/telemetry_models.py` has no `role` column). No migration needed.
- The frontend diagnostics page maps `role` as a string but doesn't currently render it as visible text — this is a data/typing change, not a visible UI change.
- Run `cd frontend && npm install` first if this is a fresh worktree (node_modules aren't shared across worktrees).

## Verify
- [ ] FR#8: `ResourceRole` members use `auto()` producing lowercase string values
- [ ] AC#3: `grep -n '"Core"\|"Service"\|"App"\|"Base"\|"Resource"\|"Unknown"' src/hassette/types/enums.py` returns no matches; frontend types are regenerated; frontend test fixtures use valid lowercase values
