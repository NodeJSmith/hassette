import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { LogEntry } from "../../api/endpoints";
import { getRecentLogs } from "../../api/endpoints";
import { useAppState } from "../../state/context";
import { formatTimestamp, pluralize } from "../../utils/format";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

export type SortColumn = "timestamp" | "level" | "app" | "message";

export const LEVEL_INDEX: Record<string, number> = {
  DEBUG: 0,
  INFO: 1,
  WARNING: 2,
  ERROR: 3,
  CRITICAL: 4,
};

interface SortConfig {
  column: SortColumn;
  asc: boolean;
}

/** Sort log entries by the given column and direction. Returns a new array. */
export function sortEntries(entries: readonly LogEntry[], column: SortColumn, asc: boolean): LogEntry[] {
  const direction = asc ? 1 : -1;

  return [...entries].sort((a, b) => {
    switch (column) {
      case "timestamp":
        return (a.timestamp - b.timestamp) * direction;
      case "level":
        return ((LEVEL_INDEX[a.level] ?? -1) - (LEVEL_INDEX[b.level] ?? -1)) * direction;
      case "app": {
        const aKey = a.app_key ?? "\uffff";
        const bKey = b.app_key ?? "\uffff";
        return aKey.localeCompare(bKey) * direction;
      }
      case "message":
        return a.message.localeCompare(b.message) * direction;
    }
  });
}

interface Props {
  showAppColumn?: boolean;
  appKey?: string;
  /** List of app keys for the app filter dropdown (global logs page) */
  appKeys?: string[];
}

export function LogTable({ showAppColumn = true, appKey, appKeys }: Props) {
  const { logs, updateLogSubscription, reconnectVersion } = useAppState();
  const minLevel = useRef(signal("INFO")).current; // default = INFO (matches WS subscription)
  const appFilter = useRef(signal("")).current; // "" = All Apps
  const search = useRef(signal("")).current;
  const initialEntries = useRef(signal<LogEntry[]>([])).current;
  const sortConfig = useRef(signal<SortConfig>({ column: "timestamp", asc: false })).current;
  const expandedRows = useRef(signal<Set<string>>(new Set())).current;

  const watermarkRef = useRef(0);

  // Fetch initial entries on mount and after reconnect
  const rv = reconnectVersion.value;
  useEffect(() => {
    watermarkRef.current = 0;
    getRecentLogs({ app_key: appKey, limit: 200 })
      .then((entries) => {
        initialEntries.value = entries;
        watermarkRef.current = entries.reduce((max, e) => Math.max(max, e.seq), 0);
      })
      .catch(() => { /* API error — initial entries stay empty, WS will still stream */ });
  }, [appKey, rv]);

  // Read version to subscribe to WS updates
  void logs.version.value;

  // Combine initial entries + ring buffer entries, deduplicating by seq watermark
  const wsEntries = logs.toArray().filter((e) => {
    if (e.seq <= watermarkRef.current) return false;
    if (appKey && e.app_key !== appKey) return false;
    return true;
  });

  // Live pause: when sorting by non-timestamp column, exclude WS entries
  const livePaused = sortConfig.value.column !== "timestamp";
  const allEntries = livePaused
    ? [...initialEntries.value]
    : [...initialEntries.value, ...wsEntries];

  // Apply level filter
  const levelFiltered = minLevel.value
    ? allEntries.filter((e) => {
        const levelIndex = LEVELS.indexOf(minLevel.value as (typeof LEVELS)[number]);
        const entryIndex = LEVELS.indexOf(e.level as (typeof LEVELS)[number]);
        return entryIndex >= levelIndex;
      })
    : allEntries; // "" = All Levels — show everything

  // Apply app filter (only for global logs)
  const appFiltered = appFilter.value
    ? levelFiltered.filter((e) => e.app_key === appFilter.value)
    : levelFiltered;

  // Apply search filter
  const filtered = search.value
    ? appFiltered.filter(
        (e) =>
          e.message.toLowerCase().includes(search.value.toLowerCase()) ||
          e.logger_name.toLowerCase().includes(search.value.toLowerCase()),
      )
    : appFiltered;

  // Sort
  const sorted = sortEntries(filtered, sortConfig.value.column, sortConfig.value.asc);

  const handleSort = (column: SortColumn) => {
    const current = sortConfig.value;
    if (current.column === column) {
      sortConfig.value = { column, asc: !current.asc };
    } else {
      sortConfig.value = { column, asc: false };
    }
  };

  const handleResume = () => {
    sortConfig.value = { column: "timestamp", asc: false };
  };

  const ariaSortFor = (column: SortColumn): "ascending" | "descending" | undefined =>
    sortConfig.value.column === column
      ? sortConfig.value.asc ? "ascending" : "descending"
      : undefined;

  const sortArrow = (column: SortColumn): string =>
    sortConfig.value.column === column
      ? sortConfig.value.asc ? "↑" : "↓"
      : "⇅";

  return (
    <div class="ht-log-table-container">
      <div class="ht-field-group">
        <div class="ht-select ht-select--sm">
          <select
            data-testid="filter-level"
            value={minLevel.value}
            onChange={(e) => {
              const newLevel = (e.target as HTMLSelectElement).value;
              minLevel.value = newLevel;
              // Update server-side filtering — "" (All Levels) maps to DEBUG
              updateLogSubscription(newLevel || "DEBUG");
            }}
          >
            <option value="">All Levels</option>
            {LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </div>
        {showAppColumn && appKeys && appKeys.length > 0 && (
          <div class="ht-select ht-select--sm">
            <select
              data-testid="filter-app"
              value={appFilter.value}
              onChange={(e) => {
                appFilter.value = (e.target as HTMLSelectElement).value;
              }}
            >
              <option value="">All Apps</option>
              {appKeys.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </div>
        )}
        <input
          class="ht-input ht-input--sm"
          type="text"
          placeholder="Search..."
          value={search.value}
          onInput={(e) => {
            search.value = (e.target as HTMLInputElement).value;
          }}
        />
        <span class="ht-text-secondary ht-text-xs">{pluralize(filtered.length, "entry", "entries")}</span>
        {livePaused && (
          <span class="ht-text-xs ht-text-warning">
            Live updates paused{" "}
            <button type="button" class="ht-btn ht-btn--xs ht-btn--ghost" onClick={handleResume}>
              Resume
            </button>
          </span>
        )}
      </div>
      <div class="ht-log-table-scroll" style={{ maxHeight: "600px", overflow: "auto" }}>
        <table class="ht-table ht-table--compact ht-table-log">
          <thead style={{ position: "sticky", top: 0, background: "var(--ht-surface-sticky, var(--ht-bg))" }}>
            <tr>
              <th style={{ width: "90px" }} aria-sort={ariaSortFor("level")} data-testid="sort-level">
                <button type="button" class="ht-sortable" onClick={() => handleSort("level")}>
                  <span>Level</span>{" "}<span aria-hidden="true">{sortArrow("level")}</span>
                </button>
              </th>
              <th style={{ width: "180px" }} aria-sort={ariaSortFor("timestamp")} data-testid="sort-timestamp">
                <button type="button" class="ht-sortable" onClick={() => handleSort("timestamp")}>
                  <span>Timestamp</span>{" "}<span aria-hidden="true">{sortArrow("timestamp")}</span>
                </button>
              </th>
              {showAppColumn && (
                <th style={{ width: "170px" }} aria-sort={ariaSortFor("app")} data-testid="sort-app">
                  <button type="button" class="ht-sortable" onClick={() => handleSort("app")}>
                    <span>App</span>{" "}<span aria-hidden="true">{sortArrow("app")}</span>
                  </button>
                </th>
              )}
              <th style={{ width: "140px" }} class="ht-col-source">Source</th>
              <th aria-sort={ariaSortFor("message")} data-testid="sort-message">
                <button type="button" class="ht-sortable" onClick={() => handleSort("message")}>
                  <span>Message</span>{" "}<span aria-hidden="true">{sortArrow("message")}</span>
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={showAppColumn ? 5 : 4} style={{ textAlign: "center" }} class="ht-text-muted">
                  No log entries.
                </td>
              </tr>
            )}
            {sorted.slice(0, 500).map((entry) => {
              const rowKey = entry.seq ? String(entry.seq) : `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
              return (
              <tr key={rowKey}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${entry.level === "ERROR" || entry.level === "CRITICAL" ? "danger" : entry.level === "WARNING" ? "warning" : entry.level === "DEBUG" ? "neutral" : "success"}`}>
                    {entry.level}
                  </span>
                </td>
                <td class="ht-text-mono">{formatTimestamp(entry.timestamp)}</td>
                {showAppColumn && (
                  <td>
                    {entry.app_key ? (
                      <a href={`/apps/${entry.app_key}`} class="ht-text-mono">
                        {entry.app_key}
                      </a>
                    ) : (
                      <span class="ht-text-muted">—</span>
                    )}
                  </td>
                )}
                <td class="ht-col-source ht-text-mono ht-text-xs ht-text-muted" title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
                  {entry.func_name}:{entry.lineno}
                </td>
                <td
                  class="ht-log-message"
                  role="button"
                  tabIndex={0}
                  aria-expanded={expandedRows.value.has(rowKey)}
                  onClick={() => {
                    const next = new Set(expandedRows.value);
                    if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                    expandedRows.value = next;
                  }}
                  onKeyDown={(e: KeyboardEvent) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      const next = new Set(expandedRows.value);
                      if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                      expandedRows.value = next;
                    }
                  }}
                >
                  <div class={`ht-log-message__text${expandedRows.value.has(rowKey) ? " is-expanded" : ""}`}>{entry.message}</div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
