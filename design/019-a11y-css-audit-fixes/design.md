# Design: Frontend A11y + CSS Audit Fixes (#419 + #420)

**Status:** Draft
**Issues:** #419 (a11y), #420 (CSS/fonts)
**Source:** [Comprehensive codebase audit](../audits/2026-03-25-comprehensive-audit/)

## Problem

The frontend has critical accessibility failures and CSS inconsistencies surfaced by the codebase audit:

1. **Keyboard users are locked out.** `outline: none` on inputs with no `:focus-visible` replacement. No skip-nav link. Interactive elements (`<span>` chevron, `<a>` tabs) lack keyboard handlers and ARIA roles.
2. **Screen readers get wrong semantics.** Status filters announced as links, not tabs. SVG icons not hidden from AT. Form controls missing labels. Health bar has no progressbar role.
3. **CSS has gaps.** `.ht-text-warning` and `.ht-tag--neutral` are used in components but never defined. 13+ inline styles across 8 files contradict the token architecture. Source column in log table overflows into Message column (no truncation on fixed-width cell).
4. **Fonts break offline.** Three Google Fonts families loaded from CDN. The vite config already mounts `/fonts/` suggesting self-hosting was planned.
5. **Page title never updates.** All routes show "Hassette" — no per-page document.title.

## Approach

All changes are frontend-only (Preact components + CSS). No backend changes. All CSS values reference `direction.md` tokens.

### WP1: Global focus + skip-nav + page titles

Foundation work that touches `global.css`, `index.html`, and `app.tsx`:

- Rename `.ht-input:focus` / `.ht-select select:focus` to `:focus-visible` (keep existing box-shadow + border-color values). Remove the `:focus` rule — do not supplement alongside it
- Add global `:focus-visible` rule for all interactive elements (buttons, links, selects)
- Add `.ht-sortable:focus-visible` rule explicitly — `all: unset` on `.ht-sortable` (`global.css:1354`) strips inherited focus styles, so the global rule alone is insufficient. Consider replacing `all: unset` with targeted property resets
- Existing `prefers-reduced-motion` rule at `global.css:1404` already suppresses all transitions via wildcard — no additional query needed. Verify focus-ring transitions are covered
- Add skip-nav link inside the Preact `App` component (co-located with its `<main id="main-content">` target to avoid cross-file pairing risk). Both must ship together — add E2E test that activates skip link and asserts focus lands on `#main-content`
- Page titles: each page component sets its own `document.title` via `useEffect`. Static pages on mount (e.g. "Dashboard - Hassette"). `AppDetailPage` sets title after manifest loads (e.g. "Garage Proximity - Hassette"), falling back to "App - Hassette" while loading

### WP2: Component ARIA + keyboard fixes

Per-component fixes — each is isolated:

- **manifest-row.tsx:** Convert chevron `<span>` to `<button>` with `aria-label`, `aria-expanded`, keyboard handler
- **status-filter.tsx:** Change `<nav>` to `<div role="group" aria-label="App status filter">`. Replace `<a href="#">` with `<button type="button" aria-pressed={isActive}>` toggle buttons. Remove `is-active` class from `<li>`. Update all 3 CSS selectors (`li a`, `li a:hover`, `li.is-active a`). No tablist/tab roles — this is a filter toggle group, not a tab widget
- **log-table.tsx:** Add `aria-label` to search input and level select. Add small expand button *alongside* (not wrapping) message text in the `<td>` — remove `role="button"`, `tabIndex`, `onKeyDown` from the `<td>`, keep `onClick` for click-anywhere. Button has `aria-label`/`aria-expanded`; message text stays independently readable by AT
- **app-detail.tsx:** Connect instance label to select via `htmlFor`/`id`
- **icons.tsx:** Add `aria-hidden="true"` to all SVG icons (decorative)
- **health-bar.tsx:** Add `role="progressbar"`, `aria-valuenow`, `aria-valuemin="0"`, `aria-valuemax="100"`, `aria-label`. When `total === 0`, render with `aria-hidden="true"` instead (no activity data — don't announce a misleading 100%)

### WP3: Missing CSS classes + inline style extraction

- Define `.ht-text-warning` in `global.css` using `--ht-warning` token
- Define `.ht-tag--neutral` in `global.css` at line 1283 (after `.ht-tag--job`) using `--ht-text-secondary` / `--ht-surface-recessed`. Note: `.ht-badge--neutral` already exists at `global.css:440` — these are separate component systems (different shape, sizing, text-transform) and must not be conflated
- Extract inline styles to CSS classes:
  - `manifest-row.tsx` — chevron cursor/margin → `.ht-item-row__chevron-inline` already exists, extend it; instance row padding → `.ht-instance-row td:first-child` padding
  - `error-feed.tsx` — ellipsis style → `.ht-tag--truncated` utility
  - `log-table.tsx` — scroll container → `.ht-log-table-scroll { max-height: var(--ht-log-scroll-height, 600px); overflow: auto; }` (CSS custom property allows future override); thead sticky → `.ht-table-log thead` (add comment: `--ht-surface-sticky` must remain opaque); column widths → `.ht-col-level`, `.ht-col-timestamp`, `.ht-col-app`, `.ht-col-source` (already exists for source); empty row center → `.ht-text-center` (utility exists)
  - `app-detail.tsx` — inline-block on select wrapper → `.ht-select--inline`
  - `sidebar.tsx` — logo dimensions → `.ht-sidebar__logo`
  - `not-found.tsx` — center + padding → `.ht-error-page { text-align: center; padding: var(--ht-sp-10); }`
  - `error-boundary.tsx` — center + padding → `.ht-error-card { padding: var(--ht-sp-6); text-align: center; }`
- Health bar width stays inline (dynamic value — cannot be a class)

### WP4: Self-host fonts

- Download Latin-subset woff2 files: DM Sans (400, 500, 700), JetBrains Mono (400, 500), Space Grotesk (400, 500, 600, 700) — 9 files total
- Commit to `frontend/public/fonts/` (reproducible, works offline, ~250KB added to git)
- Add `@font-face` declarations in `global.css` (not `tokens.css` — keep tokens strictly declarative) with `font-display: swap` (parity with current CDN behavior) and `unicode-range` for Latin subset
- Comment in `global.css` listing exact weights per family so future maintainers know what to add
- Add `*.woff2 binary` to `.gitattributes` to prevent autocrlf corruption
- Remove Google Fonts `<link>` tags and `preconnect` hints from `index.html`
- Verify no 404s on font files after switch; confirm browser devtools shows self-hosted fonts loading

## Files Changed

| File | Changes |
|------|---------|
| `frontend/index.html` | Remove CDN font links and preconnect hints |
| `frontend/src/app.tsx` | Add skip-nav link + `id="main-content"` on `<main>` (co-located) |
| `frontend/src/pages/dashboard.tsx` | Add `useEffect` for `document.title` ("Dashboard - Hassette") |
| `frontend/src/pages/apps.tsx` | Add `useEffect` for `document.title` ("Apps - Hassette") |
| `frontend/src/pages/app-detail.tsx` | Add `useEffect` for `document.title` (manifest display name after load) |
| `frontend/src/pages/logs.tsx` | Add `useEffect` for `document.title` ("Logs - Hassette") |
| `frontend/src/pages/not-found.tsx` | Add `useEffect` for `document.title` ("Not Found - Hassette") |
| `frontend/src/global.css` | Focus-visible styles, skip-nav styles, `.ht-text-warning`, `.ht-tag--neutral`, `.ht-tag--truncated`, column width classes, inline style extractions |
| `frontend/src/global.css` | (also) `@font-face` declarations for self-hosted fonts |
| `.gitattributes` | Add `*.woff2 binary` |
| `frontend/src/components/apps/manifest-row.tsx` | Chevron → `<button>`, remove inline styles |
| `frontend/src/components/apps/status-filter.tsx` | Replace `<a href="#">` with `<button aria-pressed>`, remove tab roles |
| `frontend/src/components/shared/log-table.tsx` | Add aria-labels, nest `<button>` in message `<td>`, remove inline styles |
| `frontend/src/components/shared/health-bar.tsx` | Add progressbar role + ARIA attributes |
| `frontend/src/components/shared/icons.tsx` | Add `aria-hidden="true"` to all SVGs |
| `frontend/src/components/dashboard/error-feed.tsx` | Remove inline style, use `.ht-tag--truncated` |
| `frontend/src/pages/app-detail.tsx` | Connect label to select, remove inline style |
| `frontend/src/components/layout/sidebar.tsx` | Remove inline style, use CSS class |
| `frontend/src/pages/not-found.tsx` | Remove inline style, use `.ht-error-page` |
| `frontend/src/components/layout/error-boundary.tsx` | Remove inline style, use `.ht-error-card` |
| `frontend/public/fonts/` | woff2 font files (DM Sans, JetBrains Mono, Space Grotesk) |
| `tests/e2e/test_apps_list.py` | Update tab selectors after `<a>` → `<button>` conversion |
| `tests/e2e/test_apps.py` | Update tab selectors after `<a>` → `<button>` conversion |

## Risks

- **Font file size.** woff2 is compact but 9 font files (3 DM Sans + 2 JetBrains Mono + 4 Space Grotesk) add ~200-300KB. Acceptable for an offline-capable tool.
- **E2E test breakage.** Converting `<a>` to `<button>` in status-filter will break E2E selectors (`[data-testid='tab-running'] a`). Test files included in scope.
- **Inline style removal could break layout.** Each extraction needs visual verification. The log table sticky header and column widths are the highest risk.

## Out of Scope

- Rate limiting on app mutation endpoints (#418)
- Path traversal fix (#418)
- Healthz Pydantic model (#418)
- Resizable columns (#384)
- Responsive mobile layout (#389)
