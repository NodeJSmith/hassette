import {
  type Cell,
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type Row,
  type Table as TanStackTable,
  useReactTable,
} from "@tanstack/react-table";
import { useState } from "react";
import { useLocation } from "wouter";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import type { components } from "../../api/generated-types";
import { useRovingTabIndex } from "../../hooks/use-roving-tab-index";
import { executionPath, type HandlerKind } from "../../utils/app-routes";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatRelativeTime, formatTimestamp } from "../../utils/format";
import { onActivateKeyDown } from "../../utils/keyboard";
import { executionStatusKind, type StatusKind } from "../../utils/status";
import { EmptyState } from "./empty-state";
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

type ExecutionStatus = components["schemas"]["ExecutionStatus"];

const INITIAL_ROWS = 5;

const HEAD_CLASS =
  "sticky top-0 z-[var(--z-table-head)] bg-muted px-2 py-1 font-mono text-xs font-medium uppercase tracking-[var(--text-label-tracking)] text-muted-foreground";

const CELL_CLASS = "px-2 py-1 max-mobile:px-1 max-mobile:text-xs";

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
  status: ExecutionStatus;
  error_type: string | null;
  error_message: string | null;
  error_traceback?: string | null;
  execution_id?: string | null;
  trigger_context_id?: string | null;
  trigger_origin?: string | null;
  trigger_mode?: string | null;
  thread_leaked: boolean;
}

function statusLabelClass(kind: StatusKind): string {
  switch (kind) {
    case "ok":
      return "font-mono text-xs whitespace-nowrap text-[var(--status-success)]";
    case "err":
      return "truncate font-mono text-xs whitespace-nowrap text-destructive";
    case "warn":
      return "font-mono text-xs whitespace-nowrap text-[var(--status-warning)]";
    case "cancel":
      return "font-mono text-xs whitespace-nowrap text-[var(--status-cancel)]";
    case "mute":
      return "font-mono text-xs whitespace-nowrap";
  }
}

// Static — no sorting/filtering/visibility, so no closures over component
// state are needed (unlike log-table-view.tsx's columns, which are rebuilt
// per render to close over sort/filter/mobile state).
const columns: ColumnDef<ExecutionRecord, unknown>[] = [
  {
    id: "status",
    header: "Status",
    meta: { headerClassName: "w-[18%] max-mobile:w-auto", cellClassName: "w-[18%] max-mobile:w-auto" },
    cell: ({ row }) => {
      const record = row.original;
      const statusKind = executionStatusKind(record.status);
      return (
        <div className="flex items-center gap-2">
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
      headerClassName: "[overflow-wrap:anywhere] max-mobile:hidden",
      cellClassName: cn("font-mono text-xs [overflow-wrap:anywhere] max-mobile:hidden"),
    },
    cell: ({ row }) => row.original.execution_id ?? "—",
  },
  {
    id: "duration",
    header: "Duration",
    meta: {
      headerClassName: "w-[14%] max-mobile:w-auto",
      cellClassName: "w-[14%] whitespace-nowrap max-mobile:w-auto",
    },
    cell: ({ row }) => formatDuration(row.original.duration_ms),
  },
  {
    id: "time",
    header: "Time",
    meta: {
      headerClassName: "w-[18%] max-mobile:w-auto",
      cellClassName: cn("w-[18%] font-mono text-xs whitespace-nowrap max-mobile:w-auto"),
      cellProps: (record: ExecutionRecord) => ({ title: formatTimestamp(record.execution_start_ts) }),
    },
    cell: ({ row }) => formatRelativeTime(row.original.execution_start_ts),
  },
  {
    id: "detail",
    header: () => <span className="sr-only">Details</span>,
    meta: { headerClassName: "w-8", cellClassName: "text-center align-middle text-muted-foreground transition-colors" },
    // No `cell` — `ExecutionCell` below special-cases `column.id === "detail"` and never calls
    // flexRender for it (it needs the row's resolved href, not available at column-definition time).
  },
];

export type ExecutionKind = "handler" | "job";

interface ExecutionTableProps {
  records: ExecutionRecord[];
  kind: ExecutionKind;
  tableId: string;
  appKey?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  instanceQs?: string;
}

type DetailTarget = Pick<ExecutionTableProps, "appKey" | "handlerKind" | "handlerId" | "instanceQs">;

// A row links to its execution detail page only when every part of the route is known.
// Returns null when it isn't — which also drives the row's hover/keyboard affordances.
function detailHref(record: ExecutionRecord, target: DetailTarget): string | null {
  const { appKey, handlerKind, handlerId, instanceQs } = target;
  if (!appKey || !handlerKind || handlerId === undefined || !record.execution_id) {
    return null;
  }
  return executionPath(appKey, handlerKind, handlerId, record.execution_id) + (instanceQs ?? "");
}

function ExecutionEmptyState({ kind }: { kind: ExecutionKind }) {
  if (kind === "handler") {
    return (
      <EmptyState
        icon="◌"
        title="no invocations recorded"
        body="this handler hasn't been called yet in the current time window."
      />
    );
  }
  return <EmptyState title="no executions recorded." />;
}

function ExecutionTableHead({ table }: { table: TanStackTable<ExecutionRecord> }) {
  return (
    <TableHeader className="[&_tr]:bg-muted">
      {table.getHeaderGroups().map((headerGroup) => (
        <TableRow key={headerGroup.id}>
          {headerGroup.headers.map((header) => (
            <TableHead
              key={header.id}
              scope="col"
              className={cn(HEAD_CLASS, header.column.columnDef.meta?.headerClassName)}
            >
              {flexRender(header.column.columnDef.header, header.getContext())}
            </TableHead>
          ))}
        </TableRow>
      ))}
    </TableHeader>
  );
}

// The "detail" column has no `cell` definition — it needs the row's resolved href, which
// isn't available at column-definition time — so it is rendered here instead of via flexRender.
function ExecutionCell({ cell, href }: { cell: Cell<ExecutionRecord, unknown>; href: string | null }) {
  const className = cn(CELL_CLASS, cell.column.columnDef.meta?.cellClassName);

  if (cell.column.id === "detail") {
    return (
      <TableCell className={className}>
        {href && (
          <span
            className="inline-flex items-center justify-center align-middle"
            data-testid="execution-detail-indicator"
          >
            <IconArrowRight />
          </span>
        )}
      </TableCell>
    );
  }

  const cellProps = cell.column.columnDef.meta?.cellProps?.(cell.row.original) ?? {};
  return (
    <TableCell className={className} {...cellProps}>
      {flexRender(cell.column.columnDef.cell, cell.getContext())}
    </TableCell>
  );
}

interface ExecutionRowProps {
  row: Row<ExecutionRecord>;
  kind: ExecutionKind;
  href: string | null;
  tabIndex: number;
  onSelect: () => void;
  onOpenDetail: () => void;
}

function ExecutionRow({ row, kind, href, tabIndex, onSelect, onOpenDetail }: ExecutionRowProps) {
  return (
    <TableRow
      className={cn("transition-colors", href && "cursor-pointer hover:bg-muted [&:hover_td:last-child]:text-primary")}
      data-testid={kind === "handler" ? "invocation-row" : "execution-row"}
      tabIndex={tabIndex}
      role="row"
      aria-label={href ? "View execution detail" : undefined}
      data-roving-item
      onClick={() => {
        onSelect();
        onOpenDetail();
      }}
      onKeyDown={href ? onActivateKeyDown(onOpenDetail) : undefined}
    >
      {row.getVisibleCells().map((cell) => (
        <ExecutionCell key={cell.id} cell={cell} href={href} />
      ))}
    </TableRow>
  );
}

interface ExecutionRowsProps extends DetailTarget {
  table: TanStackTable<ExecutionRecord>;
  kind: ExecutionKind;
}

// Owns the roving-tabindex wiring: the table body is the roving container, each row an item.
function ExecutionRows({ table, kind, ...target }: ExecutionRowsProps) {
  const rows = table.getRowModel().rows;
  const { containerRef, onContainerKeyDown, getTabIndex, setActiveIndex } = useRovingTabIndex<HTMLTableSectionElement>(
    rows.length,
  );
  const [, navigate] = useLocation();

  return (
    <TableBody ref={containerRef} onKeyDown={onContainerKeyDown}>
      {rows.map((row, i) => {
        const href = detailHref(row.original, target);
        return (
          <ExecutionRow
            key={row.id}
            row={row}
            kind={kind}
            href={href}
            tabIndex={getTabIndex(i)}
            onSelect={() => setActiveIndex(i)}
            onOpenDetail={() => {
              if (href) {
                navigate(href);
              }
            }}
          />
        );
      })}
    </TableBody>
  );
}

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

  const table = useReactTable({
    data: visible,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (record, index) => record.execution_id ?? `${kind}-${index}`,
  });

  if (records.length === 0) {
    return <ExecutionEmptyState kind={kind} />;
  }

  return (
    <>
      <Table
        className="table-fixed bg-card max-mobile:table-auto [&_td]:overflow-hidden [&_td]:text-ellipsis"
        data-testid={tableId}
      >
        <ExecutionTableHead table={table} />
        <ExecutionRows
          table={table}
          kind={kind}
          appKey={appKey}
          handlerKind={handlerKind}
          handlerId={handlerId}
          instanceQs={instanceQs}
        />
      </Table>
      {records.length > INITIAL_ROWS && (
        <ShowMoreButton showAll={showAll} onToggle={() => setShowAll((v) => !v)} totalCount={records.length} />
      )}
    </>
  );
}
