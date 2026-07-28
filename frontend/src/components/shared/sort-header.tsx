import type { ReactNode } from "react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import { FilterIcon } from "./filter-icon";
import styles from "./sort-header.module.css";

export interface SortState<K extends string = string> {
  key: K;
  dir: "asc" | "desc";
}

const ARROW_FOR_DIRECTION: Record<"asc" | "desc", string> = { asc: " ↑", desc: " ↓" };

// Exported so callers that own the real <th> (TableHead in log-table-view.tsx)
// can compute `aria-sort` themselves — SortHeader no longer renders a <th>.
export const ARIA_SORT_FOR_DIRECTION: Record<"asc" | "desc", "ascending" | "descending"> = {
  asc: "ascending",
  desc: "descending",
};

interface BaseProps {
  ariaLabel?: string;
  className?: string;
  "data-testid"?: string;
  children: ReactNode;
}

// Sort fields are all-or-nothing in practice (either fully managed, or omitted
// entirely for a filter-only or plain-label header), but that isn't worth
// enforcing at the type level — they're simply optional together.
interface SortProps<K extends string = string> extends BaseProps {
  sortKey?: K;
  sort?: SortState<K>;
  onSort?: (s: SortState<K>) => void;
}

// Filter axis — orthogonal, optional, independent of sort
interface WithFilter {
  filterContent: ReactNode;
  hasActiveFilter: boolean;
}

interface WithoutFilter {
  filterContent?: never;
  hasActiveFilter?: never;
}

type FilterProps = WithFilter | WithoutFilter;

type Props<K extends string = string> = SortProps<K> & FilterProps;

/**
 * Renders only the inner content of a column header (sort button + filter
 * popover) — never the `<th>` itself. The caller (shadcn's `TableHead`) owns
 * the `<th>` element, `scope="col"`, and `aria-sort`. This avoids nesting a
 * `<th>` produced here inside the `<th>` TanStack/shadcn already render.
 */
export function SortHeader<K extends string = string>(props: Props<K>) {
  const { className, "data-testid": testId, children, ariaLabel } = props;

  // Filter state — local per-instance
  const [filterOpen, setFilterOpen] = useState(false);

  // Determine sort axis
  const hasSortProps = props.sortKey !== undefined && props.sort !== undefined && props.onSort !== undefined;

  let active = false;
  let direction: "asc" | "desc" = "asc";
  let sortClickHandler: (() => void) | undefined;

  if (hasSortProps) {
    const { sortKey, sort, onSort } = props as Required<Pick<SortProps<K>, "sortKey" | "sort" | "onSort">>;
    active = sort.key === sortKey;
    direction = active ? sort.dir : "asc";
    sortClickHandler = () => onSort({ key: sortKey, dir: active && sort.dir === "asc" ? "desc" : "asc" });
  }

  const hasFilter = props.filterContent !== undefined && props.filterContent !== null;
  const arrow = active ? ARROW_FOR_DIRECTION[direction] : "";

  // Sort button or plain label
  const sortElement = hasSortProps ? (
    <button
      type="button"
      className={cn(styles.sortHeader, active && styles.active)}
      data-testid="sort-header-btn"
      aria-label={ariaLabel ? `Sort by ${ariaLabel}` : undefined}
      onClick={sortClickHandler}
    >
      {children}
      <span aria-hidden="true">{arrow}</span>
    </button>
  ) : (
    <span>{children}</span>
  );

  if (!hasFilter) {
    return (
      <span className={className} data-testid={testId}>
        {sortElement}
      </span>
    );
  }

  return (
    <div className={cn(styles.headerInner, className)} data-testid={testId}>
      {sortElement}
      <Popover open={filterOpen} onOpenChange={setFilterOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={cn(styles.filterBtn, props.hasActiveFilter && styles.filterActive)}
            data-testid="filter-btn"
            aria-label={ariaLabel ? `Filter ${ariaLabel}` : undefined}
          >
            <FilterIcon active={props.hasActiveFilter} />
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" data-testid="sort-header-filter-popover" className="w-auto">
          {props.filterContent}
        </PopoverContent>
      </Popover>
    </div>
  );
}
