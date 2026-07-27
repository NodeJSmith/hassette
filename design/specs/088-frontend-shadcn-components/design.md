# Design: Replace Hand-Rolled Components with shadcn/ui

**Date:** 2026-07-27
**Status:** approved
**Scope-mode:** expand
**Research:** design/research/2026-07-27-frontend-migration-part-two/brief.md

## Problem

Every frontend session is a fight against bespoke primitives. The dashboard has 13 hand-rolled interactive components — popovers with manual floating-ui positioning, dialogs with manual focus traps, tooltips with CSS-only positioning, tables with hand-written per-column JSX — each requiring triple-checked CSS and custom accessibility wiring. AI agents produce inconsistent output because there is no shared component vocabulary; `design/context.md` must over-specify every visual decision to prevent invention.

Spec 020 (PR #1466, merged to `frontend-migration`) replaced the framework layer (Preact → React 19, signals → Zustand, added Tailwind v4, initialized shadcn/ui). But no shadcn components were generated — the `components/ui/` directory is empty. The 136 custom design tokens still use the old `--bg-*`/`--ink-*`/`--accent-*` naming, which collides with shadcn's theme variables (shadcn's `--accent` already shadows hassette's `--accent` in `global.css` with different values).

This spec replaces the hand-rolled component layer with shadcn/ui primitives and adopts shadcn's token naming system, completing the migration from "custom everything" to "shared vocabulary."

## Goals

- All hand-rolled shared components (Button, Badge, Chip, Card, Tooltip, ConfirmDialog, InfoPopover, ColumnFilterPopover, CommandPalette, TimePresetSelector) are replaced by shadcn/ui equivalents.
- The log-table subsystem (14 source files) and execution-table are replaced with TanStack Table + shadcn Table.
- The sidebar is replaced with shadcn Sidebar.
- All 136 design tokens are renamed to shadcn's naming convention.
- The `--accent` naming collision between hassette and shadcn is resolved.
- Visual parity with the current UI is maintained.
- All existing vitest tests pass (updated for new component APIs).
- The E2E suite (`nox -s e2e`) passes.

## Non-Goals

- Converting CSS Module files to Tailwind utility classes (PR 2).
- Removing global CSS files in `styles/` (PR 2).
- Removing CSS lint tools (PR 2).
- Removing `tokens.css` (PR 2 — the file is rewritten here but stays until all `var()` references migrate to Tailwind utilities).
- Rewriting `design/context.md` (PR 3).
- Regenerating doc screenshots (PR 3).
- Enabling React StrictMode (PR 2).
- Adding table virtualization or removing the 200-row cap (follow-up issue).
- Changing the routing library, data fetching layer, or WebSocket protocol.

## User Scenarios

### Jessica: Solo developer + AI agents

- **Goal:** Make frontend changes without fighting the stack
- **Context:** Working on `migration-part-two` branch, PRing to `frontend-migration`

#### Component replacement

1. **Verify token rename**
   - Sees: all pages render with correct colors, spacing, typography
   - Decides: nothing — mechanical rename
   - Then: no visual regression from the rename

2. **Verify component replacements**
   - Sees: each replaced component renders identically to the hand-rolled version
   - Decides: whether visual parity is acceptable
   - Then: tests pass, demo stack looks correct

3. **Use shadcn components in future work**
   - Sees: `npx shadcn@latest add <component>` works; existing components follow shadcn conventions
   - Decides: which shadcn component to use for new UI features
   - Then: consistent output from both human and AI-assisted development

## Functional Requirements

- **FR#1** All 136 design tokens in `tokens.css` use shadcn-compatible naming: surfaces map to `--background`/`--card`/`--muted`/`--accent`, text to `--foreground`/`--muted-foreground`, borders to `--border`, brand/action color to `--primary`, error to `--destructive`. Domain-specific tokens (status colors, handler families, type scale) use prefixed custom extensions (`--status-*`, `--handler-*`, `--text-*`).
- **FR#2** The `--accent` collision is resolved: hassette's brand/action color (`--accent`) becomes `--primary`; hassette's highlighted-background (`--bg-active`) becomes `--accent` (matching shadcn's semantic role).
- **FR#3** shadcn Button replaces `components/shared/button.tsx`. All consumers update to shadcn's prop API (`variant`, `size`). The current `ghost` boolean becomes `variant="ghost"`. The `buttonRef` prop becomes React's standard `ref` forwarding.
- **FR#4** shadcn Badge replaces `components/shared/badge.tsx` and `components/shared/chip.tsx`. The Chip's discriminated-union props interface is simplified to Badge variants. Consumer call sites update directly to the new API.
- **FR#5** shadcn Card replaces `components/shared/card.tsx`. The `diagnostics.tsx` direct CSS Module import is converted to use the Card component.
- **FR#6** shadcn Tooltip replaces `components/shared/tooltip.tsx` (currently CSS-only, 1 consumer).
- **FR#7** shadcn AlertDialog replaces `components/shared/confirm-dialog.tsx`. The manual focus trap and keyboard handling are removed (Radix handles these internally).
- **FR#8** shadcn Popover replaces `components/shared/info-popover.tsx` and `components/shared/column-filter-popover/`. The `@floating-ui/dom` positioning and manual focus trap are removed (Radix handles these internally).
- **FR#9** shadcn Command (wrapping cmdk) replaces `components/layout/command-palette.tsx`. The react-query listener fetch is preserved, wired into cmdk's async search pattern. The manual sentinel-div focus trap is removed.
- **FR#10** `components/layout/time-preset-selector.tsx` is restyled with Tailwind utilities and `cn()`, keeping the existing `<select>` (mobile) and `<button aria-pressed>` (desktop) markup. The `useMediaQuery(BREAKPOINT_MOBILE)` branch structure is preserved. A future date-range feature will replace this component with shadcn Select/DatePicker when the real prop interface is known.
- **FR#11** TanStack Table (`@tanstack/react-table`) + shadcn Table replaces the log-table subsystem and execution-table. Existing hooks (`useLogFilters`, `useColumnVisibility`, `useRovingTabIndex`) are preserved — TanStack Table receives pre-filtered, pre-sorted data via `getCoreRowModel()` only. Hand-written per-column JSX in `log-table-row.tsx` is replaced with TanStack `ColumnDef` declarations.
- **FR#12** The sidebar is restyled with Tailwind utilities and uses Radix `Collapsible` directly for the two accordion tiers (per-status-group, per-app-instance). Three collapse tiers are preserved: whole-sidebar (existing Zustand state), per-status-group (Radix Collapsible), per-app-instance (Radix Collapsible). The `[` keyboard shortcut, `isTypingTarget` guard, and `!belowSidebarBreakpoint` desktop-only guard are preserved unchanged in `app.tsx`.
- **FR#13** shadcn Drawer replaces the hand-rolled log-detail-drawer.
- **FR#14** *(dropped — no shimmer/skeleton pattern exists in the codebase; the actual loading indicator is a Spinner component)*
- **FR#15** Manual `@floating-ui/dom` usage (`computePosition`/`autoUpdate`/`flip`/`offset`/`shift`) is removed. The package itself remains as a transitive dependency of `@radix-ui/react-popper` (which backs Radix's Popover/Tooltip). It is removed as a direct dependency from `package.json`.
- **FR#16** `utils/focus-trap.ts` is removed (orphaned after FR#7, FR#8).
- **FR#17** Tests for replaced components switch from `fireEvent` to `@testing-library/user-event` for richer interaction testing.

## Edge Cases

- **Token rename misses** — a `var(--bg-base)` reference in a CSS Module or inline style that the rename script misses, causing a runtime fallback to `initial`. Mitigation: the token rename script must be followed by a grep-verify step confirming zero remaining old token names across all CSS/TSX files.
- **`--accent` semantic swap** — old `--accent` (brand color) becomes `--primary`, while `--bg-active` (highlight) becomes `--accent`. A naive find-replace would break this. Mitigation: the rename script must process `--accent` → `--primary` and `--bg-active` → `--accent` in a specific order to avoid double-renaming. Use a two-pass approach or temporary sentinel names.
- **Chip discriminated union simplification** — `Chip`'s discriminated-union props (`variant: "kind"` requires `kind: ChipKind`; other variants disallow `kind` via `never`) is replaced by simpler Badge variants. Consumer call sites that relied on the type constraint need manual review.
- **Sidebar keyboard shortcut** — the current shortcut is `[` (bare key, not Cmd+B), guarded by `isTypingTarget()` to prevent firing while typing in inputs. shadcn Sidebar hardcodes `Cmd+B`. The vendored `components/ui/sidebar.tsx` must be edited to restore `[` with the typing-target guard.
- **Sidebar mobile breakpoint** — shadcn's internal mobile detection defaults to 768px; hassette uses 900px (`BREAKPOINT_SIDEBAR`). The vendored sidebar source must use hassette's breakpoint.
- **Command palette data fetching** — cmdk has its own async patterns. The existing react-query fetch of listeners must be preserved and wired into cmdk's search.
- **`diagnostics.tsx` direct CSS Module import** — imports `card.module.css` directly, bypassing the Card component. Must be converted to use the shadcn Card component directly.
- **shadcn Table wrapper div** — shadcn's generated `Table` component wraps `<table>` in an `overflow-x-auto` `<div>` that breaks `position: sticky` on `<thead>` by inserting a new scroll container between the sticky header and the real scroll ancestor (`.ht-table-card-scroll`). After `npx shadcn add table`, edit the generated `components/ui/table.tsx` to remove or neutralize the wrapper (`overflow-x: visible`).
- **Radius values** — shadcn derives radius from a base via `calc()`. Hassette's `--r-lg` (12px) and `--r-xl` (20px) don't match the formula output (10px, 14px). These slots need literal overrides, not the `calc()` chain.
- **SortHeader `<th>` ownership** — `SortHeader` currently returns its own `<th scope="col" aria-sort=...>`. Under TanStack Table + shadcn Table, header cells render inside `TableHead` (also a `<th>`). To avoid nested `<th>` (invalid HTML), rewrite `SortHeader` to return only inner content (button + filter popover). Thread `aria-sort`/`scope` up via `column.meta` or `TableHead` props. Update the convention example to match.
- **Log table sort state shape** — hassette's sort uses `{key, dir}` while TanStack uses `{id, desc}`. Small adapter functions are needed at this boundary, or (simpler) keep sort handlers calling directly into `use-log-filters.ts` and only use TanStack's `column.getIsSorted()` for display.

## Acceptance Criteria

- **AC#1** `cd frontend && npm run build` exits 0 (FR#1–FR#16).
- **AC#2** `cd frontend && npm run test` reports 0 failures (FR#3–FR#17).
- **AC#3** `cd frontend && npm run typecheck` exits 0 (FR#1–FR#16).
- **AC#4** All shadcn-named token aliases resolve correctly: `cd frontend && npm run build` succeeds with shadcn components referencing `var(--background)`, `var(--primary)`, etc. via the alias layer (FR#1, FR#2). Zero-remaining-old-names grep verification deferred to PR 2 when CSS Modules are actually converted.
- **AC#5** `grep -rn '@floating-ui' frontend/src/ --include='*.ts' --include='*.tsx' | grep -v node_modules` returns no results (FR#15).
- **AC#6** `ls frontend/src/utils/focus-trap.ts 2>/dev/null` returns no file (FR#16).
- **AC#7** `ls frontend/src/components/shared/button.tsx frontend/src/components/shared/badge.tsx frontend/src/components/shared/chip.tsx frontend/src/components/shared/card.tsx frontend/src/components/shared/tooltip.tsx frontend/src/components/shared/confirm-dialog.tsx frontend/src/components/shared/info-popover.tsx frontend/src/components/shared/column-filter-popover/index.tsx frontend/src/components/layout/command-palette.tsx 2>/dev/null` returns no files — all replaced hand-rolled components are deleted (FR#3–FR#9). Note: `time-preset-selector.tsx` and `sidebar.tsx` are restyled in place, not deleted.
- **AC#8** `ls frontend/src/components/ui/button.tsx frontend/src/components/ui/badge.tsx frontend/src/components/ui/card.tsx frontend/src/components/ui/tooltip.tsx frontend/src/components/ui/alert-dialog.tsx frontend/src/components/ui/popover.tsx frontend/src/components/ui/command.tsx frontend/src/components/ui/table.tsx frontend/src/components/ui/drawer.tsx 2>/dev/null | wc -l` returns 9 — all shadcn components are generated (FR#3–FR#14, excluding sidebar and time-preset-selector which use Tailwind restyle).
- **AC#9** `uv run nox -s e2e` passes (behavioral parity).
- **AC#10** Demo stack (`mise run demo`) renders all 7 pages without visual regression (FR#1–FR#16).

## Key Constraints

- **Do not wrap shadcn components in thin compatibility wrappers.** Update all consumer call sites directly to shadcn's prop API. Wrappers are deferred migration debt.
- **Do not call `getFilteredRowModel()` or `getSortedRowModel()` on the TanStack Table instance.** Filtering and sorting stay in `useLogFilters` as external pre-processing. TanStack Table receives already-processed data via `getCoreRowModel()` only.
- **Do not adopt TanStack's `columnVisibility` state management.** Keep `useColumnVisibility` as-is — it handles viewport-forced hiding (`REQUIRED_COLUMNS`, `viewportHidden`) that TanStack's visibility state has no concept of. Add a code comment at the `useReactTable({ columns: ... })` call site documenting this constraint, so a future contributor doesn't "fix" it by switching to TanStack's `columnVisibility` and reintroducing the viewport/required-column bugs.
- **Do not modify CSS Module files.** They must continue working for the transition period. PR 2 handles their conversion to Tailwind utilities.
- **Do not remove `tokens.css`.** Rewrite it with new names, but keep the file. PR 2 removes it after all `var()` references migrate to Tailwind utilities.
- **The token alias layer must not collide with existing names.** The alias block in `global.css` defines new names (`--primary`, `--background`, etc.) pointing at old values (`var(--accent)`, `var(--bg-page)`, etc.). Since aliases reference old names rather than replacing them, the `--accent` ↔ `--primary` swap ordering problem is eliminated.

## Dependencies and Assumptions

- **npm packages (add):** `@tanstack/react-table`, `@testing-library/user-event`, `cmdk` (shadcn Command dependency — may be auto-installed by `npx shadcn add command`).
- **npm packages (remove):** `@floating-ui/dom`.
- **shadcn components to generate:** Button, Badge, Card, Tooltip, AlertDialog, Popover, Command, Table, Drawer. (Sidebar uses Tailwind restyle + Radix Collapsible. TimePresetSelector uses Tailwind restyle only. Skeleton dropped — no shimmer pattern exists.)
- **Existing infrastructure:** React 19, Zustand, Tailwind v4, `@tailwindcss/vite`, `radix-ui` meta-package, `class-variance-authority`, `tailwind-merge`, `lucide-react`, `clsx` — all already installed on `frontend-migration`.
- **`cn()` utility** at `src/lib/utils.ts` — already exists from shadcn init.
- **Docker + Playwright** required for AC#9 and AC#10 (E2E tests and demo stack).
- **The `frontend-migration` branch** is the target — this PR does not go to `main` directly.
- **Prerequisite merge:** The working branch (`migration-part-two`) must merge `origin/frontend-migration` before any work begins. The spec 020 migration (React 19, Zustand, Tailwind v4, shadcn init, `components.json`, `cn()` utility) landed on `frontend-migration` via PR #1466 — without that merge, the working branch is still on Preact with no shadcn infrastructure.

## Architecture

### Phase 1: Token alias layer

Instead of destructively renaming tokens across all 63 CSS Module files (which PR 2 will rewrite anyway during Tailwind conversion), add the 136 new shadcn-named custom properties as an alias block in `global.css` pointing at the existing token values. Old names remain in CSS Modules untouched; new names are available everywhere for shadcn components and new code.

This eliminates the `--accent` ↔ `--primary` swap collision entirely — aliases can be declared in any order since they reference the old names, not replace them. The "grep for zero remaining old names" verification (AC#4) moves to PR 2, when CSS Modules are actually converted.

**Token mapping summary** (136 tokens total):

| Category | Count | Strategy |
|---|---|---|
| shadcn-standard (direct equivalents) | 13 | Alias to shadcn's canonical name |
| tailwind-native (value matches Tailwind's built-in scale) | 43 | Alias to Tailwind-compatible name |
| custom-extend (no shadcn/Tailwind equivalent) | 80 | Alias to shadcn-compatible prefixed names |

**Critical aliases:**
- `--primary: var(--accent)` (brand/action color)
- `--accent: var(--bg-active)` (highlighted background — matches shadcn's semantic role)
- `--primary-foreground: var(--accent-ink)`
- `--background: var(--bg-page)`, `--card: var(--bg-surface)`, `--muted: var(--bg-sunken)`
- `--foreground: var(--ink-1)`, `--muted-foreground: var(--ink-3)`
- `--line-1` → `--border`
- `--err` → `--destructive`
- `--input-bg` → `--input`
- `--font-body` → `--font-sans`, `--font-display` → `--font-heading`
- All `--sp-*` → `--spacing-*` (renumbered to match Tailwind's 4px multiplier scale)
- All `--sz-*` → `--size-*`
- All `--ok`/`--warn`/`--cancel`/`--mute` → `--status-*`
- All `--job`/`--listener` → `--handler-*`

After the script runs, update `global.css`'s shadcn `@theme inline` block and `:root`/`[data-theme="dark"]` blocks to use the real hassette token values instead of shadcn's defaults. This resolves the `--accent` collision.

**Verification:** grep for any remaining old token names (AC#4). The script itself serves as the "build the lever" artifact — rerunnable if files are added.

### Phase 2: Leaf components (Button, Badge, Card, Tooltip)

Generate each via `npx shadcn@latest add <component>`. Then update all consumer call sites directly to shadcn's API (no thin wrappers).

**Button** (10 consumers): `variant` mapping: `default` → `default`, `primary` → `default` (shadcn's default is primary-colored), `success`/`warning`/`info`/`danger` → custom variants added to the generated `button.tsx`. `ghost` boolean → `variant="ghost"`. `size` mapping: `default` → `default`, `sm` → `sm`, `xs` → custom size. `icon` boolean → `variant="ghost" size="icon"`. `buttonRef` → standard `React.forwardRef` (shadcn Button already uses `forwardRef`). The forced `type="button"` default stays.

**Badge** (7 badge + 10 chip consumers): shadcn Badge with extended variants covering both the current Badge's `BadgeVariant` set and the Chip's simplified kind-based coloring. The Chip's discriminated-union interface is flattened.

**Card** (5 component consumers + 1 direct `.module.css` import): shadcn Card with `variant` support (`default`/`compact`/`config`/`error`). Consumers: `code-tab.tsx`, `config-tab.tsx`, `component-showcase.tsx`, `error-boundary.tsx`, `config-schema-view.tsx`. Fix `diagnostics.tsx`'s direct `card.module.css` import (bypasses the Card component). Note: `overview-tab.tsx`, `app-logs-panel.tsx`, and `execution-logs.tsx` import `TableCard` (a distinct wrapper component), not `Card`.

**Tooltip** (1 consumer): shadcn Tooltip (Radix-based, JS-positioned) replaces the CSS-only tooltip.

### Phase 3: Interactive components (AlertDialog, Popover, Command, Select)

**AlertDialog** (1 consumer via `action-buttons.tsx`): Replace `confirm-dialog.tsx`. The `tone` prop (`default`/`danger`) maps to AlertDialog's button styling. Remove manual focus trap, Escape/Tab handling, random-id aria wiring — Radix provides all of these.

**Popover** (1 + 5 consumers): Replace both `info-popover.tsx` (click-triggered, 1 consumer: `config-schema-view.tsx`) and `column-filter-popover/` (5 consumers: `column-picker.tsx`, `use-log-table.tsx`, `sort-header.tsx`, `table-footer.tsx`, `apps.tsx`). Remove `@floating-ui/dom` positioning (`computePosition`/`autoUpdate`/`flip`/`offset`/`shift`) and `wrapFocusOnTab` focus trap. Radix Popover handles positioning and focus internally. The `column-filter-popover`'s `ignoreNextClick` guard and `size()` middleware need evaluation — the `ignoreNextClick` pattern may not be needed with Radix's built-in open/close state management.

**Command** (1 consumer via `app.tsx`): Replace `command-palette.tsx` with shadcn Command (wraps cmdk). Wire the existing react-query listener fetch into cmdk's item filtering. Replace manual arrow-key navigation and sentinel-div focus trap with cmdk's built-in keyboard handling. Preserve the `Cmd+K`/`Ctrl+K` trigger (already standard in cmdk).

**Time preset selector** (1 consumer via `status-bar.tsx`): Restyle with Tailwind utilities and `cn()`, keeping the existing `<select>` (mobile) and `<button aria-pressed>` (desktop) markup unchanged. No shadcn component generation — the component has no bespoke behavior to replace, and a future date-range feature will dictate the real shadcn component choice.

### Phase 4: Tables (TanStack Table + shadcn Table)

This is an adapter layer, not a ground-up rewrite. The key insight: existing hooks (`useLogFilters`, `useColumnVisibility`, `useRovingTabIndex`) are preserved unchanged. TanStack Table is a controlled display layer.

**Log table migration:**

1. Convert `COLUMNS` array from hassette's `ColumnDef` to TanStack's `ColumnDef<LogEntry>[]` with `accessorFn`, `header` (reusing `SortHeader` as custom renderer), and `cell` closures. Column metadata that TanStack doesn't model (`shortLabel`, `mobileWidth`, `ariaLabel`) goes in `column.meta`.
2. Replace `log-table-view.tsx`'s hand-written `<table>`/`<thead>`/`<tbody>` with `useReactTable({ data: visibleEntries, columns, getCoreRowModel: getCoreRowModel() })` + shadcn `Table`/`TableHeader`/`TableBody`/`TableRow`/`TableCell`.
3. The giant `isColumnVisible("x") && <td>...</td>` chain in `log-table-row.tsx` collapses into `row.getVisibleCells().map(cell => flexRender(...))`. Column visibility is controlled externally by filtering the columns array via `useColumnVisibility`'s output.
4. `SortHeader`'s combined sort-button + filter-popover UI has no TanStack equivalent — it stays as a custom column `header` renderer. Sort state from `use-log-filters.ts` drives `column.getIsSorted()` for display (arrow direction, `aria-sort`) only; the actual comparator still runs in `sortEntries`.
5. `useRovingTabIndex` wires against `table.getRowModel().rows` (same pattern as today).

**Execution table migration:**

Simpler — 5 columns, no sorting, no filtering, no column visibility. Convert to TanStack `ColumnDef<ExecutionRecord>[]` + shadcn Table for consistency with log table. Keep the `showAll`/`INITIAL_ROWS` slice logic.

**Log detail drawer → shadcn Drawer:**

Replace the hand-rolled drawer with shadcn Drawer. Preserve the CSS-grid desktop / overlay mobile layout in `LogTableWithDrawer`.

**Log-table subsystem files (14 source files):** `column-picker.tsx`, `constants.ts`, `execution-id-link.tsx`, `index.ts`, `log-detail-drawer.tsx`, `log-table-header.tsx`, `log-table-row.tsx`, `log-table-view.tsx`, `log-table-with-drawer.tsx`, `types.ts`, `use-column-visibility.ts`, `use-log-data.ts`, `use-log-filters.ts`, `use-log-table.tsx`. Of these: `log-table-row.tsx` and `log-table-header.tsx` are deleted (absorbed into `ColumnDef` declarations); `log-table-view.tsx` is rewritten; `constants.ts` and `types.ts` are rewritten for TanStack types; `use-log-table.tsx` is simplified; `column-picker.tsx` updates ColumnFilterPopover → Popover; `log-detail-drawer.tsx` rewrites to shadcn Drawer; `log-table-with-drawer.tsx` updates drawer integration; `index.ts` updates re-exports. `use-column-visibility.ts`, `use-log-data.ts`, `use-log-filters.ts`, and `execution-id-link.tsx` are preserved unchanged. `table-card.tsx` and `table-footer.tsx` (outside the log-table directory) may be kept as thin layout wrappers or absorbed.

### Phase 5: Sidebar (Tailwind restyle + Radix Collapsible)

Restyle the existing `sidebar.tsx` with Tailwind utilities and `cn()`. Use Radix `Collapsible` directly for the two accordion tiers (per-status-group and per-app-instance expand) — the same primitive shadcn Sidebar wraps internally, without the 700-line vendored file and the two required hand-edits.

This avoids importing shadcn Sidebar entirely. The sidebar's business logic, keyboard handling, and mobile drawer behavior stay in the codebase as owned code, not vendored code that needs `// HASSETTE: must-preserve-on-regen` markers.

**Structure (preserved, restyled):**
- Whole-sidebar collapse: existing Zustand `sidebarCollapsed` state — no change to mechanism, just Tailwind styling.
- Brand block: wordmark + version chip + collapse toggle — restyled with Tailwind.
- Command palette trigger: `⌘K`/`Ctrl+K` hint button — restyled with Tailwind.
- Primary nav: `NAV_PAGES` iteration with active-route prefix-match — restyled with Tailwind.
- App nav status groups: wrap each `GroupDef` in Radix `Collapsible` — `CollapsibleTrigger` on the group header (with tone-based coloring), `CollapsibleContent` on the group content. `useGroupOpen` hook preserved.
- Per-app instance expand: Radix `Collapsible` for instance list toggle.
- App search filter: search input wired to `search`/`setSearch` state, `${filteredCount}/${totalCount}` label, loading spinner, empty state — restyled with Tailwind.
- Footer: `SystemHealth` + `ThemeToggle` — restyled with Tailwind.
- Mobile drawer: existing dual-render architecture in `app.tsx` stays for now (manual `inert` toggling, focus management). This is a contained piece of owned code; replacing it with shadcn's Sheet-based approach can be evaluated independently in a future PR if desired. Delete `.ht-drawer`/`.ht-drawer-backdrop` global CSS and replace with Tailwind utilities.

**Keyboard shortcut:** `[` key handler stays in `app.tsx` as-is — no vendored-file edit needed. The `isTypingTarget()` guard and `!belowSidebarBreakpoint` desktop-only guard are both preserved unchanged.

**Business logic preserved unchanged:** `groupAndSortApps`, `worstStatus`, `statusPriority` sort, `GroupDef` tone/defaultOpen table, status-bar chrome fallback (`useSidebarHidden`), app-key/instance status aggregation, app search filtering (`search`/`setSearch`, `filteredCount`/`totalCount`, loading/empty states).

### Phase 6: Expand items (Drawer, Skeleton, userEvent)

**Drawer** (FR#13): Generated via `npx shadcn add drawer`. Used by the log-detail-drawer replacement in Phase 4.

**userEvent** (FR#17): Add `@testing-library/user-event` to dev dependencies. Update tests for replaced components to use `userEvent.click()`, `userEvent.type()`, etc. instead of `fireEvent.click()`, `fireEvent.change()`.

## Implementation Preferences

- **shadcn/ui New York style** (already configured in `components.json`).
- **Generate components via `npx shadcn@latest add <component>`**, then customize variants/sizes to match current behavior.
- **No thin wrappers** — update all consumer call sites directly to shadcn's API.
- **`cn()` utility** (`src/lib/utils.ts`) for all className composition — replace `clsx()` calls in affected components.
- **TanStack Table v8 API** (`useReactTable`, `getCoreRowModel`) — not the in-progress v9.
- **Token alias layer** in `global.css` — new shadcn-named custom properties pointing at existing token values. CSS Modules untouched until PR 2.
- **Commit ordering:** tokens → leaf components → interactive components → tables → sidebar → expand items → cleanup.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `components/shared/button.tsx` + `.module.css` + `.test.tsx` | shadcn Button (`components/ui/button.tsx`) | Delete hand-rolled; update all 10 consumers |
| `components/shared/badge.tsx` + `.module.css` + `.test.tsx` | shadcn Badge (`components/ui/badge.tsx`) | Delete hand-rolled; update all 7 consumers |
| `components/shared/chip.tsx` + `.module.css` + `.test.tsx` | shadcn Badge variants | Delete; update all 9 consumers to Badge |
| `components/shared/card.tsx` + `.module.css` + `.test.tsx` | shadcn Card (`components/ui/card.tsx`) | Delete hand-rolled; update 5 component consumers + 1 direct `.module.css` import |
| `components/shared/tooltip.tsx` + `.module.css` + `.test.tsx` | shadcn Tooltip (`components/ui/tooltip.tsx`) | Delete hand-rolled; update 1 consumer |
| `components/shared/confirm-dialog.tsx` + `.module.css` + `.test.tsx` | shadcn AlertDialog (`components/ui/alert-dialog.tsx`) | Delete hand-rolled; update 1 consumer |
| `components/shared/info-popover.tsx` + `.module.css` + `.test.tsx` | shadcn Popover (`components/ui/popover.tsx`) | Delete hand-rolled; update 1 consumer |
| `components/shared/column-filter-popover/` (index.tsx + .module.css) | shadcn Popover | Delete directory; update 5 consumers + 1 direct CSS import (`apps.tsx`) |
| `components/layout/command-palette.tsx` + `.module.css` + `.test.tsx` | shadcn Command (`components/ui/command.tsx`) | Delete hand-rolled; update 1 consumer |
| `components/layout/time-preset-selector.tsx` + `.module.css` + `.test.tsx` | Tailwind restyle (no shadcn component) | Restyle in place; shadcn replacement deferred to date-range feature |
| `components/shared/log-table/` (14 source files) | TanStack Table + shadcn Table + Drawer | Rewrite subsystem; delete `log-table-row.tsx`, `log-table-header.tsx` |
| `components/shared/execution-table.tsx` + `.module.css` + `.test.tsx` | TanStack Table + shadcn Table | Rewrite |
| `components/shared/table-card.tsx` + `.module.css` | Evaluate: keep as layout wrapper or absorb | May delete |
| `components/shared/table-footer.tsx` + `.module.css` | Evaluate: keep as layout wrapper or absorb | May delete |
| `components/layout/sidebar.tsx` + `.module.css` + `.test.tsx` | Tailwind restyle + Radix Collapsible (no shadcn Sidebar) | Restyle in place; add Radix Collapsible for accordion tiers |
| `utils/focus-trap.ts` | Radix internal focus trapping | Delete |
| `@floating-ui/dom` (package) | Radix internal positioning | Remove from `package.json` |
| `tokens.css` (naming only) | shadcn-compatible token names | Rewrite in place (file stays until PR 2) |

## Convention Examples

### shadcn component usage (target convention)

**Source:** shadcn/ui docs — Button

```tsx
import { Button } from "@/components/ui/button";

<Button variant="destructive" size="sm" onClick={handleDelete}>
  Delete
</Button>
```

Components are imported from `@/components/ui/`, use `variant`/`size` props, and compose with `cn()` for additional className needs.

### Zustand selector pattern (existing convention to preserve)

**Source:** `frontend/src/state/store.ts` (established in spec 020)

```tsx
const connection = useAppStore((s) => s.connection);
const theme = useAppStore((s) => s.theme);
```

One `useAppStore()` call per field — never destructure the whole store or use multi-field object selectors.

### Test pattern with renderWithAppState (existing convention to preserve)

**Source:** `frontend/src/components/shared/confirm-dialog.test.tsx`

```tsx
function renderDialog(overrides: Partial<ConfirmDialogProps> = {}) {
  const props = { title: "Confirm", body: "Are you sure?", confirmLabel: "Yes",
    onConfirm: vi.fn(), onCancel: vi.fn(), ...overrides };
  return { ...render(<ConfirmDialog {...props} />), props };
}

it("calls onConfirm when confirm button is clicked", async () => {
  const { props } = renderDialog();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Yes" }));
  expect(props.onConfirm).toHaveBeenCalledOnce();
});
```

Tests use a prop-builder helper, render directly (or via `renderWithAppState` for store-dependent components), and assert via `screen` queries. The target convention switches from `fireEvent` to `userEvent.setup()` for interaction testing.

### TanStack Table column definition (target convention)

**Source:** TanStack Table v8 docs + shadcn data-table example

```tsx
const columns: ColumnDef<LogEntry>[] = [
  {
    id: "level",
    accessorFn: (row) => row.level,
    meta: { shortLabel: "Lvl", ariaLabel: "Log level", width: "70px", mobileWidth: "32px" },
    header: ({ column }) => (
      <SortHeader sortKey="level" sort={sortState} onSort={setSort}
        filterContent={levelFilterSelect} hasActiveFilter={levelFilter !== DEFAULT_LEVEL}
        ariaLabel="Log level">
        {isMobile ? "Lvl" : "Level"}
      </SortHeader>
    ),
    cell: ({ row }) => (
      <span className={cn("text-xs font-medium", levelColorClass(row.original.level))}>
        {isMobile ? (LEVEL_ABBREV[row.original.level] ?? row.original.level) : row.original.level}
      </span>
    ),
  },
];
```

Custom column metadata goes in `column.meta`. `SortHeader` is reused as a custom header renderer. Cell rendering is inline, not per-column JSX branches.

## Alternatives Considered

### Keep hand-rolled components, just add Tailwind styling

Restyle existing components with Tailwind utilities instead of replacing them with shadcn. **Rejected:** the problem isn't styling — it's the bespoke behavior code (focus traps, floating-ui positioning, keyboard handling). Restyling doesn't remove the maintenance burden.

### Headless UI instead of shadcn

Use Radix UI primitives directly without shadcn's styled layer. **Rejected:** shadcn is built on Radix and adds sensible defaults, consistent styling, and the `npx shadcn add` workflow. Using Radix directly means writing the same styling and configuration that shadcn already provides. shadcn's training-data presence also helps AI consistency.

### Thin wrappers around shadcn to preserve current prop APIs

Wrap shadcn Button/Badge/Card to keep the current prop interfaces unchanged, minimizing consumer migration. **Rejected by user preference.** Wrappers are deferred migration debt — one-time churn to update all consumers is preferable to maintaining a compatibility layer indefinitely.

### Keep custom tables, just use shadcn Table markup

Use shadcn's Table/TableRow/TableCell components for consistent markup, but keep all custom hooks and rendering logic. **Rejected:** the custom per-column JSX branching pattern (`isColumnVisible("x") && <td>...</td>`) is the core maintenance burden. TanStack Table's `ColumnDef` declarations eliminate it. The existing hooks (`useLogFilters`, `useColumnVisibility`, `useRovingTabIndex`) are preserved regardless.

## Test Strategy

### Required Test Types

- **Unit (vitest):** Update all existing tests for replaced components. New tests for any significant new behavior (e.g., TanStack Table column definitions, sidebar collapse bridging). Switch interaction tests to `userEvent` for affected files.
- **E2E (Playwright via `nox -s e2e`):** Existing suite must pass — behavioral parity, not new test coverage.
- **Visual QA (demo stack):** `mise run demo` → verify all 7 pages render correctly.

### Existing Tests to Adapt

All test files for replaced components need updates to match new APIs:

- `components/shared/button.test.tsx` — update prop names (`ghost` boolean → `variant="ghost"`)
- `components/shared/badge.test.tsx` — update variant names
- `components/shared/chip.test.tsx` — rewrite for Badge variant API (discriminated union gone)
- `components/shared/card.test.tsx` — update variant names
- `components/shared/tooltip.test.tsx` — update for Radix-based Tooltip API
- `components/shared/confirm-dialog.test.tsx` — rewrite for AlertDialog compound-component API
- `components/shared/info-popover.test.tsx` — rewrite for Popover API
- `components/layout/command-palette.test.tsx` — rewrite for Command/cmdk API
- `components/layout/time-preset-selector.test.tsx` — rewrite for NativeSelect/ToggleGroup
- `components/shared/log-table/*.test.tsx` — update for TanStack Table rendering
- `components/shared/execution-table.test.tsx` — update for TanStack Table rendering
- `components/layout/sidebar.test.tsx` — rewrite for shadcn Sidebar compound-component API

### New Test Coverage

- TanStack Table column definitions for log table and execution table (FR#11)
- Sidebar Zustand ↔ shadcn state bridging (FR#12)
- Command palette cmdk integration with react-query data (FR#9)

### Tests to Remove

- Tests that directly test focus-trap logic in `confirm-dialog.test.tsx` and `command-palette.test.tsx` — Radix/cmdk own focus management now. Tests should verify the *outcome* (dialog traps focus) via user interaction, not the mechanism.

## Documentation Updates

- **CLAUDE.md (CSS Architecture section):** Update component references — `Button`, `Badge`, `Chip`, `Card` are now shadcn components in `components/ui/`, not shared components in `components/shared/`. Update the "Shared components" guidance to reference shadcn components. Update token naming in any examples.
- **CLAUDE.md (Common Commands section):** No changes needed.
- **`design/context.md`:** Deferred to PR 3 — full rewrite for shadcn vocabulary.

## Impact

### Changed Files

**Cross-cutting (highest risk):**
- modify `frontend/src/tokens.css` — no changes (old names stay; aliases live in global.css)
- modify `frontend/src/global.css` — add token alias block and update shadcn theme block with real token values
- modify `frontend/package.json` — add TanStack Table, user-event; remove floating-ui

**New files (shadcn generated + customized):**
- create `frontend/src/components/ui/button.tsx`
- create `frontend/src/components/ui/badge.tsx`
- create `frontend/src/components/ui/card.tsx`
- create `frontend/src/components/ui/tooltip.tsx`
- create `frontend/src/components/ui/alert-dialog.tsx`
- create `frontend/src/components/ui/popover.tsx`
- create `frontend/src/components/ui/command.tsx`
- create `frontend/src/components/ui/table.tsx`
- create `frontend/src/components/ui/drawer.tsx`

**Deleted files:**
- delete `frontend/src/components/shared/button.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/badge.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/chip.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/card.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/tooltip.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/confirm-dialog.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/info-popover.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/column-filter-popover/` (directory)
- delete `frontend/src/components/layout/command-palette.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/layout/time-preset-selector.tsx` + `.module.css` + `.test.tsx`
- delete `frontend/src/components/shared/log-table/log-table-row.tsx` + `.module.css`
- delete `frontend/src/components/shared/log-table/log-table-header.tsx` + `.module.css`
- delete `frontend/src/utils/focus-trap.ts`

**Modified files (consumer updates):**
- modify `frontend/src/components/layout/sidebar.tsx` — restyle with Tailwind + add Radix Collapsible for accordion tiers
- modify `frontend/src/components/layout/sidebar.module.css` — restyle with Tailwind (may be reduced or deleted)
- modify `frontend/src/components/shared/log-table/log-table-view.tsx` — rewrite for TanStack Table
- modify `frontend/src/components/shared/log-table/use-log-table.tsx` — simplify orchestration; fix direct `column-filter-popover/index.module.css` import (same pattern as `diagnostics.tsx`/`card.module.css` — target directory is deleted by FR#8)
- modify `frontend/src/components/shared/log-table/log-detail-drawer.tsx` — rewrite for shadcn Drawer
- modify `frontend/src/components/shared/log-table/constants.ts` — TanStack ColumnDef types
- modify `frontend/src/components/shared/log-table/types.ts` — TanStack types
- modify `frontend/src/components/shared/execution-table.tsx` — rewrite for TanStack Table
- modify `frontend/src/components/shared/action-buttons.tsx` — update Button/AlertDialog usage
- modify `frontend/src/components/shared/sort-header.tsx` — may need minor interface updates
- modify `frontend/src/components/app-detail/code-tab.tsx` — update Button/Card usage
- modify `frontend/src/components/app-detail/handlers-tab.tsx` — update Button/Badge/Chip usage
- modify `frontend/src/components/app-detail/job-detail.tsx` — update Button/Chip usage
- modify `frontend/src/components/app-detail/registration-footer.tsx` — update Button usage
- modify `frontend/src/components/app-detail/app-detail-header.tsx` — update Badge/Chip usage
- modify `frontend/src/components/app-detail/detail-header.tsx` — update Badge/Chip usage
- modify `frontend/src/components/app-detail/execution-detail.tsx` — update Badge usage
- modify `frontend/src/components/app-detail/multi-instance.tsx` — update Badge usage
- modify `frontend/src/components/app-detail/unified-handler-row.tsx` — update Badge/Chip usage
- modify `frontend/src/components/app-detail/listener-detail.tsx` — update Chip usage
- modify `frontend/src/components/app-detail/config-tab.tsx` — update Card usage
- modify `frontend/src/components/app-detail/handler-health-card.tsx` — update Tooltip/Chip usage
- modify `frontend/src/components/design/component-showcase.tsx` — update all shared component usage
- modify `frontend/src/components/layout/error-boundary.tsx` — update Button/Card usage
- modify `frontend/src/components/layout/status-bar.tsx` — update Button usage, time-preset-selector import
- modify `frontend/src/components/shared/config-schema-view.tsx` — update InfoPopover and Card usage
- modify `frontend/src/components/shared/log-table/column-picker.tsx` — update ColumnFilterPopover to Popover
- modify `frontend/src/components/shared/log-table/log-table-with-drawer.tsx` — update drawer integration
- modify `frontend/src/components/shared/log-table/index.ts` — update re-exports
- modify `frontend/src/components/shared/table-footer.tsx` — update ColumnFilterPopover usage
- modify `frontend/src/pages/apps.tsx` — update Button usage, ColumnFilterPopover CSS import
- modify `frontend/src/pages/apps-table-row.tsx` — update Badge/Chip usage
- modify `frontend/src/pages/handlers.tsx` — update Button/Chip/Badge usage
- modify `frontend/src/pages/handlers-rows.tsx` — update Chip usage
- modify `frontend/src/pages/diagnostics.tsx` — fix direct `card.module.css` import
- modify `frontend/src/app.tsx` — update CommandPalette/Sidebar integration
- modify all `.module.css` files — token name references updated by rename script

### Behavioral Invariants

- All existing page routes and URL structures must continue working.
- WebSocket connection, state management, and data fetching behavior must be unchanged.
- The sidebar's `[` keyboard shortcut, status-group business logic, and status-bar chrome fallback must be preserved.
- The log table's column visibility persistence (localStorage), sort state URL-param sync, and 200-row render cap must be preserved.
- The command palette's listener search functionality must continue working.

### Blast Radius

- **E2E tests:** May need selector updates if data-testid attributes change on replaced components.
- **Doc screenshots:** Will need regeneration (deferred to PR 3).
- **`design/context.md`:** References old component names and token names (deferred to PR 3).
- **CSS Module files:** Untouched in this PR — the token alias layer means CSS Modules keep referencing old names until PR 2 converts them to Tailwind utilities.

## Open Questions

None — all unknowns resolved during investigation.
