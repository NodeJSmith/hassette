import type { LogEntry } from "../../../api/endpoints";

export type ColumnId = "level" | "timestamp" | "app" | "instance" | "execution" | "function" | "module" | "message";

export type SortColumn = "timestamp" | "level" | "app" | "function" | "message";

export interface SortConfig {
  column: SortColumn;
  asc: boolean;
}

export type LevelFilter = "" | "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export type TierFilter = "all" | "app" | "framework";

export interface FilterState {
  level: LevelFilter;
  tier: TierFilter;
  app: string;
  search: string;
  func: string;
  sort: SortConfig;
}

export type ViewContext = "global" | "app" | "execution";

export interface ColumnDef {
  id: ColumnId;
  label: string;
  shortLabel?: string;
  sortKey?: SortColumn;
  filterable: boolean;
  width: string;
  mobileWidth: string;
  mono: boolean;
  ariaLabel: string;
}

export type RowKey = string;

export function rowKey(entry: LogEntry): RowKey {
  return entry.seq ? `${entry.timestamp}-${entry.seq}` : `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
}
