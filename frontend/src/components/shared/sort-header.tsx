import clsx from "clsx";
import type { ReactNode } from "react";
import { useRef, useState } from "react";

import { ColumnFilterPopover } from "./column-filter-popover/index";
import { FilterIcon } from "./filter-icon";
import styles from "./sort-header.module.css";

export interface SortState<K extends string = string> {
  key: K;
  dir: "asc" | "desc";
}

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

export function SortHeader<K extends string = string>(props: Props<K>) {
  const { ariaLabel, className, "data-testid": testId, children } = props;

  // Filter state — local per-instance
  const [filterOpen, setFilterOpen] = useState(false);
  const filterTriggerRef = useRef<HTMLButtonElement>(null);

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

  const arrow = active ? (direction === "asc" ? " ↑" : " ↓") : "";
  const ariaSortValue = active ? (direction === "asc" ? "ascending" : "descending") : undefined;

  // Sort button or plain label
  const sortElement = hasSortProps ? (
    <button
      type="button"
      className={clsx(styles.sortHeader, active && styles.active)}
      data-testid="sort-header-btn"
      aria-label={ariaLabel ? `Sort by ${ariaLabel}` : undefined}
      onClick={sortClickHandler}
    >
      {children}
      <span aria-hidden="true">{arrow}</span>
    </button>
  ) : hasFilter ? (
    // filter-only: plain label span (no sort button)
    <span>{children}</span>
  ) : null;

  // Plain label (neither sort nor filter)
  if (!hasSortProps && !hasFilter) {
    return (
      <th scope="col" className={className} aria-label={ariaLabel} data-testid={testId}>
        <span>{children}</span>
      </th>
    );
  }

  return (
    <th
      scope="col"
      className={className}
      aria-sort={hasSortProps ? ariaSortValue : undefined}
      aria-label={ariaLabel}
      data-testid={testId}
    >
      {hasFilter ? (
        <div className={styles.headerInner}>
          {sortElement}
          <button
            ref={filterTriggerRef}
            type="button"
            className={clsx(styles.filterBtn, props.hasActiveFilter && styles.filterActive)}
            data-testid="filter-btn"
            aria-label={ariaLabel ? `Filter ${ariaLabel}` : undefined}
            onClick={() => {
              setFilterOpen((v) => !v);
            }}
          >
            <FilterIcon active={props.hasActiveFilter} />
          </button>
          <ColumnFilterPopover
            open={filterOpen}
            onClose={() => {
              setFilterOpen(false);
            }}
            triggerRef={filterTriggerRef}
          >
            {props.filterContent}
          </ColumnFilterPopover>
        </div>
      ) : (
        sortElement
      )}
    </th>
  );
}
