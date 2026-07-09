import type { LogEntry } from "../../../api/endpoints";
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

export interface ColumnDef {
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
  return entry.seq ? `${entry.timestamp}-${entry.seq}` : `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
}
