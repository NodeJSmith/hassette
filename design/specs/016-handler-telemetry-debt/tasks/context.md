# Context: Handler UI and Telemetry Structural Debt

## Problem & Motivation

Oversized files and duplicated patterns across the handler UI and telemetry layers create a readability ceiling that causes AI agents to miss existing utilities and create redundant code. Parallel stat-cell builders in two frontend components, a 25-prop layout component serving 5 roles, 400-800 line Python modules with flat internal structure, repeated UNION query scaffolding, and oversized test files mixing unrelated concerns all contribute to this. The primary consumer of this codebase is AI agents, so clean lines and small scopes are critical for code discovery.

## Visual Artifacts

None.

## Key Decisions

1. **Flat sibling file splits, not package-with-re-exports** — all importers updated to point at the specific submodule. Explicit imports help AI agents find the right file. Larger diff but more discoverable.
2. **Full compositor decomposition** — HandlerDetailLayout becomes a thin layout shell (`testId` + `children` only) with 3 extracted sub-components (`DetailHeader`, `ExecutionSection`, `RegistrationFooter`). Addresses root cause (too many responsibilities) not symptom (too many props).
3. **Shared stat-cell builder via normalized input** — a `buildCommonStatCells` function takes a `CommonStatInput` object; callers construct the input from their domain type and append domain-specific cells.
4. **UNION arm builder as a helper function** — lives in `helpers.py` alongside existing clause builders. Returns `(sql_fragment, params)` tuple. Not a class or template method — exactly 3 call sites.
5. **CSS splits co-located with sub-components** — each extracted component gets its own `.module.css`. `job-detail.tsx` imports `.runNow` from the layout CSS.
6. **New unit tests for all extracted components** — `DetailHeader`, `ExecutionSection`, `RegistrationFooter`, and `stat-cell-builders` each get a co-located test file.
7. **`createWrapper` migration** — `app-detail.test.tsx`'s local wrapper replaced with `renderWithAppState()` + `stateOverrides` during the split.

## Constraints & Anti-Patterns

- No behavior changes. Any bug discovered during implementation gets a separate commit.
- Do NOT introduce package-with-re-exports (no `__init__.py` re-export directories for the splits).
- Do NOT touch `tokens.css` or make visual changes.
- Do NOT reorganize `test_telemetry_query_service_aggregates.py` — it's already well-organized and out of scope.
- Do NOT use `from __future__ import annotations`.
- Do NOT use `Optional[X]` — use `X | None`.
- The PR must carry the `no-visual-change` label — CI (`pr-screenshots.yml`) blocks PRs touching `frontend/src/**/*.tsx` or `*.css` without visual evidence or this label. This is a structural refactoring with no rendered changes.

## Design Doc References

- `## Architecture` — full component interfaces, CSS distribution table, SQL helper signature, split groupings
- `## Replacement Targets` — what old code is being replaced and by what
- `## Test Strategy` — which tests to adapt, new coverage needed, nothing to remove
- `## Impact → Changed Files` — exhaustive file inventory with change verbs
- `## Edge Cases` — import breakage, re-export drift, test coverage gaps, GlobalSummary cross-import
- `## Key Constraints` — behavioral invariants and explicit exclusions

## Convention Examples

### SQL clause builders

**Source:** `src/hassette/core/telemetry/helpers.py`

```python
def source_tier_clause(source_tier: QuerySourceTier, alias: str) -> tuple[str, dict[str, str]]:
    match source_tier:
        case "all":
            return ("", {})
        case "app" | "framework":
            return (f"AND {alias}.source_tier = :source_tier", {"source_tier": source_tier})
        case _ as unreachable:
            assert_never(unreachable)
```

The UNION arm builder follows this same `(fragment, params)` return pattern.

### DetailStatsCell data-driven rendering

**Source:** `frontend/src/components/shared/detail-stats.tsx`

```typescript
export interface DetailStatsCell {
  label: string;
  value: string | number;
  tone?: StatusKind;
}
```

The shared stat-cell builder produces this type. No new interface needed.

### test_utils re-export pattern

**Source:** `src/hassette/test_utils/__init__.py`

```python
from .web_helpers import make_full_snapshot as make_full_snapshot
from .web_helpers import make_job as make_job
from .web_helpers import make_manifest as make_manifest
from .web_helpers import make_real_job as make_real_job
```

These 4 re-exports are load-bearing and must be updated to point at the new submodule paths.
