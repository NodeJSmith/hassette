# Design: Responsive Mobile Adaptation

**Status:** Approved
**Feature:** responsive-mobile
**Date:** 2026-04-05

## Problem

The Hassette web UI is non-functional on mobile devices (<768px):

1. **No navigation** — sidebar is `display: none` with no replacement. Users are stranded on whatever page they land on. This is a shipping bug.
2. **Apps table unusable** — Status, Error, and Actions columns clip off-screen. No way to see app status or take actions.
3. **Log table truncates** — App and Message columns clip. Sort state can reference hidden columns.
4. **Touch targets undersized** — scope toggle (~23px), theme toggle (30px), tab buttons (~27px), action buttons are all below 44px minimum.
5. **Pulse dot disappears** — the signature connection indicator lives in the hidden sidebar.
6. **KPI strip orphans** — 5 cards in a 2-col grid leaves 1 orphan card on its own row.

The user is a developer doing a quick diagnostic check on their phone: "Is everything running? What's the error rate?" Quick glance, not prolonged monitoring.

## Architecture

### Component Changes

**New: `BottomNav` component** (`frontend/src/components/layout/bottom-nav.tsx`)
- Renders at <768px only (CSS `display: none` at >=768px)
- Fixed to bottom of viewport, above safe area
- 4 tabs: Dashboard, Apps, Logs, Sessions — reuses icon components from `shared/icons.tsx`
- Active state: neutral treatment (recessed surface + text color), matching desktop sidebar convention
- 52px height + safe-area inset

**BottomNav owns its own nav items** — the `NAV_ITEMS` array in `sidebar.tsx` contains JSX icon elements that don't belong in a constants file. BottomNav duplicates the 4-item list (these are stable, rarely-changed items). If nav items change, both components need updating — an acceptable tradeoff for 4 items vs the indirection of a shared constants file with JSX.

**New: `ManifestCardList` component** (`frontend/src/components/apps/manifest-card-list.tsx`)
- Card-based layout for <768px, replacing the `<table>` in `ManifestList`
- Each card: app name + status badge top line, handler/job counts below, link to detail page
- Action buttons render below counts, full width. No confirmation — all actions are reversible per design principle #5.
- Multi-instance apps show expand chevron, accordion-style expansion

**New: `useManifestState` hook** (`frontend/src/hooks/use-manifest-state.ts`)
- Extracts filter state, expanded state, and localStorage persistence from `ManifestList`
- Both `ManifestList` (table) and `ManifestCardList` consume this hook
- `ManifestList` conditionally renders the card list or table based on a `useMediaQuery` hook

**New: `useMediaQuery` hook** (`frontend/src/hooks/use-media-query.ts`)
- `useMediaQuery(maxWidth: number): boolean`
- Uses `window.matchMedia`, cleans up listener on unmount
- Returns `true` when viewport <= maxWidth
- **Breakpoint sync**: the 768px value must match the CSS `@media (max-width: 768px)` breakpoint. Define as `BREAKPOINT_MOBILE = 768` in the hook file, and add `/* sync: BREAKPOINT_MOBILE in use-media-query.ts */` comments in global.css at each <768px media query.

**Modify: `StatusBar`** (`frontend/src/components/layout/status-bar.tsx`)
- Already renders the pulse dot via `.ht-ws-indicator`
- No component changes needed — pulse dot is already in the status bar
- **CSS change**: make StatusBar `position: sticky; top: 0` at <768px so the connection indicator stays visible while scrolling

**Modify: `App` layout** (`frontend/src/app.tsx`)
- Add `<BottomNav />` after the main content area
- CSS handles show/hide based on viewport

### CSS Changes (global.css)

**Bottom nav styles:**
- `.ht-bottom-nav`: fixed bottom, 52px height, flex row, 4 equal items
- `.ht-bottom-nav__item`: 44px min touch target, flex column (icon + label), 10px label
- `display: none` at >=768px
- `env(safe-area-inset-bottom)` padding for iOS

**Main content padding:**
- At <768px: `padding-bottom: calc(var(--ht-sp-4) + 52px + env(safe-area-inset-bottom, 0px))`
- Prevents bottom nav overlap with content

**KPI strip reflow:**
- **JSX reorder**: move Error Rate to first position in `KpiStrip` component (currently 2nd). This makes it the most prominent card on all viewports — if it's the most important metric, it should be first everywhere.
- At <768px: `:first-child` spans full width, remaining 4 in 2x2 grid
- All cards visible without scrolling

**Touch target enforcement at <768px:**
- `.ht-scope-toggle__btn`: min-height 44px, padding increase
- `.ht-theme-toggle`: min-width/height 44px
- `.ht-tabs li button`: min-height 44px, padding increase
- `.ht-btn--sm`, `.ht-btn--xs`: min-height 44px at <768px
- Action buttons in apps: min-height 44px

**Log table adaptation at <768px:**
- Hide Source column (already done at <1024px)
- Hide App column — show app name as a colored tag (using existing `.ht-tag` component) before the message text. Sort-by-app is handled via the existing app dropdown filter, so removing the column header doesn't lose functionality.
- Timestamp column: narrower, truncate seconds
- Level column: abbreviate (INFO→I, WARNING→W, etc.) or use color-only dots

**StatusBar sticky on mobile:**
- At <768px: `position: sticky; top: 0; z-index: 20; background: var(--ht-surface-sticky)`
- Keeps pulse dot and scope toggle visible while scrolling

**App grid on dashboard:**
- At <480px: single column
- Already `auto-fill, minmax(220px, 1fr)` which handles most sizes

### Token Compliance

All values must reference `--ht-*` tokens:
- Bottom nav background: `--ht-surface`
- Bottom nav border-top: `--ht-border`
- Active item: `--ht-surface-recessed` bg + `--ht-text` color
- Inactive item: `--ht-text-dim` color
- Touch target spacing: `--ht-sp-*` scale
- Bottom nav icon size: 20px (matches sidebar icon size)
- Bottom nav label: `--ht-text-xs` (12px), `--ht-font-body`

## Alternatives Considered

### Horizontal scroll KPI strip
Rejected: hides Error Rate (the most critical metric) behind a scroll interaction. Challenge finding #3 flagged this — "vertical space is cheap on mobile, horizontal scroll is an anti-pattern for critical diagnostic data."

### Hamburger menu instead of bottom nav
Rejected: hides navigation behind an extra tap. The design context says "everything has a place, you grab what you need" — a hamburger menu contradicts this by hiding the toolbox.

### Simplified "quick check" mobile view (dashboard only, no navigation)
Considered but deferred: the challenge produced a TENSION finding (#8) on this. For now, full responsive adaptation is the baseline — a simplified quick-check view can be layered on top later if usage data shows >90% dashboard-only mobile usage.

### CSS-only adaptation (no new components)
Rejected: the challenge found (finding #1) that the apps table cannot be transformed to cards via CSS alone — `<table>/<thead>/<tbody>` requires JSX restructuring.

## Test Strategy

### Unit tests
- `BottomNav` renders 4 items, active state matches current route, hidden at >=768px
- `ManifestCardList` renders card per app, shows status badge, handles expand toggle
- `useMediaQuery` hook responds to viewport changes
- `useManifestState` hook manages expanded state and localStorage persistence

### E2E tests (Playwright)
- Navigate between all 4 pages via bottom nav at 375px viewport
- Apps page shows card layout at 375px, table at 1024px
- KPI strip: Error Rate card spans full width at 375px, all 5 visible without scrolling
- Bottom nav does not overlap last content item (scroll to bottom, assert last element is visible above nav)
- Touch target assertion: all interactive elements at 375px have computed min-height >= 44px
- Breakpoint boundary: at exactly 768px, verify table/card transition is clean (no mixed state)

### Visual regression (Playwright screenshots)
- Dashboard at 375px, 768px, 1440px (dark mode)
- Apps page at 375px, 768px, 1440px (dark mode)
- Logs page at 375px, 768px, 1440px (dark mode)
- Dashboard at 375px (light mode)
- Compare before/after for each viewport

## Risks

- **iOS Safari dynamic toolbar**: bottom nav may overlap with Safari's toolbar. Mitigated by `env(safe-area-inset-bottom)` and `min-height: 100dvh` on the layout.
- **Expansion state shared between table/card views**: if user expands an app on desktop then checks on mobile, the card view should respect the expanded state. Both views share the same state via `useManifestState` hook.
- **JS/CSS breakpoint drift**: `useMediaQuery(768)` and `@media (max-width: 768px)` must stay in sync. Mitigated by TS constant + CSS comments + E2E test at exactly 768px.
