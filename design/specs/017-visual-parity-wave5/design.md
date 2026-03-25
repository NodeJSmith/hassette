# Design: Visual Parity Wave 5 — Final Polish

**Date:** 2026-03-24
**Status:** implemented
**Spec:** N/A (gap analysis serves as spec: `design/research/2026-03-20-visual-parity-gaps.md`)

## Problem

The Preact SPA migration closed 24 of 30 visual parity gaps across waves 1–4. Five Low/Medium gaps remain, making the UI feel unfinished compared to the old Jinja2 version. These are all frontend-only fixes that surface data already available from the API.

### Remaining Gaps

| ID | Sev | Page | Description |
|----|-----|------|-------------|
| GAP-D1 | Low | Dashboard | App cards don't show error rate percentage |
| GAP-D3 | Low | Dashboard | Error feed omits `handler_method` |
| GAP-D4 | Low | Dashboard | Error feed badge shows `kind` instead of exception type |
| GAP-AD2 | Medium | App Detail | Instance metadata shows `instance_name` instead of PID (`owner_id`) |
| GAP-AD11 | Low | App/Logs | Only Timestamp column sortable in log table |

## Non-Goals

- Multi-instance changes (GAP-MI1/A5/AD3) — separate wave
- New features beyond visual parity with the old Jinja2 UI
- Backend API changes beyond what's needed for server-side error rate classification
- CSS design token changes
- Page-transition loading indicator (GAP-MI5) — dropped after challenge review: SPA route transitions are instant (all components bundled), per-page Spinners already communicate loading state, and a fake progress bar creates contradictory signals when API calls outlast the animation timer

## Architecture

### Fix 1: Error rate on dashboard app cards (GAP-D1)

**File:** `frontend/src/components/dashboard/app-card.tsx`

The component already computes `total` and `errors` (lines 13–14) but only passes them to `HealthBar`. Add a text display of the error rate percentage when `total > 0`.

```
const rate = total > 0 ? (errors / total) * 100 : 0;
```

Display as e.g. `"2.1% errors"` with danger/warn color. Color the text using `errorRateToVariant(app.error_rate_class)` from the server-provided classification. `DashboardAppGridEntry` now includes `error_rate: float` and `error_rate_class: str` (added to the backend model and telemetry route). This follows the project's established pattern where the server owns classification thresholds and the client maps labels to CSS classes. Show nothing when `error_rate === 0`.

Place the error rate text below the handler/job counts line, matching the old UI's position.

### Fix 2: Error feed handler method and badge content (GAP-D3 + GAP-D4)

**File:** `frontend/src/components/dashboard/error-feed.tsx`

The `DashboardErrorEntry` type already includes `handler_method?: string` and `job_name?: string` — both sent by the API but not rendered.

**GAP-D3:** Add `handler_method` (or `job_name` for job errors) to the error entry subtitle, after the `app_key` link. Format: `app_key · handler_method`.

**GAP-D4:** Change the badge text from `err.kind` to `err.error_type`. The old UI showed the exception type name (e.g. "ValueError") as a danger badge. Keep the `ht-tag--${err.kind}` class for color coding but display `err.error_type` as the badge text.

**Edge cases:**
- **Empty `error_type`:** Render `err.error_type || err.kind` as fallback — never display a blank badge.
- **Long exception names:** Module-qualified names like `homeassistant.exceptions.ServiceNotFound` will overflow the badge. Truncate to the last dotted component for display (e.g., `"ServiceNotFound"`). Add `max-width` + `text-overflow: ellipsis` CSS on the badge as a safety net.
- **Unknown `kind` values:** Guard the `ht-tag--${err.kind}` CSS interpolation by mapping through a known set (`"handler"` → `"handler"`, `"job"` → `"job"`, default → `"neutral"`). This prevents silent CSS fallback if the backend adds a third kind value. Pattern already exists in `status.ts:35–40`.

**Key stability:** Change the ErrorEntry key from `${err.timestamp}-${err.app_key}-${i}` to `${err.listener_id ?? err.job_id ?? err.timestamp}-${err.app_key}`. The `listener_id` and `job_id` fields are stable unique identifiers already present on `DashboardErrorEntry`, eliminating both timestamp collision and positional index coupling on burst errors.

### Fix 3: Instance metadata PID display (GAP-AD2)

**Files:**
- `frontend/src/api/endpoints.ts` — Add `owner_id: string | null` to `AppInstance` interface (line 30). The backend `AppInstanceResponse` already sends this field (it's in the wire format, just untyped on the frontend).
- `frontend/src/pages/app-detail.tsx` — Change the PID display (line 71) from `currentInstance.instance_name` to `currentInstance.owner_id`. Show `owner_id` as the PID value, matching the old UI's format: `"Instance 0 · PID <owner_id>"`.

Fall back gracefully: if `owner_id` is null (shouldn't happen for running instances), omit the PID portion.

Note: custom `instance_name` values (e.g., `"kitchen_lights"`) will no longer appear in the metadata bar. This is an accepted trade-off — the instance switcher dropdown already displays instance names for multi-instance apps.

### Fix 4: Multi-column sort on log table (GAP-AD11)

**File:** `frontend/src/components/shared/log-table.tsx`

Currently only Timestamp has a sort button (lines 136–140). The old UI supported sorting by Level, Timestamp, App, and Message.

**Approach:** Generalize the existing sort pattern.

1. Replace the single `sortAsc` signal with a `sortConfig` signal: `{ column: "timestamp" | "level" | "app" | "message", asc: boolean }`.
2. Add `<button class="ht-sortable">` wrappers to Level, App, and Message `<th>` elements, mirroring the existing Timestamp pattern. Add `data-testid="sort-level"`, `data-testid="sort-app"`, `data-testid="sort-message"` to the new sort buttons for test consistency.
3. Extract the sort comparator to a named function `sortEntries(entries, column, asc)` at the top of the file (alongside the `LEVELS` constant). This keeps the render body clean and makes the comparator independently testable. Handle each column:
   - **Level:** Compare by severity index (DEBUG=0, INFO=1, WARNING=2, ERROR=3, CRITICAL=4)
   - **Timestamp:** Numeric comparison (existing)
   - **App:** Alphabetical (`localeCompare`)
   - **Message:** Alphabetical (`localeCompare`)
4. Show the `aria-sort` attribute only on the active sort column — remove it from inactive columns. Stale `aria-sort` on non-sorted columns violates ARIA spec.

Default sort remains Timestamp descending.

**Live streaming interaction:** When a non-timestamp sort column is active, pause WebSocket log entry accumulation and show a small "Live updates paused" indicator near the log controls. Resume streaming when the user switches back to timestamp sort or clicks "Resume". This prevents the table from visually reordering on each new log entry — the standard pattern in monitoring log viewers (Kibana, Grafana Loki). Implementation: gate the WS entry append in the log store on a `livePaused` signal derived from `sortConfig.column !== "timestamp"`.

## Alternatives Considered

### Multi-column sort: Full table sort library
Could use a library like `@tanstack/table` for sorting. Rejected — the sort logic is simple enough (4 columns, 2 directions) that adding a dependency would be over-engineering. The extracted `sortEntries` function extends cleanly.

### Page transition indicator (GAP-MI5)
Considered a CSS progress bar on route changes via `useLocation()` from wouter. Rejected after challenge review — SPA transitions are instant (no lazy loading), per-page Spinners handle actual async loading, and a timer-based fake bar creates contradictory loading signals. Also misfires on instance-switcher `navigate()` calls. All three critics flagged this independently.

### GAP-AD2: Show both instance_name and owner_id
Could display `"Instance 0 · my_instance_name (PID 12345)"`. Rejected — the old UI only showed PID, and `instance_name` often defaults to `ClassName.index` which is redundant with the instance heading. Custom instance names remain visible in the instance switcher dropdown.

### Multi-column sort: No streaming interaction
Could implement sort without pausing live streaming. Rejected — sorting by Level/Message while logs stream causes the table to visually reorder on each new entry, which is confusing in a monitoring context.

## Open Questions

None identified after codebase verification on 2026-03-24. Implementer should re-read each target file before writing code and open questions if the current state differs from what this design describes.

## Impact

**Files changed (5):**
- `frontend/src/api/endpoints.ts` — Add `owner_id` to `AppInstance` type
- `frontend/src/components/dashboard/app-card.tsx` — Add error rate text
- `frontend/src/components/dashboard/error-feed.tsx` — Show handler_method, change badge to error_type, fix key stability
- `frontend/src/pages/app-detail.tsx` — Use owner_id for PID display
- `frontend/src/components/shared/log-table.tsx` — Add multi-column sort with streaming pause

**Tests to update/add:**
- `app-card.test.tsx` — Error rate rendering
- `error-feed.test.tsx` — Handler method, badge content, key stability (if test exists)
- `log-table.test.tsx` — Multi-column sort behavior, aria-sort placement, live pause indicator
- `app-detail.test.tsx` — PID display with owner_id (if test exists)

**Blast radius:** Low. All changes are isolated to individual components. No shared state changes, no API changes, no backend changes.
