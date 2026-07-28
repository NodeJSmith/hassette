import type { ReactNode } from "react";

/**
 * A single column filter entry: whether it is active, a label for the mobile
 * filter panel, and the filter UI content rendered in both the desktop popover
 * and the mobile consolidated panel.
 */
export interface ColumnFilter {
  active: boolean;
  label: string;
  content: ReactNode;
}

/**
 * A map from column id to its filter definition. Defined once per page and
 * consumed by both SortHeader (desktop popovers) and TableFooter (mobile panel).
 */
export type ColumnFilters = Record<string, ColumnFilter>;

// Shared column metadata fields TanStack doesn't model natively, common to
// every table in this app (log-table-view.tsx and execution-table.tsx both
// need per-cell classNames and per-cell extra props). Each table file adds
// its own additional augmentation for fields unique to that table (e.g.
// `ariaLabel` for log-table-view, `headerClassName` for execution-table) —
// TanStack's ColumnMeta is a single interface per program, so these merge.
declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- must match TanStack's ColumnMeta<TData, TValue> signature exactly for declaration merging
  interface ColumnMeta<TData, TValue> {
    cellClassName?: string;
    cellProps?: (entry: TData) => Record<string, unknown>;
  }
}
