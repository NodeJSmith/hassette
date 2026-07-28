# Context: Replace Hand-Rolled Components with shadcn/ui

## Problem & Motivation

The hassette dashboard has 13 hand-rolled interactive components — popovers with manual floating-ui positioning, dialogs with manual focus traps, tooltips with CSS-only positioning, tables with hand-written per-column JSX. Each requires triple-checked CSS and custom accessibility wiring. AI agents produce inconsistent output because there is no shared component vocabulary. Spec 020 (PR #1466) replaced the framework layer (Preact -> React 19, Zustand, Tailwind v4, shadcn init) but generated no shadcn components. The 136 custom design tokens use old `--bg-*`/`--ink-*`/`--accent-*` naming that collides with shadcn's theme variables.

## Visual Artifacts

None.

## Key Decisions

1. **Token alias layer instead of destructive rename** — add new shadcn-named custom properties as aliases pointing at existing token values in `global.css`. CSS Modules stay untouched until PR 2's Tailwind conversion. Eliminates the `--accent` / `--primary` swap collision.
2. **No thin wrappers** — update all consumer call sites directly to shadcn's prop API. One-time churn is preferable to maintaining compatibility wrappers.
3. **TanStack Table as adapter layer** — existing hooks (`useLogFilters`, `useColumnVisibility`, `useRovingTabIndex`) are preserved unchanged. TanStack Table receives pre-filtered, pre-sorted data via `getCoreRowModel()` only. Do NOT call `getFilteredRowModel()` or `getSortedRowModel()`.
4. **Sidebar: Tailwind restyle + Radix Collapsible** — no shadcn Sidebar. The sidebar stays as owned code with Radix Collapsible for the two accordion tiers (per-status-group, per-app-instance). All business logic, keyboard handling, and mobile drawer behavior preserved.
5. **SortHeader rewrite** — SortHeader must be rewritten to return only inner content (button + filter popover), not a `<th>`. `TableHead` (shadcn's `<th>`) owns `aria-sort`/`scope`. This avoids nested `<th>` (invalid HTML).
6. **shadcn Table wrapper fix** — after generating `components/ui/table.tsx`, remove or neutralize the wrapper `<div>` (`overflow-x: visible`) to prevent breaking `position: sticky` on `<thead>`.
7. **TimePresetSelector: Tailwind restyle only** — no shadcn component generation. A future date-range feature will dictate the real shadcn component choice.
8. **Skeleton dropped** — no shimmer/skeleton pattern exists in the codebase.

## Constraints & Anti-Patterns

- Do NOT wrap shadcn components in thin compatibility wrappers.
- Do NOT call `getFilteredRowModel()` or `getSortedRowModel()` on the TanStack Table instance.
- Do NOT adopt TanStack's `columnVisibility` state management. Keep `useColumnVisibility` as-is. Add a code comment at the `useReactTable({ columns: ... })` call site documenting this constraint.
- Do NOT modify CSS Module files. They stay untouched until PR 2.
- Do NOT remove `tokens.css`. Keep the file with old names; aliases live in `global.css`.
- Non-goals: CSS Module -> Tailwind conversion (PR 2), removing CSS lint tools (PR 2), rewriting `design/context.md` (PR 3), regenerating doc screenshots (PR 3), StrictMode (PR 2), table virtualization (follow-up issue).
- **Prerequisite merge:** the working branch must merge `origin/frontend-migration` before any work begins.

## Design Doc References

- `## Architecture` — six phases: token alias, leaf components, interactive components, tables, sidebar, expand items
- `## Edge Cases` — token rename misses, `--accent` swap, SortHeader `<th>`, Table wrapper div, sidebar keyboard shortcut, command palette data fetching
- `## Replacement Targets` — complete table of old -> new component mappings
- `## Test Strategy` — existing tests to adapt, new test coverage needed, tests to remove
- `## Impact > Changed Files` — exhaustive file inventory with change verbs

## Convention Examples

### shadcn component usage (target convention)

**Source:** shadcn/ui docs -- Button

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

One `useAppStore()` call per field -- never destructure the whole store or use multi-field object selectors.

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

Note: `SortHeader` emits only inner content (not a `<th>`). `TableHead` owns the `<th>` with `aria-sort`/`scope` threaded via `column.meta`.
