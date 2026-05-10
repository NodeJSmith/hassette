# Context: App Detail Overview Tab

## Problem & Motivation
The app detail page lands on the handlers tab with an empty right panel, providing no at-a-glance summary of how an app is doing. Users must click into individual handlers to see invocation history or errors. The overview tab fills this gap: a default landing page that surfaces health, errors, and activity without requiring handler-by-handler navigation. It should be useful for error investigation, healthy-state checks, and post-reload verification.

## Visual Artifacts
None.

## Key Decisions
1. Overview tab is the new default landing (replaces handlers as default). Existing `/apps/{key}/handlers` routes still work — only the bare `/apps/{key}` default changes.
2. Error spotlight shows at most 3 expanded error entries with a "show N more" control. The section is absent (not rendered) when nothing is failing.
3. Handler health grid shows ALL handlers/jobs — failing items first (expanded), healthy items compact below. Each links to the handlers tab with that handler pre-selected.
4. Recent activity comes from a new backend endpoint (`GET /telemetry/app/{app_key}/activity`) that uses the proven UNION ALL pattern already in `get_per_app_activity_buckets()`. The `ActivityFeedEntry` model already exists in `telemetry_models.py`.
5. Real-time updates follow the existing `useDebouncedEffect` + `invocationCompleted`/`executionCompleted` WebSocket pattern.
6. Backend endpoints are in scope — no artificial constraint to frontend-only changes.

## Constraints & Anti-Patterns
- REUSE existing components: `ErrorBanner`, `StatusShape`, `EmptyState`, `LogTable`, `useScopedApi`, `useDebouncedEffect`, `formatRelativeTime`, `formatDurationOrDash`, `buildItems` from handler-list.tsx, `handlerKindLabel`/`statusToKind` from utils/status.
- Do NOT recreate any component that already exists. If a component is close but not exact, extend it rather than duplicating.
- No status colors on non-status elements.
- No left-border accents on error entries.
- Error spotlight section is absent when nothing is failing (no "no errors found" empty state).
- Backend endpoint must accept `limit`, `since`, and `source_tier` parameters.
- No `from __future__ import annotations`. No `Optional[X]` — use `X | None`.
- The handlers tab's health strip (`HandlersHealthStrip`) stays inside the handlers tab — do NOT move it above the tab bar. The overview tab's sections provide the same diagnostic data.

## Design Doc References
- "## Problem" — what is broken and why it matters
- "## Architecture" — backend endpoint details and frontend component structure
- "## Functional Requirements" — FR#1 through FR#14, each one testable behavior
- "## Edge Cases" — 7 edge cases including many-failures cap and empty states
- "## Key Constraints" — 6 explicit technical constraints
- "## Dependencies and Assumptions" — existing models, hooks, and patterns to reuse
