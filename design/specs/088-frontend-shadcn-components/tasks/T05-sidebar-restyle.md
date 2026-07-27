---
task_id: "T05"
title: "Restyle sidebar with Tailwind and add Radix Collapsible"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#12", "AC#1", "AC#3"]
---

## Summary

Restyle the existing `sidebar.tsx` with Tailwind utilities and `cn()`. Add Radix `Collapsible` for the two accordion tiers (per-status-group, per-app-instance). No shadcn Sidebar is generated -- the sidebar stays as fully owned code. All business logic, keyboard handling (`[` key with `isTypingTarget` and `!belowSidebarBreakpoint` guards), and mobile drawer behavior are preserved unchanged. The mobile drawer's global CSS classes (`.ht-drawer`/`.ht-drawer-backdrop`) are replaced with Tailwind utilities.

## Target Files

- modify: `frontend/src/components/layout/sidebar.tsx`
- modify: `frontend/src/components/layout/sidebar.module.css`
- modify: `frontend/src/components/layout/sidebar.test.tsx`
- modify: `frontend/src/components/layout/sidebar-groups.ts`
- modify: `frontend/src/styles/layout.css`
- modify: `frontend/src/app.tsx`
- read: `frontend/src/components/layout/use-group-open.ts` (preserved unchanged)
- read: `frontend/src/hooks/use-sidebar-hidden.ts` (preserved unchanged)
- read: `frontend/src/hooks/use-media-query.ts` (preserved unchanged)

## Prompt

Read `frontend/src/components/layout/sidebar.tsx`, `sidebar-groups.ts`, `use-group-open.ts`, and `sidebar.module.css` to understand the full current implementation.

**Restyle with Tailwind:**
Replace CSS Module class references (`styles.sidebar`, `styles.navItem`, etc.) in `sidebar.tsx` with Tailwind utility classes composed via `cn()`. The sidebar's `.module.css` file may be significantly reduced or deleted once all styles are in Tailwind -- but do NOT convert styles that are shared with other components via the global `styles/layout.css` file without verifying no other consumers depend on them.

**Add Radix Collapsible for accordion tiers:**
1. Per-status-group: wrap each `GroupDef` in Radix `Collapsible`. `CollapsibleTrigger` on the group header (with tone-based coloring for err/warn/ok/mute). `CollapsibleContent` on the group content. Wire open/close state from the existing `useGroupOpen` hook -- do NOT introduce new state management.
2. Per-app-instance: wrap each app's instance list in Radix `Collapsible`. The existing local `useState(false)` per `AppEntry` for expand/collapse is preserved.

**Structure preserved (restyled only):**
- Whole-sidebar collapse: existing Zustand `sidebarCollapsed` state, no change to mechanism
- Brand block: wordmark + version chip + collapse toggle
- Command palette trigger: `Cmd+K`/`Ctrl+K` hint button
- Primary nav: `NAV_PAGES` iteration with active-route prefix-match (via `useLocation()`)
- App search filter: search input wired to `search`/`setSearch`, `${filteredCount}/${totalCount}` label, loading spinner, empty state
- Footer: `SystemHealth` + `ThemeToggle`

**Mobile drawer restyle:**
Read the mobile drawer code in `frontend/src/app.tsx` (the dual-render pattern with `drawerOpen`/`drawerMounted`/`drawerRef`/`drawerEverOpenedRef`/`hamburgerRef` state). Replace `.ht-drawer`/`.ht-drawer.is-open`/`.ht-drawer-backdrop` global CSS classes in `styles/layout.css` with Tailwind utilities applied directly in `app.tsx`. This is a CSS-only change -- the JavaScript drawer state machine stays unchanged.

**Do NOT change:**
- The `[` keyboard shortcut handler in `app.tsx` (with `isTypingTarget()` and `!belowSidebarBreakpoint` guards)
- `useGroupOpen` hook logic (`allHealthy` auto-open, `GROUP_DEFS` defaultOpen flags)
- Status-bar chrome fallback (`useSidebarHidden`)
- App-key/instance status aggregation
- Any sidebar business logic functions (`groupAndSortApps`, `worstStatus`, `statusPriority`)

Update sidebar tests for the new Tailwind class names and Radix Collapsible markup.

## Focus

- `sidebar.tsx` is 284 lines including all business logic. The visual restyle should not change the component's structure or behavior -- only its CSS class references.
- `use-group-open.ts` has the auto-open-running-only-when-allHealthy logic -- this must be preserved; Radix Collapsible's `open`/`onOpenChange` is controlled by this hook.
- The mobile drawer in `app.tsx` uses `inert` attribute toggling and manual focus management -- this JavaScript logic stays, only the CSS classes change.
- `sidebar-groups.ts` defines `GROUP_DEFS` with tone and defaultOpen per status -- this is pure data, not CSS. It may not need changes unless tone-based coloring is currently done via CSS Module classes.
- The active-route class is currently a plain string `"is-active"` (not CSS-module scoped) + `aria-current="page"`. Decide whether to keep this as a plain class or convert to a Tailwind conditional.

## Verify

- [ ] FR#12: Sidebar uses Tailwind utilities and Radix Collapsible; three collapse tiers (whole-sidebar, per-group, per-instance) work correctly; `[` keyboard shortcut with `isTypingTarget` and `!belowSidebarBreakpoint` guards preserved; app search filter functional
- [ ] AC#1: `cd frontend && npm run build` exits 0
- [ ] AC#3: `cd frontend && npm run typecheck` exits 0
