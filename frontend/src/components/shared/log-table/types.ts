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

// Static per-column metadata (id, label, width, etc.). Renamed from the
// previous `ColumnDef` to avoid colliding with TanStack's own `ColumnDef`
// type, which log-table-view.tsx now imports directly to build the real
// TanStack column definitions. This metadata feeds that construction and is
// also consumed as-is by column-picker.tsx and use-column-visibility.ts,
// neither of which need TanStack types.
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

export function rowKey(entry: LogEntry): RowKey {
  // `seq` is always present (backend falls back to `seq: 0` for records that bypass
  // CorrelationFilter — early-startup and third-party logger records). Check for
  // presence with `!= null`, not truthiness, so a real `seq: 0` isn't mistaken for
  // an absent value and pushed onto the weaker fallback key.
  if (entry.seq === null || entry.seq === undefined) {
    return `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
  }

  // The stamped counter starts at 1, so `seq: 0` is the fallback marker and can repeat
  // across concurrent records — add the logger/lineno discriminator to avoid collisions
  // that a bare `${timestamp}-0` key would produce.
  if (entry.seq === 0) {
    return `${entry.timestamp}-0-${entry.logger_name}-${entry.lineno}`;
  }

  return `${entry.timestamp}-${entry.seq}`;
}
