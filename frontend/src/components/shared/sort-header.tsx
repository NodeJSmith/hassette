import clsx from "clsx";
import type { ComponentChildren } from "preact";
import { useRef } from "preact/hooks";

import { useSignal } from "../../hooks/use-signal";
import { useSubscribe } from "../../hooks/use-subscribe";
import { ColumnFilterPopover } from "./column-filter-popover/index";
import { FilterIcon } from "./filter-icon";
import styles from "./sort-header.module.css";

export interface SortState<K extends string = string> {
  key: K;
  dir: "asc" | "desc";
}

interface BaseProps {
  ariaLabel?: string;
  class?: string;
  "data-testid"?: string;
  children: ComponentChildren;
}

interface ManualProps extends BaseProps {
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
  sortKey?: never;
  sort?: never;
  onSort?: never;
}

interface ManagedProps<K extends string> extends BaseProps {
  sortKey: K;
  sort: SortState<K>;
  onSort: (s: SortState<K>) => void;
  active?: never;
  direction?: never;
  onClick?: never;
}

// Neither-sort variant: no sort props at all
interface NoSortProps extends BaseProps {
  sortKey?: never;
  sort?: never;
  onSort?: never;
  active?: never;
  direction?: never;
  onClick?: never;
}

type SortProps<K extends string = string> = ManualProps | ManagedProps<K> | NoSortProps;

// Filter axis — orthogonal, optional, independent of sort
interface WithFilter {
  filterContent: ComponentChildren;
  hasActiveFilter: boolean;
}

interface WithoutFilter {
  filterContent?: never;
  hasActiveFilter?: never;
}

type FilterProps = WithFilter | WithoutFilter;

type Props<K extends string = string> = SortProps<K> & FilterProps;

export function SortHeader<K extends string = string>(props: Props<K>) {
  const { ariaLabel, class: className, "data-testid": testId, children } = props;

  // Filter state — local per-instance
  const filterOpen = useSignal(false);
  useSubscribe(filterOpen);
  const filterTriggerRef = useRef<HTMLButtonElement>(null);

  // Determine sort axis
  const hasSortKey = "sortKey" in props && props.sortKey !== undefined;
  const hasManualSort = !hasSortKey && "onClick" in props && (props as ManualProps).onClick !== undefined;

  let active = false;
  let direction: "asc" | "desc" = "asc";
  let sortClickHandler: (() => void) | undefined;

  if (hasSortKey) {
    const managed = props as ManagedProps<K>;
    active = managed.sort.key === managed.sortKey;
    direction = active ? managed.sort.dir : "asc";
    const key = managed.sortKey;
    const onSort = managed.onSort;
    sortClickHandler = () => onSort({ key, dir: active && managed.sort.dir === "asc" ? "desc" : "asc" });
  } else if (hasManualSort) {
    const manual = props as ManualProps;
    active = manual.active;
    direction = manual.direction;
    sortClickHandler = manual.onClick;
  }

  const hasSortProps = hasSortKey || hasManualSort;
  const hasFilter = props.filterContent !== undefined && props.filterContent !== null;

  const arrow = active ? (direction === "asc" ? " ↑" : " ↓") : "";
  const ariaSortValue = active ? (direction === "asc" ? "ascending" : "descending") : undefined;

  // Sort button or plain label
  const sortElement = hasSortProps ? (
    <button
      type="button"
      class={clsx(styles.sortHeader, active && styles.active)}
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
      <th scope="col" class={className} aria-label={ariaLabel} data-testid={testId}>
        <span>{children}</span>
      </th>
    );
  }

  return (
    <th
      scope="col"
      class={className}
      aria-sort={hasSortProps ? ariaSortValue : undefined}
      aria-label={ariaLabel}
      data-testid={testId}
    >
      {hasFilter ? (
        <div class={styles.headerInner}>
          {sortElement}
          <button
            ref={filterTriggerRef}
            type="button"
            class={clsx(styles.filterBtn, props.hasActiveFilter && styles.filterActive)}
            data-testid="filter-btn"
            aria-label={ariaLabel ? `Filter ${ariaLabel}` : undefined}
            onClick={() => {
              filterOpen.value = !filterOpen.value;
            }}
          >
            <FilterIcon active={props.hasActiveFilter} />
          </button>
          <ColumnFilterPopover
            open={filterOpen.value}
            onClose={() => {
              filterOpen.value = false;
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
