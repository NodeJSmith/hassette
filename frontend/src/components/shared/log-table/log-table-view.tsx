import { type ColumnDef, flexRender, getCoreRowModel, type SortingState, useReactTable } from "@tanstack/react-table";
import clsx from "clsx";
import { type ReactNode, useMemo } from "react";

import type { LogEntry } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useRelativeTime } from "@/hooks/use-relative-time";
import { useRovingTabIndex } from "@/hooks/use-roving-tab-index";
import { formatTimestamp, truncateId } from "@/utils/format";

import { AppLink } from "../app-link";
import { IconChevron } from "../icons";
import { ARIA_SORT_FOR_DIRECTION, SortHeader } from "../sort-header";
import { COLUMN_MAP, DEFAULT_SORT, DETAIL_DRAWER_ID, LEVEL_ABBREV, levelClass } from "./constants";
import { ExecutionIdLink } from "./execution-id-link";
import styles from "./log-table-view.module.css";
import type { ColumnId, LogSortState } from "./types";
import { rowKey } from "./types";
import type { LogTableViewProps } from "./use-log-table";

// cellClassName/cellProps are declared once, shared with execution-table.tsx,
// in table-types.ts. This file only adds the field unique to log tables.
declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- must match TanStack's ColumnMeta<TData, TValue> signature exactly for declaration merging
  interface ColumnMeta<TData, TValue> {
    ariaLabel?: string;
  }
}

function TimestampCell({ entry, isMobile }: { entry: LogEntry; isMobile: boolean }) {
  // useRelativeTime is a hook, so this content must be a real component
  // instantiated via JSX (<TimestampCell />) rather than called as a plain
  // function inside the cell-rendering loop — calling hooks from a bare
  // function invoked once per row would violate the rules of hooks.
  const relativeTime = useRelativeTime(entry.timestamp);
  return <>{isMobile ? relativeTime : formatTimestamp(entry.timestamp)}</>;
}

function cellClassNameFor(id: ColumnId): string | undefined {
  switch (id) {
    case "level":
      return styles.levelCell;
    case "timestamp":
    case "instance":
    case "execution":
    case "function":
    case "module":
      return styles.mono;
    case "message":
      return styles.messageCell;
    case "app":
      return undefined;
  }
}

function renderCell(id: ColumnId, entry: LogEntry, isMobile: boolean, visibleColumns: ColumnId[]): ReactNode {
  switch (id) {
    case "level":
      return (
        <span className={clsx(styles.levelText, levelClass(styles, "level", entry.level))}>
          {isMobile ? (LEVEL_ABBREV[entry.level] ?? entry.level) : entry.level}
        </span>
      );
    case "timestamp":
      return <TimestampCell entry={entry} isMobile={isMobile} />;
    case "app":
      return entry.app_key ? <AppLink appKey={entry.app_key} /> : <span className={styles.muted}>&mdash;</span>;
    case "instance":
      return entry.instance_name ?? <span className={styles.muted}>&mdash;</span>;
    case "execution":
      return (
        <ExecutionIdLink
          entry={entry}
          linkClassName={styles.execLink}
          mutedClassName={styles.muted}
          title={entry.execution_id ?? undefined}
        >
          {truncateId(entry.execution_id)}
        </ExecutionIdLink>
      );
    case "function":
      return <span className={styles.truncate}>{entry.func_name}()</span>;
    case "module":
      return (
        <span className={styles.truncate} title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
          {entry.logger_name.split(".").pop()}:{entry.lineno}
        </span>
      );
    case "message": {
      const showSourceInline = isMobile && !visibleColumns.includes("app") && entry.func_name;
      return (
        <>
          {showSourceInline && (
            <div className={styles.sourceInline}>
              {entry.app_key ? `${entry.app_key}.` : ""}
              {entry.func_name}()
            </div>
          )}
          <div className={styles.messageText}>{entry.message}</div>
        </>
      );
    }
  }
}

interface BuildColumnsParams {
  sort: LogSortState;
  onSort: (sort: LogSortState) => void;
  isMobile: boolean;
  columnFilters: LogTableViewProps["columnFilters"];
  visibleColumns: ColumnId[];
}

// Convert the static per-column metadata in constants.ts (COLUMNS) into
// TanStack ColumnDef<LogEntry> declarations — the equivalent declarative
// shape for what used to be per-column JSX branches in log-table-row.tsx /
// log-table-header.tsx. Memoized by the caller (LogTableView) since this
// re-renders on the live-log poll interval.
function buildDataColumns({
  sort,
  onSort,
  isMobile,
  columnFilters,
  visibleColumns,
}: BuildColumnsParams): ColumnDef<LogEntry, unknown>[] {
  const handleSort = (next: LogSortState) => {
    if (next.key === DEFAULT_SORT.key && sort.key !== DEFAULT_SORT.key) {
      onSort(DEFAULT_SORT);
      return;
    }
    onSort(next);
  };

  return visibleColumns.map((id): ColumnDef<LogEntry, unknown> => {
    const col = COLUMN_MAP[id];
    const displayLabel = isMobile && col.shortLabel ? col.shortLabel : col.label;
    const filter = columnFilters[id];
    const sortProps = col.sortKey ? { sortKey: col.sortKey, sort, onSort: handleSort } : {};
    const filterProps = filter ? { filterContent: filter.content, hasActiveFilter: filter.active } : {};

    let testId = `col-${id}`;
    if (col.sortKey) testId = `sort-${col.sortKey}`;
    else if (filter) testId = `filter-${id}-col`;

    return {
      id,
      // No accessorFn: nothing here reads cell.getValue()/row.getValue() — cells
      // render straight from row.original (see renderCell), and getIsSorted()
      // reads table.getState().sorting directly, not through the accessor.
      meta: {
        ariaLabel: col.ariaLabel,
        cellClassName: cellClassNameFor(id),
        cellProps:
          id === "instance"
            ? (entry: LogEntry) => ({ title: entry.instance_name ?? undefined })
            : id === "message"
              ? () => ({ "data-testid": "log-message-cell" })
              : undefined,
      },
      header: () => (
        <SortHeader {...sortProps} {...filterProps} ariaLabel={col.ariaLabel} data-testid={testId}>
          {displayLabel}
        </SortHeader>
      ),
      cell: ({ row }) => renderCell(id, row.original, isMobile, visibleColumns),
    };
  });
}

export function LogTableView({
  visibleColumns,
  sort,
  onSort,
  columnFilters,
  entries,
  selectedKey,
  onRowClick,
  isMobile,
}: LogTableViewProps) {
  const { containerRef, onContainerKeyDown, getTabIndex, setActiveIndex } = useRovingTabIndex<HTMLTableSectionElement>(
    entries.length,
  );

  const dataColumns = useMemo(
    () => buildDataColumns({ sort, onSort, isMobile, columnFilters, visibleColumns }),
    [sort, onSort, isMobile, columnFilters, visibleColumns],
  );

  const detailColumn: ColumnDef<LogEntry, unknown> = useMemo(
    () => ({
      id: "detail",
      meta: { ariaLabel: "Detail", cellClassName: styles.detailCell },
      header: () => null,
      cell: ({ row }) => {
        const isSelected = selectedKey === row.id;
        return (
          <Button
            variant="ghost"
            size="icon-xs"
            className={styles.detailBtn}
            onClick={() => {
              setActiveIndex(row.index);
              onRowClick(row.original);
            }}
            tabIndex={getTabIndex(row.index)}
            data-roving-item
            aria-label="View log detail"
            aria-expanded={isSelected}
            aria-controls={DETAIL_DRAWER_ID}
          >
            <IconChevron open={isSelected} />
          </Button>
        );
      },
    }),
    [selectedKey, onRowClick, setActiveIndex, getTabIndex],
  );

  const columns: ColumnDef<LogEntry, unknown>[] = useMemo(
    () => [...dataColumns, detailColumn],
    [dataColumns, detailColumn],
  );

  // Display-only sorting state: bridges hassette's {key, dir} sort shape into
  // TanStack's {id, desc} shape so `column.getIsSorted()` can drive the
  // header's aria-sort/arrow indicator. We deliberately do NOT call
  // getSortedRowModel() or provide onSortingChange — the actual sort
  // comparator (sortEntries in use-log-filters.ts) already ran on `entries`
  // before they reached this component. Column visibility is also owned
  // externally (useColumnVisibility): `visibleColumns` above pre-filters
  // which columns get built at all, rather than using TanStack's
  // `state.columnVisibility` — viewport-forced hiding via REQUIRED_COLUMNS/
  // viewportHidden has no TanStack equivalent.
  const sorting: SortingState = [{ id: sort.key, desc: sort.dir === "desc" }];

  const table = useReactTable({
    data: entries,
    columns,
    state: { sorting },
    getRowId: (entry) => rowKey(entry),
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Table className="ht-table ht-table--fixed" data-testid="log-table">
      <colgroup>
        {visibleColumns.map((id) => {
          const col = COLUMN_MAP[id];
          const w = isMobile ? col.mobileWidth : col.width;
          return <col key={id} style={w ? { width: w } : undefined} />;
        })}
        <col className={styles.detailCol} />
      </colgroup>
      <TableHeader>
        {table.getHeaderGroups().map((headerGroup) => (
          <TableRow key={headerGroup.id}>
            {headerGroup.headers.map((header) => {
              const sortDirection = header.column.getIsSorted();
              return (
                <TableHead
                  key={header.id}
                  scope="col"
                  aria-sort={sortDirection ? ARIA_SORT_FOR_DIRECTION[sortDirection] : undefined}
                  aria-label={header.column.columnDef.meta?.ariaLabel}
                >
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              );
            })}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody ref={containerRef} onKeyDown={onContainerKeyDown}>
        {table.getRowModel().rows.map((row) => {
          const entry = row.original;
          const isSelected = selectedKey === row.id;
          return (
            <TableRow
              key={row.id}
              className={clsx(styles.row, isSelected && styles.selected)}
              data-level={entry.level}
              aria-current={isSelected ? "true" : undefined}
              onClick={(e) => {
                if (e.target instanceof Element && e.target.closest("a, button")) return;
                setActiveIndex(row.index);
                onRowClick(entry);
              }}
            >
              {row.getVisibleCells().map((cell) => {
                const meta = cell.column.columnDef.meta;
                const cellProps = meta?.cellProps?.(entry) ?? {};
                return (
                  <TableCell key={cell.id} className={meta?.cellClassName} {...cellProps}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                );
              })}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
