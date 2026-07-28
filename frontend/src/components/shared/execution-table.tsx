import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useState } from "react";
import { useLocation } from "wouter";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { useRovingTabIndex } from "../../hooks/use-roving-tab-index";
import { executionPath, type HandlerKind } from "../../utils/app-routes";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatRelativeTime, formatTimestamp } from "../../utils/format";
import { onActivateKeyDown } from "../../utils/keyboard";
import { executionStatusKind, type StatusKind } from "../../utils/status";
import { EmptyState } from "./empty-state";
import styles from "./execution-table.module.css";
import { IconArrowRight } from "./icons";
import { ShowMoreButton } from "./show-more-button";
import { StatusShape } from "./status-shape";

// cellClassName/cellProps are declared once, shared with log-table-view.tsx,
// in table-types.ts. This file only adds the field unique to execution tables.
declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- must match TanStack's ColumnMeta<TData, TValue> signature exactly for declaration merging
  interface ColumnMeta<TData, TValue> {
    headerClassName?: string;
  }
}

const INITIAL_ROWS = 5;

const STATUS_LABEL: Record<StatusKind, string> = {
  ok: "ok",
  err: "failed",
  warn: "timed out",
  cancel: "cancelled",
  mute: "skipped",
};

export interface ExecutionRecord {
  execution_start_ts: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  error_message: string | null;
  error_traceback?: string | null;
  execution_id?: string | null;
  trigger_context_id?: string | null;
  trigger_origin?: string | null;
  trigger_mode?: string | null;
  thread_leaked: boolean;
}

interface ExecutionTableProps {
  records: ExecutionRecord[];
  kind: "handler" | "job";
  tableId: string;
  appKey?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  instanceQs?: string;
}

function statusLabelClass(kind: StatusKind): string {
  switch (kind) {
    case "ok":
      return styles.okLabel;
    case "err":
      return styles.failedLabel;
    case "warn":
      return styles.timeoutLabel;
    case "cancel":
      return styles.cancelledLabel;
    case "mute":
      return styles.statusLabel;
  }
}

// Static — no sorting/filtering/visibility, so no closures over component
// state are needed (unlike log-table-view.tsx's columns, which are rebuilt
// per render to close over sort/filter/mobile state).
const columns: ColumnDef<ExecutionRecord, unknown>[] = [
  {
    id: "status",
    header: "Status",
    meta: { headerClassName: styles.statusColumn, cellClassName: styles.statusColumn },
    cell: ({ row }) => {
      const record = row.original;
      const statusKind = executionStatusKind(record.status);
      return (
        <div className={styles.statusCellInner}>
          <StatusShape kind={statusKind} size={STATUS_DOT_SIZE} />
          <span className={statusLabelClass(statusKind)}>{STATUS_LABEL[statusKind]}</span>
          {record.thread_leaked && (
            <Badge variant="warning" size="sm" aria-label="thread leaked past timeout">
              thread leaked
            </Badge>
          )}
          {record.trigger_mode === "manual" && (
            <Badge variant="info" size="sm" aria-label="manually triggered">
              manual
            </Badge>
          )}
        </div>
      );
    },
  },
  {
    id: "execution",
    header: "Execution",
    meta: {
      headerClassName: styles.executionColumn,
      cellClassName: cn(styles.executionColumn, "ht-text-mono ht-text-xs"),
    },
    cell: ({ row }) => row.original.execution_id ?? "—",
  },
  {
    id: "duration",
    header: "Duration",
    meta: { headerClassName: styles.durationColumn, cellClassName: styles.durationColumn },
    cell: ({ row }) => formatDuration(row.original.duration_ms),
  },
  {
    id: "time",
    header: "Time",
    meta: {
      headerClassName: styles.timeColumn,
      cellClassName: cn(styles.timeColumn, "ht-text-mono ht-text-xs"),
      cellProps: (record: ExecutionRecord) => ({ title: formatTimestamp(record.execution_start_ts) }),
    },
    cell: ({ row }) => formatRelativeTime(row.original.execution_start_ts),
  },
  {
    id: "detail",
    header: () => <span className="ht-visually-hidden">Details</span>,
    meta: { headerClassName: styles.colArrow, cellClassName: cn("ht-text-muted", styles.arrowCell) },
    // No `cell` — the row render loop below special-cases `column.id === "detail"` and never calls
    // flexRender for it (it needs appKey/handlerKind/handlerId, not available at column-definition time).
  },
];

export function ExecutionTable({
  records,
  kind,
  tableId,
  appKey,
  handlerKind,
  handlerId,
  instanceQs,
}: ExecutionTableProps) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? records : records.slice(0, INITIAL_ROWS);
  const { containerRef, onContainerKeyDown, getTabIndex, setActiveIndex } = useRovingTabIndex<HTMLTableSectionElement>(
    visible.length,
  );
  const [, navigate] = useLocation();

  const table = useReactTable({
    data: visible,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (record, index) => record.execution_id ?? `${kind}-${index}`,
  });

  if (records.length === 0) {
    return kind === "handler" ? (
      <EmptyState
        icon="◌"
        title="no invocations recorded"
        body="this handler hasn't been called yet in the current time window."
      />
    ) : (
      <EmptyState title="no executions recorded." />
    );
  }

  const hasMore = records.length > INITIAL_ROWS;

  return (
    <>
      <Table className="ht-table ht-table--compact" data-testid={tableId}>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id} scope="col" className={header.column.columnDef.meta?.headerClassName}>
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody ref={containerRef} onKeyDown={onContainerKeyDown}>
          {table.getRowModel().rows.map((row, i) => {
            const record = row.original;
            const canNavigate = appKey && handlerKind && handlerId !== undefined && record.execution_id;
            const goToDetail = () => {
              if (canNavigate) {
                navigate(executionPath(appKey, handlerKind, handlerId, record.execution_id!) + (instanceQs ?? ""));
              }
            };

            return (
              <TableRow
                key={row.id}
                className={cn(styles.row, canNavigate && styles.rowClickable)}
                data-testid={kind === "handler" ? "invocation-row" : "execution-row"}
                tabIndex={getTabIndex(i)}
                role="row"
                aria-label={canNavigate ? "View execution detail" : undefined}
                data-roving-item
                onClick={() => {
                  setActiveIndex(i);
                  goToDetail();
                }}
                onKeyDown={canNavigate ? onActivateKeyDown(goToDetail) : undefined}
              >
                {row.getVisibleCells().map((cell) => {
                  if (cell.column.id === "detail") {
                    return (
                      <TableCell key={cell.id} className={cell.column.columnDef.meta?.cellClassName}>
                        {canNavigate && (
                          <span className={styles.arrowIndicator} data-testid="execution-detail-indicator">
                            <IconArrowRight />
                          </span>
                        )}
                      </TableCell>
                    );
                  }
                  const cellProps = cell.column.columnDef.meta?.cellProps?.(record) ?? {};
                  return (
                    <TableCell key={cell.id} className={cell.column.columnDef.meta?.cellClassName} {...cellProps}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  );
                })}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {hasMore && (
        <ShowMoreButton showAll={showAll} onToggle={() => setShowAll((v) => !v)} totalCount={records.length} />
      )}
    </>
  );
}
