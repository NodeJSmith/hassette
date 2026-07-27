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
