import { signal } from "@preact/signals";
import { useEffect, useRef, useCallback } from "preact/hooks";
import type { LogEntry } from "../../api/endpoints";
import { getRecentLogs } from "../../api/endpoints";
import { useMediaQuery, BREAKPOINT_MOBILE, BREAKPOINT_TABLET } from "../../hooks/use-media-query";
import { useAppState } from "../../state/context";
import { formatTimestamp, formatRelativeTime, pluralize } from "../../utils/format";

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
        const aKey = a.app_key;
        const bKey = b.app_key;
        const aMissing = aKey === null || aKey === undefined || aKey === "";
        const bMissing = bKey === null || bKey === undefined || bKey === "";
        if (aMissing && bMissing) return 0;
        if (aMissing) return 1;  // nulls always last
        if (bMissing) return -1; // nulls always last
        return aKey.localeCompare(bKey) * direction;
      }
      case "message":
        return a.message.localeCompare(b.message) * direction;
    }
  });
}

const LEVEL_ABBREV: Record<string, string> = {
  DEBUG: "D",
  INFO: "I",
  WARNING: "W",
  ERROR: "E",
  CRITICAL: "C",
};

interface Props {
  showAppColumn?: boolean;
  appKey?: string;
  /** List of app keys for the app filter dropdown (global logs page) */
  appKeys?: string[];
}

export function LogTable({ showAppColumn = true, appKey, appKeys }: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  // Source column is CSS-hidden at max-width: 1024px (see global.css .ht-table-log .ht-col-source)
  // Ideally the Source <th>/<td> would be conditionally rendered like the App column,
  // but for now we just adjust the colSpan to match the CSS-only hide.
  const isTablet = useMediaQuery(BREAKPOINT_TABLET);
  const showSourceColumn = !isTablet;
  const { logs, updateLogSubscription, reconnectVersion, tick } = useAppState();

  // Subscribe to tick signal so relative timestamps re-render every 30s on mobile
  if (isMobile) void tick.value;
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

  // Track which rows have truncated message text (scrollWidth > clientWidth).
  //
  // NOTE: Expanded rows have `text-overflow: ellipsis` removed by CSS (via the
  // `.is-expanded` class), so `scrollWidth === clientWidth` for them — they will
  // NOT appear in `truncatedRows`. The `|| isExpanded` guard in the render path
  // (`canExpand = truncatedRows.value.has(rowKey) || isExpanded`) is load-bearing:
  // it keeps expanded rows collapsible even when recheckTruncation() doesn't
  // include them. Do NOT remove that guard.
  const truncatedRows = useRef(signal(new Set<string>())).current;
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  /** Scan all `.ht-log-message__text` elements and update `truncatedRows` if the set changed. */
  const recheckTruncation = useCallback(() => {
    const container = tableContainerRef.current;
    if (!container) return;
    const elements = container.querySelectorAll<HTMLElement>(".ht-log-message__text");
    const nextTruncated = new Set<string>();
    elements.forEach((el) => {
      const key = el.getAttribute("data-row-key");
      if (key && el.scrollWidth > el.clientWidth) {
        nextTruncated.add(key);
      }
    });
    // Suppress signal update when the set is unchanged (avoids unnecessary re-renders).
    const current = truncatedRows.value;
    if (nextTruncated.size !== current.size || [...nextTruncated].some((k) => !current.has(k))) {
      truncatedRows.value = nextTruncated;
    }
  }, [truncatedRows]);

  // Trigger path A — Viewport resize: ResizeObserver on individual text elements.
  // Observe the table container element (not individual text elements or the
  // scroll container). The table container is in normal document flow and resizes
  // with the viewport. One observer target is cheaper than 500 per-element targets,
  // and table cells all share column widths so they resize together.
  useEffect(() => {
    const container = tableContainerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(() => {
      recheckTruncation();
    });
    resizeObserverRef.current = observer;
    observer.observe(container);
    // Font load detection — recheck after all fonts have loaded
    void document.fonts.ready.then(() => recheckTruncation());
    return () => {
      observer.disconnect();
      resizeObserverRef.current = null;
    };
  }, [recheckTruncation]);

  // Trigger path B — Data changes: recheck after render when visible entry count changes.
  // Uses requestAnimationFrame to ensure layout is complete before measuring.
  // No need to re-observe elements since Trigger A observes the container, not
  // individual elements.
  useEffect(() => {
    const rafId = requestAnimationFrame(() => {
      recheckTruncation();
    });
    return () => cancelAnimationFrame(rafId);
    // Key on count + first/last seq to detect row swaps at same count (filter/sort changes)
  }, [sorted.length, sorted[0]?.seq, sorted[sorted.length - 1]?.seq, recheckTruncation]);

  const ariaSortFor = (column: SortColumn): "ascending" | "descending" | undefined =>
    sortConfig.value.column === column
      ? sortConfig.value.asc ? "ascending" : "descending"
      : undefined;

  const sortArrow = (column: SortColumn): string =>
    sortConfig.value.column === column
      ? sortConfig.value.asc ? "↑" : "↓"
      : "⇅";

  return (
    <div class="ht-log-table-container" ref={tableContainerRef}>
      <div class="ht-field-group">
        <div class="ht-select ht-select--sm">
          <select
            aria-label="Minimum log level"
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
              aria-label="Filter by app"
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
          aria-label="Search log messages"
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
      <div class="ht-log-table-scroll">
        <table class="ht-table ht-table--compact ht-table-log">
          <thead>
            <tr>
              <th class="ht-col-level" aria-sort={ariaSortFor("level")} data-testid="sort-level">
                <button type="button" class="ht-sortable" onClick={() => handleSort("level")}>
                  <span>Level</span>{" "}<span aria-hidden="true">{sortArrow("level")}</span>
                </button>
              </th>
              <th class="ht-col-time" aria-sort={ariaSortFor("timestamp")} data-testid="sort-timestamp">
                <button type="button" class="ht-sortable" onClick={() => handleSort("timestamp")}>
                  <span>Timestamp</span>{" "}<span aria-hidden="true">{sortArrow("timestamp")}</span>
                </button>
              </th>
              {showAppColumn && !isMobile && (
                <th class="ht-col-app" aria-sort={ariaSortFor("app")} data-testid="sort-app">
                  <button type="button" class="ht-sortable" onClick={() => handleSort("app")}>
                    <span>App</span>{" "}<span aria-hidden="true">{sortArrow("app")}</span>
                  </button>
                </th>
              )}
              <th class="ht-col-source">Source</th>
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
                <td colSpan={isMobile ? 3 : (showAppColumn ? (showSourceColumn ? 5 : 4) : (showSourceColumn ? 4 : 3))} class="ht-text-center ht-text-muted">
                  No log entries.
                </td>
              </tr>
            )}
            {sorted.slice(0, 500).map((entry) => {
              const rowKey = entry.seq ? String(entry.seq) : `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
              const isExpanded = expandedRows.value.has(rowKey);
              const canExpand = truncatedRows.value.has(rowKey) || isExpanded;
              const toggle = () => {
                if (!canExpand) return;
                const next = new Set(expandedRows.value);
                if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                expandedRows.value = next;
              };
              const mobileColCount = 3; // level + time + message (source hidden, app hidden on mobile)
              const sourceAdjust = showSourceColumn ? 0 : -1;
              const desktopColCount = (showAppColumn ? 5 : 4) + sourceAdjust;
              const colCount = isMobile ? mobileColCount : desktopColCount;
              const rows = [
              <tr key={rowKey}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${entry.level === "ERROR" || entry.level === "CRITICAL" ? "danger" : entry.level === "WARNING" ? "warning" : entry.level === "DEBUG" ? "neutral" : "success"}`}>
                    {isMobile ? (LEVEL_ABBREV[entry.level] ?? entry.level) : entry.level}
                  </span>
                </td>
                <td class="ht-text-mono">{isMobile ? formatRelativeTime(entry.timestamp) : formatTimestamp(entry.timestamp)}</td>
                {showAppColumn && !isMobile && (
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
                  class={`ht-log-message-cell${canExpand ? " is-expandable" : ""}${isExpanded ? " is-expanded" : ""}${isMobile && isExpanded ? " is-mobile-expanded" : ""}`}
                  {...(canExpand ? { role: "button", tabIndex: 0, "aria-expanded": isExpanded,
                    "aria-label": isExpanded ? "Collapse log message" : "Expand log message" } : {})}
                  onClick={toggle}
                  onKeyDown={(e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
                >
                  <div data-row-key={rowKey} class={`ht-log-message__text${isExpanded && !isMobile ? " is-expanded" : ""}`}>
                    {isMobile && showAppColumn && entry.app_key && (
                      <span class="ht-log-app-tag ht-tag ht-tag--neutral">{entry.app_key}</span>
                    )}
                    {entry.message}
                  </div>
                </td>
              </tr>,
              ];
              if (isMobile && isExpanded) {
                rows.push(
                  <tr key={`${rowKey}-expanded`} class="ht-log-expanded-row">
                    <td colSpan={colCount} class="ht-log-expanded-cell">
                      <div class="ht-log-expanded-message">{entry.message}</div>
                    </td>
                  </tr>,
                );
              }
              return rows;
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
