import type { ColumnDef, ColumnId, LevelFilter, LogSortKey, LogSortState, TierFilter } from "./types";

export const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

export const DEFAULT_LEVEL: LevelFilter = "INFO";
// Empty string means "show all levels" in app code; serialized as "all" in URL params.
export const ALL_LEVELS: LevelFilter = "";

export const COPY_CONFIRM_MS = 1500;

export const DEFAULT_SORT: LogSortState = { key: "timestamp", dir: "desc" };

// Enforced in: use-column-visibility.ts readStored() (persistence) and column-picker.tsx (UI disabled state)
export const REQUIRED_COLUMNS: ReadonlySet<ColumnId> = new Set(["level", "message"]);

export const TIER_OPTIONS: readonly { value: TierFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "app", label: "Apps" },
  { value: "framework", label: "Framework" },
] as const;

export const LEVEL_INDEX: Record<string, number> = {
  DEBUG: 0,
  INFO: 1,
  WARNING: 2,
  ERROR: 3,
  CRITICAL: 4,
};

export const LEVEL_ABBREV: Record<string, string> = {
  DEBUG: "D",
  INFO: "I",
  WARNING: "W",
  ERROR: "E",
  CRITICAL: "C",
};

export const LEVEL_OPTIONS: { value: LevelFilter; label: string }[] = [
  { value: "", label: "All levels" },
  { value: "DEBUG", label: "DEBUG+" },
  { value: "INFO", label: "INFO+" },
  { value: "WARNING", label: "WARNING+" },
  { value: "ERROR", label: "ERROR+" },
  { value: "CRITICAL", label: "CRITICAL only" },
];

export const COLUMNS: ColumnDef[] = [
  {
    id: "level",
    label: "Level",
    shortLabel: "Lvl",
    sortKey: "level",
    width: "70px",
    mobileWidth: "32px",
    ariaLabel: "Log level",
  },
  {
    id: "timestamp",
    label: "Timestamp",
    shortLabel: "When",
    sortKey: "timestamp",
    width: "140px",
    mobileWidth: "72px",
    ariaLabel: "Timestamp",
  },
  {
    id: "app",
    label: "App",
    sortKey: "app",
    width: "130px",
    mobileWidth: "80px",
    ariaLabel: "Application",
  },
  {
    id: "instance",
    label: "Instance",
    width: "110px",
    mobileWidth: "80px",
    ariaLabel: "Instance name",
  },
  {
    id: "execution",
    label: "Execution",
    width: "90px",
    mobileWidth: "70px",
    ariaLabel: "Execution ID",
  },
  {
    id: "function",
    label: "Function",
    sortKey: "function",
    width: "150px",
    mobileWidth: "90px",
    ariaLabel: "Function name",
  },
  {
    id: "module",
    label: "Module",
    width: "120px",
    mobileWidth: "80px",
    ariaLabel: "Module and line",
  },
  {
    id: "message",
    label: "Message",
    sortKey: "message",
    width: "",
    mobileWidth: "",
    ariaLabel: "Log message",
  },
];

export const COLUMN_MAP: Record<ColumnId, ColumnDef> = Object.fromEntries(COLUMNS.map((c) => [c.id, c])) as Record<
  ColumnId,
  ColumnDef
>;

export const VALID_SORT_COLUMNS: ReadonlySet<string> = new Set<string>([
  "timestamp",
  "level",
  "app",
  "function",
  "message",
  "source", // deprecated alias → function (preserves bookmarked URLs)
]);

export function resolveSortKey(raw: string): LogSortKey {
  if (raw === "source") return "function";
  return VALID_SORT_COLUMNS.has(raw) ? (raw as LogSortKey) : "timestamp";
}

export const DEFAULT_COLUMNS_GLOBAL: ColumnId[] = [
  "level",
  "timestamp",
  "app",
  "execution",
  "function",
  "module",
  "message",
];
export const DEFAULT_COLUMNS_APP: ColumnId[] = ["level", "timestamp", "execution", "function", "module", "message"];
export const DEFAULT_COLUMNS_EXECUTION: ColumnId[] = ["level", "timestamp", "function", "module", "message"];

export function levelClass(styles: Record<string, string>, prefix: string, level: string): string | undefined {
  return styles[`${prefix}${level}`];
}

export const RENDER_CAP = 200;
export const SEARCH_DEBOUNCE_MS = 150;
export const REST_FETCH_LIMIT = 1000;
export const LIVE_LOG_UPDATE_INTERVAL_MS = 750;
