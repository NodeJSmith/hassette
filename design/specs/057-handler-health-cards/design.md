# Design: Handler Health Cards

**Date:** 2026-05-15
**Status:** archived
**Scope-mode:** hold

## Problem

The handler health section on the app detail overview tab uses a data table to display handler status. Tables distribute whitespace evenly across columns, creating large empty gaps that make the section feel sparse and hard to scan. For a quick health check — the primary use case — users need to glance at the section, spot problems instantly, and click into a failing handler. The table layout works against this: it forces the eye to track across wide rows, and the uniform row treatment makes healthy and failing handlers visually equivalent at a glance.

Cards are a better container for this data because each handler is a self-contained unit with heterogeneous metadata (listeners have entity IDs; jobs have trigger labels). Cards let each unit own its vertical space, surface more stats without column-width contention, and make failing handlers visually distinct through per-card styling.

## Goals

- Replace the handler health table with a responsive card grid that eliminates wasted whitespace
- Enable 5-second health checks: glance at the grid, spot failing cards immediately, click in for details
- Surface richer per-handler stats (error rate, average duration, last active) without the column-width problems that plagued the table
- Maintain full keyboard accessibility and screen reader support

## Non-Goals

- Modifying the error spotlight section, recent activity table, or logs section
- Adding sparklines, micro-animations, or rich visualizations to cards
- Changing the underlying data model or API endpoints
- Adding new data fields not already available on the existing types

## User Scenarios

### Operator: Home automation maintainer

- **Goal:** Confirm all handlers are healthy
- **Context:** Opening the app detail page after a deployment or on a routine check

#### Quick health check

1. **Opens the app overview tab**
   - Sees: a grid of handler cards, each showing status, name, kind, and key stats
   - Decides: are any cards visually flagged as failing?
   - Then: if all cards look healthy, moves on. If a card has a red top border, reads the error info on the card.

2. **Spots a failing handler card**
   - Sees: red top border, error type inline, truncated error message
   - Decides: is this a known issue or something new?
   - Then: clicks the card (or the handler name link) to navigate to the handler detail page for full error context.

3. **Scans stats across handlers**
   - Sees: run counts, average durations, error rates, and recency for each handler at a glance
   - Decides: is any handler unusually slow, error-prone, or stale?
   - Then: clicks into the handler that looks anomalous.

## Functional Requirements

- **FR#1** Each handler (listener or job) is rendered as an individual card within a responsive grid
- **FR#2** Each card displays: status indicator, handler name, handler kind label, run count, average duration, error rate (when non-zero), and time since last execution
- **FR#3** Failing handler cards are visually distinguished with a colored top border and display the error type inline and error message truncated to one line
- **FR#4** The entire card is clickable and navigates to the handler detail page
- **FR#5** The handler name within each card is a standalone link that also navigates to the handler detail page
- **FR#6** The card grid is responsive, displaying 2-3 cards per row at desktop widths and collapsing to a single column on mobile
- **FR#7** When the grid exceeds 3 rows of cards, the section scrolls vertically with the remaining cards accessible via scroll
- **FR#8** When no handlers exist, an empty state message is displayed
- **FR#9** Cards are sorted with failing handlers first, then by descending run count
- **FR#10** Cards are keyboard-navigable: focusable via tab, activatable via Enter or Space

## Edge Cases

- **Single handler:** Grid renders a single card that does not stretch to fill the full width (card has a max-width or the grid column minimum prevents over-stretching)
- **Zero runs:** Stats row shows "0 calls" / "0 runs", duration shows "—", error rate is omitted, last active shows "—"
- **Long handler names:** Name truncates with ellipsis; full name visible on hover via title attribute
- **Long error messages:** Message truncates to a single line with ellipsis; full message visible on hover
- **8+ handlers:** Grid scrolls after 3 visible rows; scroll indicator (overflow gradient or scrollbar) signals more content
- **All handlers failing:** Every card shows the error treatment; no special aggregate state needed
- **Error rate rounding:** 0.0% is treated as no errors (omitted); values like 0.1% are shown

## Acceptance Criteria

- **AC#1** The handler health section renders a grid of cards instead of a table (FR#1)
- **AC#2** Each card surfaces all specified data fields with correct formatting (FR#2)
- **AC#3** Failing cards are immediately visually distinguishable from healthy cards without reading text (FR#3)
- **AC#4** Clicking anywhere on a card navigates to the correct handler detail page (FR#4, FR#5)
- **AC#5** The grid displays 2-3 columns on desktop (≥768px) and 1 column on mobile (<768px) (FR#6)
- **AC#6** The section scrolls when content exceeds 3 rows, with remaining cards accessible (FR#7)
- **AC#7** An empty state is shown when no handlers are registered (FR#8)
- **AC#8** Cards can be reached and activated via keyboard alone (FR#10)
- **AC#9** All CSS values reference design tokens — no raw hex colors, pixel values outside tokens, or magic numbers
- **AC#10** Cards are sorted with failing handlers appearing before healthy ones, and within each group by descending run count (FR#9)
- **AC#11** The `formatRate` function is extracted from `pages/handlers.tsx` to `utils/format.ts` and imported by both consumers

## Key Constraints

- No left-border accents — use top border for error state (project convention per feedback memory)
- No shadows for card depth — borders only, per design context
- No border radius above `--r-md` (6px), per design context
- All data values in monospace (`--font-mono`), per design context
- Status colors are semantic only — never decorative, per design context
- Error rate uses the existing `formatRate` calculation extracted to `format.ts` — do not reimplement

## Dependencies and Assumptions

- Depends on the existing `UnifiedItem` discriminated union type and its helper functions (`isFailing`, `itemRunCount`, `itemErrorType`, `itemErrorMessage`, `itemKindChip`, `sortedByFailingFirst`)
- Depends on existing shared components: `StatusShape`, `Chip`, `EmptyState`
- Depends on existing format utilities: `pluralize`, `formatDurationOrDash`, `formatRelativeTime`
- Assumes `formatRate` will be extracted from `pages/handlers.tsx` to `utils/format.ts` as part of this work
- Assumes the `UnifiedItem` data model provides all needed fields (confirmed: `avg_duration_ms`, `last_invoked_at`/`last_executed_at`, `failed`, `total_invocations`/`total_executions` are all present)

## Architecture

### New component: `HandlerHealthCard`

Create `frontend/src/components/app-detail/handler-health-card.tsx` with co-located `handler-health-card.module.css`.

The component receives a single `UnifiedItem` plus navigation props (`appKey`, `instanceQs`) and renders one card. The parent `HandlerHealthGrid` (which stays in `overview-tab.tsx`) maps over sorted items and wraps the cards in a CSS grid container.

**Component decomposition:**

```
HandlerHealthGrid (overview-tab.tsx — updated)
  └── .healthGrid (CSS grid container with scroll wrapper)
      ├── HandlerHealthCard (new component, one per handler)
      │   ├── header: StatusShape + Link (handler name)
      │   ├── subtitle: Chip (kind) + error type span (if failing)
      │   ├── error message (if failing, 1-line truncated)
      │   └── stats: two rows of key-value pairs
      └── EmptyState (when no handlers)
```

**Props interface:**

```typescript
interface HandlerHealthCardProps {
  item: UnifiedItem;
  appKey: string;
  instanceQs: string;
}
```

No variant prop needed — the card derives its visual state entirely from `item.statusKind`.

### CSS grid layout

The grid container uses `display: grid` with `grid-template-columns: repeat(auto-fill, minmax(280px, 1fr))` for natural responsive behavior. Gap uses `--sp-3`. The scroll wrapper uses `max-height` calculated from 3 rows of cards (approximately 3 × card height + 2 × gap) with `overflow-y: auto`.

### `formatRate` extraction

Move `formatRate` from `frontend/src/pages/handlers.tsx:74` to `frontend/src/utils/format.ts`. Update the import in `handlers.tsx`. Import in the new card component.

### Card CSS structure

```
.card          — base surface (bg, border, radius, padding, cursor, transition)
.cardFailing   — modifier: red top border, no background change
.header        — flexbox row: status shape + name link
.name          — mono font, truncated with ellipsis
.subtitle      — flexbox row: chip + error type (if present)
.errorMessage  — single-line truncated, secondary text color
.stats         — two-row grid or flexbox for stat pairs
.stat          — individual stat: label + value
.statLabel     — micro font, tertiary ink
.statValue     — mono font, secondary ink
```

### Scroll container

Wrap the grid in a div with `max-height` and `overflow-y: auto`. The max-height should accommodate ~3 rows of cards. Since card height varies slightly (failing cards have an extra error message line), use a conservative estimate. A CSS custom property or a fixed value based on the tallest possible card (failing + 2-line stats ≈ ~140px per card, plus gap) works: `max-height: calc(3 * 140px + 2 * var(--sp-3))`.

### Files changed

| File | Change |
|---|---|
| `frontend/src/components/app-detail/handler-health-card.tsx` | New — card component |
| `frontend/src/components/app-detail/handler-health-card.module.css` | New — card styles |
| `frontend/src/components/app-detail/overview-tab.tsx` | Update `HandlerHealthGrid` to render cards in a grid instead of a table; remove `HealthGridRow` and table markup |
| `frontend/src/components/app-detail/overview-tab.module.css` | Remove `.healthTable`, `.healthRow*`, `.colDot` styles; add `.healthGrid` and `.healthGridScroll` |
| `frontend/src/utils/format.ts` | Add `formatRate` function |
| `frontend/src/pages/handlers.tsx` | Update import of `formatRate` from `../utils/format` |

## Convention Examples

### Clickable navigation with keyboard support

**Source:** `frontend/src/components/app-detail/overview-tab.tsx` (HealthGridRow)

```tsx
function HealthGridRow({ item, appKey, instanceQs }: HealthGridRowProps) {
  const [, navigate] = useLocation();
  const href = handlerPath(appKey, item, instanceQs);

  return (
    <tr
      class={clsx(styles.healthRow, isFailing(item) && styles.healthRowFailing)}
      data-testid={`overview-health-row-${item.kind}-${item.id}`}
      tabIndex={0}
      role="row"
      onClick={() => navigate(href)}
      onKeyDown={(e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigate(href);
        }
      }}
    >
      <td class={styles.healthRowName}>
        <Link href={href} class={styles.healthRowLink}
          onClick={(e: MouseEvent) => e.stopPropagation()}>
          {item.name}
        </Link>
      </td>
    </tr>
  );
}
```

Key pattern: whole-element `onClick` + `tabIndex={0}` + keyboard handler. Nested `Link` uses `e.stopPropagation()` to prevent double navigation. Use ARIA `role` appropriate to the element (will be `"article"` or `"link"` for cards, not `"row"`).

### Card surface styling with token-only values

**Source:** `frontend/src/components/shared/card.module.css`

```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--line-1);
  border-top: 1px solid var(--line-2);
  border-radius: var(--r-md);
  padding: var(--sp-5);
}

.compact {
  padding: var(--sp-3);
}
```

Key pattern: base class holds shared styles, variants are additive modifiers. Every value is a design token. `border-top` gets a different token (`--line-2`) for subtle top-edge differentiation.

### Data helper functions for UnifiedItem

**Source:** `frontend/src/components/app-detail/overview-tab.tsx`

```tsx
function isFailing(item: UnifiedItem): boolean {
  return item.statusKind === "err";
}

function itemRunCount(item: UnifiedItem): number {
  return item.kind === "listener" ? item.data.total_invocations : item.data.total_executions;
}

function itemKindChip(item: UnifiedItem): string {
  if (item.kind === "listener") {
    return handlerKindLabel("listener", item.data.listener_kind, null);
  }
  return handlerKindLabel("job", null, item.data.trigger_type);
}
```

Key pattern: small pure functions that abstract the listener/job discrimination. These already exist and should be reused, not duplicated. They are currently file-local to `overview-tab.tsx` — if the new component imports them, they may need to be extracted to a shared module (e.g., `handler-utils.ts`) or the card component can import `UnifiedItem` helpers from a barrel export.

### Chip for metadata labels

**Source:** `frontend/src/components/app-detail/overview-tab.tsx`

```tsx
<Chip variant="muted" size="sm" aria-label={`kind: ${chipLabel}`}>
  {chipLabel}
</Chip>
```

Key pattern: `variant="muted"` for neutral metadata, `size="sm"` for compact contexts. Always include `aria-label` for accessibility when the chip's visual meaning isn't self-evident.

### Format utilities for stats display

**Source:** `frontend/src/utils/format.ts`

```tsx
export function formatDurationOrDash(ms: number | null | undefined): string {
  return ms !== null && ms !== undefined && ms > 0 ? formatDuration(ms) : "—";
}

export function pluralize(count: number, singular: string, plural?: string): string {
  const label = count === 1 ? singular : (plural ?? `${singular}s`);
  return `${count} ${label}`;
}
```

**Source:** `frontend/src/pages/handlers.tsx` (to be extracted)

```tsx
function formatRate(failed: number, total: number): string {
  return total > 0 ? ((failed / total) * 100).toFixed(1) + "%" : "—";
}
```

Key pattern: format functions return "—" for missing/zero data. `formatRate` belongs in `format.ts` alongside these — extract it as part of this work.

## Alternatives Considered

**Keep the table but fix column widths.** Tried in the previous session — pinning narrow columns with `width: 1%; white-space: nowrap` moved the whitespace problem from many columns to one giant gap in the handler name column. Same emptiness, different shape. Rejected because tables fundamentally distribute space across the full container width.

**`width: auto` table.** Makes the table shrink-to-fit, but then it sits at partial width with empty space to the right, which looks equally wrong on a full-width page layout.

**Stacked list cards (full-width, one per row).** Considered during the design phase. Would solve the whitespace problem but wastes vertical space — each handler gets a full row even when the card content is compact. The grid layout is denser for the quick-scan use case.

**Stat-forward cards (hero number layout).** Run count as the large hero number with metadata below. More dashboard-like but prioritizes a single metric over the multi-dimensional scan the user needs (status + kind + runs + duration + recency).

## Test Strategy

- Unit tests for `formatRate` after extraction to `format.ts` (edge cases: 0 total, 0 failed, rounding)
- Component tests for `HandlerHealthCard`: renders correct data for listener vs job, shows error treatment for failing items, truncates long names/messages, renders stats correctly for zero-run handlers
- Integration test for the grid: correct number of cards rendered, sort order (failing first), empty state when no handlers
- Visual verification via dev server on real data across multiple apps (primary acceptance criterion per user)

## Documentation Updates

None — this is an internal UI component change. No user-facing API or docs site pages are affected.

## Impact

| Area | Impact |
|---|---|
| `overview-tab.tsx` | Moderate — `HandlerHealthGrid` rewritten from table to grid; `HealthGridRow` removed |
| `overview-tab.module.css` | Moderate — health table styles removed, grid container styles added |
| `handler-health-card.tsx` | New file |
| `handler-health-card.module.css` | New file |
| `utils/format.ts` | Minor — one function added |
| `pages/handlers.tsx` | Minor — import path change for `formatRate` |

Blast radius is contained to the app detail overview tab and the shared format utility. No backend changes. No API changes. No other pages affected beyond the `formatRate` import update in `handlers.tsx`.

## Open Questions

None — all design decisions resolved during discovery.
