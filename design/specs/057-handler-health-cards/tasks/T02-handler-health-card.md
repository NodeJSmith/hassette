---
task_id: "T02"
title: "Create HandlerHealthCard component"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#10", "AC#2", "AC#3", "AC#4", "AC#8", "AC#9"]
---

## Summary

Create the new `HandlerHealthCard` component at `frontend/src/components/app-detail/handler-health-card.tsx` with co-located `handler-health-card.module.css`. This is the core visual component — one card per handler, showing status shape, handler name (clickable link), kind chip, error treatment for failing handlers, and two rows of stats. The entire card is clickable with keyboard accessibility. Unit tests verify all data states and interactions.

## Prompt

### Component file: `frontend/src/components/app-detail/handler-health-card.tsx`

1. **Props interface:**
   ```typescript
   interface HandlerHealthCardProps {
     item: UnifiedItem;
     appKey: string;
     instanceQs: string;
   }
   ```

2. **Card structure** (top to bottom):
   - **Header row:** `StatusShape` (size 10) + handler name as a `Link` to handler detail page. Name truncates with ellipsis on overflow; full name on hover via `title`.
   - **Subtitle row:** `Chip` (variant `"muted"`, size `"sm"`) showing the kind label + error type in red text (only when failing). Separated by a middle-dot or gap.
   - **Error message** (conditional): only rendered when the handler is failing and has an error message. Single-line truncated with ellipsis; full message on hover via `title`.
   - **Stats row 1:** run count (using `pluralize`) + average duration (using `formatDurationOrDash`).
   - **Stats row 2:** error rate (using `formatRate`, only shown when failed > 0) + last active (using `formatRelativeTime`). When error rate is 0%, omit it entirely — don't show "0.0%".

3. **Interaction:**
   - Whole card clickable via `onClick={() => navigate(href)}` using wouter's `useLocation`.
   - `tabIndex={0}` for keyboard focus.
   - `onKeyDown` handler for Enter and Space keys.
   - Handler name `Link` uses `onClick={(e) => e.stopPropagation()}` to prevent double navigation.
   - `role="article"` on the card div (not `"link"` — the card contains a nested `<a>`, so `role="link"` would be an a11y defect).
   - `data-testid={`overview-health-card-${item.kind}-${item.id}`}` for testing.

4. **Helper functions:** The card component needs access to helper functions currently local to `overview-tab.tsx`: `isFailing`, `itemRunCount`, `itemErrorType`, `itemErrorMessage`, `itemKindChip`, and `handlerPath`. These must not be duplicated. Either:
   - Export them from `overview-tab.tsx` and import in the card, or
   - Extract them to a shared file (e.g., `handler-helpers.ts`) and import from both files.
   Choose whichever keeps the code cleanest. The card also needs a new helper for last-active timestamp: `item.kind === "listener" ? item.data.last_invoked_at : item.data.last_executed_at`.

5. **Imports:** `formatRate` from `../../utils/format` (extracted in T01), `formatDurationOrDash`, `formatRelativeTime`, `pluralize` from `../../utils/format`, `StatusShape` from `../shared/status-shape`, `Chip` from `../shared/chip`, `Link` from `wouter`, `useLocation` from `wouter`, `clsx` from `clsx`.

### CSS module: `frontend/src/components/app-detail/handler-health-card.module.css`

Every CSS value must be a design token. Reference `frontend/src/tokens.css` for available tokens.

**Class structure:**
- `.card` — base surface: `background: var(--bg-surface)`, `border: 1px solid var(--line-1)`, `border-radius: var(--r-md)`, `padding: var(--sp-3)`, `cursor: pointer`, `transition: background var(--t-fast) var(--ease)`. Display as flex column with `gap: var(--sp-2)`.
- `.card:hover` — `background: var(--bg-sunken)`.
- `.card:focus-visible` — `outline: 2px solid var(--accent)`, `outline-offset: 2px`.
- `.cardFailing` — `border-top: 2px solid var(--err)`. No background change.
- `.cardFailing:hover` — `background: color-mix(in srgb, var(--err-bg) 40%, var(--bg-sunken))`.
- `.header` — flex row, `align-items: center`, `gap: var(--sp-2)`.
- `.name` — `font-family: var(--font-mono)`, `font-size: var(--fs-mono-sm)`, `color: var(--ink-1)`. Truncate: `overflow: hidden`, `text-overflow: ellipsis`, `white-space: nowrap`. Link decoration: `text-decoration: none`, `:hover` → `text-decoration: underline`, `text-decoration-color: var(--accent)`.
- `.subtitle` — flex row, `align-items: center`, `gap: var(--sp-2)`, `flex-wrap: wrap`.
- `.errorType` — `font-size: var(--fs-small)`, `color: var(--err)`, `white-space: nowrap`.
- `.errorMessage` — `font-size: var(--fs-small)`, `color: var(--ink-3)`, single-line truncation (`overflow: hidden`, `text-overflow: ellipsis`, `white-space: nowrap`), `max-width: 100%`.
- `.stats` — flex column with `gap: var(--sp-1)`.
- `.statRow` — flex row, `gap: var(--sp-3)`, `font-family: var(--font-mono)`, `font-size: var(--fs-mono-sm)`, `color: var(--ink-3)`.

### Test file: `frontend/src/components/app-detail/handler-health-card.test.tsx`

Follow the testing conventions in `overview-tab.test.tsx`:
- Use `renderWithAppState` from `../../test/render-helpers`.
- Use factory functions from `../../test/factories.ts` or create local helpers for test data.
- Mock `wouter` for navigation assertions.

**Test cases:**
1. Renders handler name, kind chip, and run count for a healthy listener
2. Renders handler name, kind chip, and run count for a healthy job
3. Shows error type and error message for a failing handler
4. Does not show error type or error message for a healthy handler
5. Shows error rate only when failed > 0
6. Omits error rate when failed is 0
7. Shows "—" for avg duration when it is 0
8. Shows "—" for last active when timestamp is null
9. Whole card click navigates to correct handler detail path
10. Enter key on focused card navigates
11. Name link click navigates without double navigation (stopPropagation)
12. Long handler name truncates (verify CSS class is applied)
13. `data-testid` includes kind and id

## Focus

- **Existing card pattern:** `frontend/src/components/shared/card.module.css` shows the token-only surface styling convention. Match the surface treatment but do NOT use the shared Card component as a wrapper — HandlerHealthCard has its own layout needs.
- **Navigation pattern:** The existing `HealthGridRow` in `overview-tab.tsx` (lines 157-197) demonstrates the exact click + keyboard + nested link pattern. Replicate it on a `<div>` instead of a `<tr>`.
- **Chip usage:** Line 182 of overview-tab.tsx shows `<Chip variant="muted" size="sm">` with `aria-label`. Use the same pattern.
- **StatusShape sizing:** Use `size={10}` to match the existing table row size.
- **Failing hover:** The existing `color-mix` pattern at line 122 of overview-tab.module.css shows how to blend error background with hover state.
- **UnifiedItem type:** Imported from `./unified-handler-row`. The discriminated union has `kind: "listener" | "job"` with different `data` shapes. All data access must be gated by `item.kind`.
- **Test factories:** Check `frontend/src/test/factories.ts` for existing `createListener`/`createJob` helpers before writing custom test data.

## Verify

- [ ] FR#1: Each handler (listener or job) renders as an individual card element (not a table row)
- [ ] FR#2: Each card displays status indicator, handler name, kind label, run count, avg duration, error rate (when >0), and last active time
- [ ] FR#3: Failing cards have a red top border (`border-top: 2px solid var(--err)`) and display error type inline and error message truncated to one line
- [ ] FR#4: Clicking anywhere on the card navigates to the handler detail page
- [ ] FR#5: The handler name is a standalone `Link` element that navigates to the handler detail page
- [ ] FR#10: Cards are focusable via Tab and activatable via Enter or Space
- [ ] AC#2: All data fields render with correct formatting (pluralize for counts, formatDurationOrDash for duration, formatRate for error rate, formatRelativeTime for last active)
- [ ] AC#3: Failing cards are visually distinguishable without reading text (red top border present, distinct from healthy cards)
- [ ] AC#4: Clicking the card and clicking the name link both navigate to the correct handler detail path
- [ ] AC#8: Card can be reached via Tab key and activated via Enter or Space
- [ ] AC#9: All CSS values reference design tokens — no raw hex, pixel values, or magic numbers in the module CSS
