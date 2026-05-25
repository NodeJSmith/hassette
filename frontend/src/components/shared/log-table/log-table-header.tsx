import { BREAKPOINT_MOBILE, useMediaQuery } from "../../../hooks/use-media-query";
import { SortHeader } from "../sort-header";
import type { ColumnFilters } from "../table-types";
import { COLUMN_MAP } from "./constants";
import styles from "./log-table-header.module.css";
import type { ColumnId, LogSortState } from "./types";

interface Props {
  visibleColumns: ColumnId[];
  sort: LogSortState;
  onSort: (sort: LogSortState) => void;
  columnFilters: ColumnFilters;
}

export function LogTableHeader({ visibleColumns, sort, onSort, columnFilters }: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  const handleSort = (next: LogSortState) => {
    if (next.key === "timestamp" && sort.key !== "timestamp") {
      onSort({ key: "timestamp", dir: "desc" });
      return;
    }
    onSort(next);
  };

  return (
    <thead class={styles.thead}>
      <tr>
        {visibleColumns.map((id) => {
          const col = COLUMN_MAP[id];
          const displayLabel = isMobile && col.shortLabel ? col.shortLabel : col.label;
          const filter = columnFilters[id];

          const sortProps = col.sortKey ? { sortKey: col.sortKey, sort, onSort: handleSort } : {};
          const filterProps = filter ? { filterContent: filter.content, hasActiveFilter: filter.active } : {};

          const testId = col.sortKey ? `sort-${col.sortKey}` : filter ? `filter-${id}-col` : `col-${id}`;

          return (
            <SortHeader key={id} {...sortProps} {...filterProps} ariaLabel={col.ariaLabel} data-testid={testId}>
              {displayLabel}
            </SortHeader>
          );
        })}
      </tr>
    </thead>
  );
}
