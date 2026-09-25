import type { LogEntry } from "@/api/endpoints";

import type { SortState } from "../sort-header";

export type ColumnId = "level" | "timestamp" | "app" | "instance" | "execution" | "function" | "module" | "message";

export type LogSortKey = "timestamp" | "level" | "app" | "function" | "message";

export type LogSortState = SortState<LogSortKey>;

export type LevelFilter = "" | "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export type TierFilter = "all" | "app" | "framework";

export interface FilterState {
  level: LevelFilter;
  tier: TierFilter;
  app: string;
  search: string;
  func: string;
  sort: LogSortState;
}

export type ViewContext = "global" | "app" | "execution";

// Static per-column metadata, distinct from TanStack's `ColumnDef`. log-table-view.tsx builds the
// TanStack definitions from this; column-picker.tsx and use-column-visibility.ts consume it as-is.
export interface LogColumnMeta {
  id: ColumnId;
  label: string;
  shortLabel?: string;
  sortKey?: LogSortKey;
  width: string;
  mobileWidth: string;
  ariaLabel: string;
}

export type RowKey = string;

/** The subset of `LogEntry` fields `rowKey` actually reads, so callers (and test fixtures) don't
 * need a full `LogEntry` — just these four. */
export type RowKeyInput = Pick<LogEntry, "timestamp" | "logger_name" | "lineno"> & {
  seq?: LogEntry["seq"] | null;
};

export function rowKey(entry: RowKeyInput): RowKey {
  // `seq` is optional here even though the API type marks it required — guard the absent case.
  if (entry.seq === null || entry.seq === undefined) {
    return `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
  }

  // The stamped counter starts at 1, so `seq: 0` marks a record that bypassed CorrelationFilter and
  // can repeat across concurrent records — discriminate on logger/lineno.
  if (entry.seq === 0) {
    return `${entry.timestamp}-0-${entry.logger_name}-${entry.lineno}`;
  }

  return `${entry.timestamp}-${entry.seq}`;
}
