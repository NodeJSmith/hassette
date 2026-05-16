import { useMediaQuery, BREAKPOINT_MOBILE } from "../../../hooks/use-media-query";
import type { ColumnId, SortColumn, SortConfig } from "./types";
import { COLUMN_MAP } from "./constants";
import { SortHeader } from "../sort-header";
import type { ColumnFilters } from "../table-types";
import styles from "./log-table-header.module.css";

interface Props {
  visibleColumns: ColumnId[];
  sortConfig: SortConfig;
  onSort: (col: SortColumn) => void;
  columnFilters: ColumnFilters;
}

export function LogTableHeader({
  visibleColumns, sortConfig, onSort, columnFilters,
}: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  return (
    <thead class={styles.thead}>
      <tr>
        {visibleColumns.map((id) => {
          const col = COLUMN_MAP[id];
          const displayLabel = isMobile && col.shortLabel ? col.shortLabel : col.label;
          const filter = columnFilters[id];

          // Build manual sort props for SortHeader (log table uses SortColumn/SortConfig)
          const isActive = col.sortKey ? sortConfig.column === col.sortKey : false;
          const direction = isActive ? (sortConfig.asc ? "asc" : "desc") : "asc";

          if (col.sortKey && filter) {
            return (
              <SortHeader key={id} active={isActive} direction={direction} onClick={() => onSort(col.sortKey!)}
                filterContent={filter.content} hasActiveFilter={filter.active}
                ariaLabel={col.ariaLabel} data-testid={`sort-${col.sortKey}`}
              >{displayLabel}</SortHeader>
            );
          }
          if (col.sortKey) {
            return (
              <SortHeader key={id} active={isActive} direction={direction} onClick={() => onSort(col.sortKey!)}
                ariaLabel={col.ariaLabel} data-testid={`sort-${col.sortKey}`}
              >{displayLabel}</SortHeader>
            );
          }
          if (filter) {
            return (
              <SortHeader key={id} filterContent={filter.content} hasActiveFilter={filter.active}
                ariaLabel={col.ariaLabel} data-testid={`filter-${id}-col`}
              >{displayLabel}</SortHeader>
            );
          }
          return (
            <SortHeader key={id} ariaLabel={col.ariaLabel}>{displayLabel}</SortHeader>
          );
        })}
      </tr>
    </thead>
  );
}
