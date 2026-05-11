# Design: Activity Feed Redesign

**Date:** 2026-05-06
**Status:** draft
**Scope-mode:** hold
**Research:** design/research/2026-05-06-dashboard-activity-ux/research.md, design/research/2026-05-06-cascading-failure-grouping/research.md

## Problem

The overview page's recent activity feed shows every handler invocation chronologically. On a healthy system with periodic handlers, this produces 12+ identical success rows per hour for a single handler. The user already knows what's firing — they wrote the automations. The feed answers a question nobody is asking while failing to answer the one that matters: "does anything need my attention?"

When failures occur, the problem inverts. A single root cause (e.g., a connectivity interruption) triggers many downstream handler failures simultaneously. The feed shows each failure as a separate row, burying the root cause in symptoms. The user must mentally correlate 12 error rows with identical timestamps to understand that one thing went wrong, not twelve.

The activity feed is the weakest component on an otherwise well-designed overview page. It undermines the greeting system's diagnostic intent by defaulting to noise in both healthy and unhealthy states.

## Goals

- When everything is healthy, the activity area communicates "all clear" in a single glance — not 20 identical rows
- When failures occur, related errors are grouped into a single incident with affected count, not listed individually
- The feed surfaces what needs attention, ranked by severity, not by timestamp
- The transition between "all clear" and "something needs attention" is immediate and unmissable

## User Scenarios

### Hobbyist operator: Technical home automation user

- **Goal:** Quickly determine if anything needs attention
- **Context:** Opens the overview tab with a question already in mind, wants to close the tab within seconds

#### Healthy check-in

1. **Opens the overview page**
   - Sees: Greeting with "all apps are healthy" subtitle, summary cards
   - Sees: Activity area showing a deliberate "all clear" state with proof-of-life (last successful invocation timestamp, total runs in window)
   - Decides: Nothing needs attention
   - Then: Closes the tab

#### Single handler failure

1. **Opens the overview page**
   - Sees: Greeting subtitle reflects the failure state
   - Sees: Activity area shows one error entry — the failing handler with error type, app name, time, and a link to investigate
   - Decides: Needs to look into it
   - Then: Clicks through to the app detail page for that handler

#### Cascading failure (connectivity loss)

1. **Opens the overview page**
   - Sees: Greeting reflects multiple failures
   - Sees: Activity area shows one grouped incident — "ConnectionClosedError — 12 handlers across 3 apps" with a time range
   - Decides: This is a connectivity issue, not 12 separate bugs
   - Then: Checks the system card for WebSocket status, or expands the group to see affected handlers

## Functional Requirements

- **FR#1** When no errors exist in the current time window, the activity area displays a healthy state indicator instead of individual invocation rows
- **FR#2** The healthy state indicator shows the total successful invocation count and the timestamp of the most recent invocation as proof-of-life
- **FR#3** When errors exist, the activity area displays only error entries — successful invocations are not shown
- **FR#4** Errors with the same error type that occur within a configurable time gap (default 30 seconds) are grouped into a single entry
- **FR#5** A grouped error entry displays the error type, the count of affected invocations, the list of affected app names, and the time range of the group
- **FR#6** A grouped error entry is expandable to show the individual failures within the group
- **FR#7** The minimum group size for temporal grouping is 3 — two coincidental errors with the same type remain as separate entries
- **FR#8** Error entries link to the relevant app detail page for investigation
- **FR#9** The feed updates in real-time via existing WebSocket events without requiring a page refresh
- **FR#10** The feed respects the user's selected time window (since restart, 1h, 24h, 7d)

## Edge Cases

- **Zero activity in window**: No invocations at all (not even successes). The healthy state indicator should still render, but with "no activity in this window" instead of a run count. Distinct from the existing "quiet hour" state which means apps are running but dormant.
- **Mixed grouped and ungrouped errors**: Some error types cluster (cascading failure) while others are isolated. The feed shows grouped incidents alongside individual error entries, sorted by most recent.
- **Rapid reconnect**: WebSocket drops and reconnects within seconds. A burst of errors followed by immediate recovery. The group should show the full incident even though the system is now healthy.
- **Single app failure vs cascading**: One app failing repeatedly (e.g., bad config) produces errors with the same error type and app but no temporal burst. These should NOT be grouped as a cascading incident — they're separate invocations of the same broken handler. The temporal gap threshold (30s) prevents this: if failures are spaced minutes apart, they remain individual entries.
- **Framework-tier errors**: Errors from framework internals (not user apps) should appear in the feed if the tier filter includes them.
- **Grouping query failure**: If the grouped error query fails (DB unavailable, slow query), the activity area falls back to the healthy state indicator with a stale-data visual treatment (reduced opacity). It does not fall back to the old chronological feed or show an error banner — the greeting system already surfaces system-level failures via the "system" summary card.

## Acceptance Criteria

- **AC#1** On a healthy system with 10+ successful handler invocations in the last hour, the activity area shows a single healthy-state indicator, not individual invocation rows (FR#1, FR#2)
- **AC#2** When 5+ handlers fail with the same error type within 10 seconds, the feed shows one grouped entry with the correct count and affected apps (FR#4, FR#5, FR#7)
- **AC#3** Expanding a grouped entry reveals the individual failures with their timestamps and handler names (FR#6)
- **AC#4** An isolated error (no temporal cluster) appears as a standalone entry with error type, app name, and timestamp (FR#3, FR#8)
- **AC#5** Clicking an error entry navigates to the relevant app detail page (FR#8)
- **AC#6** When a new error arrives via WebSocket, it appears in the feed without page refresh (FR#9)
- **AC#7** Changing the time window preset updates the feed content accordingly (FR#10)

## Key Constraints

- No schema migrations — grouping is query-time only, using the existing `error_type` and `execution_start_ts` columns
- The existing greeting system and its 5 system states are not modified — the activity feed adapts to the state the greeting already computes
- No left-border accents on error groups (design system constraint from context.md)
- Status colors (`--err`, `--warn`) used only for semantic status communication, not decoration

## Dependencies and Assumptions

- Assumes `error_type` is consistently populated for all failure records. The research confirmed this: `track_execution()` in `utils/execution.py` captures `type(exc).__name__` uniformly.
- Assumes the existing `idx_hi_status_time` and `idx_je_status_time` indices make error-time queries efficient at Hassette's typical data volume.
- Depends on the existing WebSocket event payloads (`WsInvocationCompletedPayload`, `WsExecutionCompletedPayload`) which already include `error_type`.

## Architecture

### Backend: Grouped error query

Add a new method `get_grouped_errors()` to `TelemetryQueryService` (src/hassette/core/telemetry_query_service.py). This reuses the UNION ALL pattern from the existing `get_recent_errors()` method (line 682) which already JOINs across `handler_invocations` and `job_executions` with listener/job metadata.

**Two-pass algorithm:**
1. SQL: Fetch recent error records ordered by `execution_start_ts DESC`, filtered by time window and optional `source_tier`. Same query structure as `get_recent_errors()` but returning `ActivityFeedEntry`-shaped rows with `error_type`.
2. Python: Walk the sorted list and merge consecutive errors with the same `error_type` that fall within the gap threshold (30s). Each group becomes a `GroupedErrorEntry` containing: `error_type`, `count`, `first_ts`, `last_ts`, `affected_app_keys: list[str]`, `entries: list[ActivityFeedEntry]`, and a representative `error_message`.

**New response model:** Add `GroupedErrorEntry` to `telemetry_models.py` alongside `ActivityFeedEntry`. The activity endpoint returns a union: either grouped entries or individual entries, plus a `healthy_summary` object when no errors exist.

**Endpoint change:** Modify `GET /telemetry/dashboard/activity` (or add a new endpoint) to return the grouped structure. Include a `healthy` boolean and `last_invocation_ts` / `total_invocations` fields for the healthy state.

### Frontend: Redesigned activity area

Replace the `RecentActivityFeed` component in `dashboard.tsx` with a new component that handles two states:

**Healthy state:** A compact card showing proof-of-life. Uses the existing `systemState` from the dashboard (which already computes `healthy`, `quiet`, etc.). Displays total invocation count and recency of last invocation. Styled as a receded card (matching current `ht-card--receded` pattern) with muted ink — deliberate understatement to communicate "nothing noteworthy."

**Exception state:** A list of error entries (grouped or individual). Each grouped entry renders as a collapsible row showing: StatusShape (err), error type in mono, affected count badge, affected app names, time range. Expanding reveals the individual invocations within the group. Individual (ungrouped) error entries render as they do today but with the app_key as a link.

**Real-time updates:** The existing `WsInvocationCompletedPayload` stream already includes `error_type`. The component applies the same temporal grouping logic client-side for live updates: when a new error arrives with the same `error_type` as the most recent group within 30s, it merges into that group. Otherwise it creates a new entry.

### Files affected

| File | Change |
|---|---|
| `src/hassette/core/telemetry_query_service.py` | New `get_grouped_errors()` method (~50-80 lines) |
| `src/hassette/core/telemetry_models.py` | New `GroupedErrorEntry` model, modified activity response model |
| `src/hassette/web/models.py` | New response schema for grouped activity |
| `src/hassette/web/routes/telemetry.py` | Modified activity endpoint |
| `frontend/openapi.json` | Regenerated |
| `frontend/src/api/generated-types.ts` | Regenerated |
| `frontend/src/pages/dashboard.tsx` | Redesigned `RecentActivityFeed` component |
| `frontend/src/global.css` | New styles for healthy state and grouped error entries |

## Alternatives Considered

**Keep the chronological feed with grouping only:** Group repeated handler invocations ("garage_proximity.recurring_occupancy_check — 12 runs, last 2m ago") without switching to exception-first. Rejected because it still shows noise when healthy — the user doesn't need to see that their recurring check ran 12 times.

**Replace with a simple status banner:** Show only "All apps healthy" or "3 apps failing" with no detail. Rejected because it loses the diagnostic value — the user can't see which error type or how many handlers were affected without drilling into a separate page.

**Error-type-only grouping (no temporal window):** Group all errors of the same type within the time window regardless of when they occurred. Simpler to implement but loses the ability to distinguish "one disconnect caused 12 failures" from "12 separate intermittent failures over 24 hours." Rejected for the activity feed but noted as potentially useful for a summary badge.

## Test Strategy

**Backend:**
- Unit tests for the grouping algorithm: verify that errors within the gap threshold merge, errors outside the threshold remain separate, minimum group size is respected, and mixed error types produce correct groups
- Integration tests for the modified activity endpoint: verify the response shape, healthy state detection, and time window filtering
- Edge case tests: zero activity, single error, rapid burst then recovery, framework-tier filtering

**Frontend:**
- Component tests for the healthy state rendering (mock API returns zero errors, verify proof-of-life display)
- Component tests for grouped error rendering (mock API returns grouped entries, verify expand/collapse, count display, app names)
- Component tests for real-time grouping (simulate WS events arriving, verify client-side merge logic)
- E2E: verify the healthy state → error state transition on the live overview page

## Documentation Updates

- Update `design/context.md` Component Inventory → "Recent activity feed" section to reflect the new exception-first behavior and healthy state
- No docs site changes needed — the activity feed is an internal monitoring UI, not a user-facing API

## Impact

**Backend:** Additive changes only. New query method, new models, modified endpoint. Existing queries untouched. No schema migration.

**Frontend:** The `RecentActivityFeed` component is replaced. No other dashboard components change. The greeting system and system state detection are reused without modification.

**Blast radius:** Low. The activity feed is self-contained on the overview page. The backend changes are additive (new method + new models). The existing activity endpoint can be versioned or replaced in place since it's only consumed by the dashboard.

## Open Questions

None — all resolved during design review:

- **Gap threshold**: Hardcoded at 30 seconds for v1. Revisit if users report false grouping.
- **Expanded group detail**: Handler names and timestamps only — no inline tracebacks. Tracebacks available on the app detail page.
- **"Full log →" link**: Retained on the healthy state card. Users may browse logs even when nothing needs attention.
