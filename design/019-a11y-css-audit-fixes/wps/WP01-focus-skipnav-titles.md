# WP01: Global focus styles, skip-nav, page titles

**Lane:** todo
**Depends on:** none

## Objective

Establish the a11y foundation: visible focus indicators for keyboard users, a skip-nav link, and per-page document titles.

## Tasks

### 1. Focus-visible on inputs/selects

- In `global.css`, rename `.ht-input:focus, .ht-select select:focus` → `.ht-input:focus-visible, .ht-select select:focus-visible`
- Keep existing `border-color: var(--ht-accent)` and `box-shadow: 0 0 0 2px var(--ht-accent-light)`
- Delete the old `:focus` rule entirely — do not leave both

### 2. Global `:focus-visible` rule

- Add a global fallback rule using `:where()` for zero specificity (so component-level overrides win cleanly):
  ```css
  :where(:focus-visible) {
    outline: 2px solid var(--ht-accent);
    outline-offset: 2px;
  }
  ```
- Place after the reset section in `global.css`. Zero specificity means this acts as a fallback — any component rule (`.ht-btn:focus-visible`, `.ht-sortable:focus-visible`) can override it without cascade order concerns

### 3. `.ht-sortable:focus-visible`

- `global.css:1354` uses `all: unset` which strips focus styles
- Add after `.ht-sortable` definition:
  ```css
  .ht-sortable:focus-visible {
    outline: 2px solid var(--ht-accent);
    outline-offset: 2px;
    border-radius: var(--ht-radius-sm);
  }
  ```
- Consider replacing `all: unset` with targeted resets (`appearance: none; background: none; border: none; padding: 0; cursor: pointer; font: inherit;`)

### 4. Skip-nav link

- In `app.tsx`, add as first child inside `<div class="ht-layout">`:
  ```tsx
  <a href="#main-content" class="ht-skip-link">Skip to main content</a>
  ```
- Add `id="main-content"` and `tabIndex={-1}` to `<main class="ht-main">` — `tabIndex={-1}` makes it programmatically focusable so the anchor actually moves keyboard focus, not just scroll position
- Add CSS for `.ht-skip-link` in `global.css`:
  ```css
  .ht-skip-link {
    position: absolute;
    left: -9999px;
    top: auto;
    width: 1px;
    height: 1px;
    overflow: hidden;
    z-index: 1000;
  }
  /* :focus (not :focus-visible) — skip-nav must be visible on ALL focus types,
     including mouse click, since the user explicitly activated it */
  .ht-skip-link:focus {
    position: fixed;
    top: var(--ht-sp-2);
    left: var(--ht-sp-2);
    width: auto;
    height: auto;
    padding: var(--ht-sp-2) var(--ht-sp-4);
    background: var(--ht-surface);
    color: var(--ht-accent);
    border: 2px solid var(--ht-accent);
    border-radius: var(--ht-radius-md);
    font-family: var(--ht-font-body);
    font-size: var(--ht-text-base);
    z-index: 1000;
  }
  ```

### 5. Page titles

- Each page component adds a `useEffect` to set `document.title`:
  - `dashboard.tsx`: `"Dashboard - Hassette"`
  - `apps.tsx`: `"Apps - Hassette"`
  - `logs.tsx`: `"Logs - Hassette"`
  - `not-found.tsx`: `"Not Found - Hassette"`
  - `app-detail.tsx`: Two effects — (1) immediate fallback `"App - Hassette"` on mount, (2) update to `manifest.display_name - Hassette` when manifest loads. The manifest effect must include cleanup: `return () => { document.title = "Hassette"; }` to prevent stale titles if user navigates away mid-load

## Files

- `frontend/src/global.css`
- `frontend/src/app.tsx`
- `frontend/src/pages/dashboard.tsx`
- `frontend/src/pages/apps.tsx`
- `frontend/src/pages/app-detail.tsx`
- `frontend/src/pages/logs.tsx`
- `frontend/src/pages/not-found.tsx`

## Verification

- Tab through the entire app — every interactive element must show a visible focus ring
- Activate skip-nav link (Tab on page load) — focus must land on main content (assert `document.activeElement === document.getElementById('main-content')`)
- Check each page's browser tab title
- E2E test: skip-nav link → focus on `#main-content`
