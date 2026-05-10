import { useEffect, useRef, useCallback } from "preact/hooks";
import { useSignal } from "../../hooks/use-signal";
import type { LogEntry } from "../../api/endpoints";
import { getRecentLogs } from "../../api/endpoints";
import { useMediaQuery, BREAKPOINT_MOBILE, BREAKPOINT_TABLET } from "../../hooks/use-media-query";
import { useQueryParams } from "../../hooks/use-query-params";
import { useSubscribe } from "../../hooks/use-subscribe";
import { useAppState } from "../../state/context";
import { formatTimestamp, formatRelativeTime, pluralize } from "../../utils/format";
import { levelToKind } from "../../utils/status";
import { AppLink } from "./app-link";
import { SortHeader } from "./sort-header";
import { StatusShape } from "./status-shape";
import { TierToolbar } from "./tier-toolbar";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;

export type SortColumn = "timestamp" | "level" | "app" | "source" | "message";

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
        const aMissing = !aKey;
        const bMissing = !bKey;
        if (aMissing && bMissing) return 0;
        if (aMissing) return 1;  // nulls always last
        if (bMissing) return -1; // nulls always last
        return aKey.localeCompare(bKey) * direction;
      }
      case "source":
        return a.func_name.localeCompare(b.func_name) * direction;
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
  /** Hide the internal "logs" heading when the parent page renders its own */
  hideTitle?: boolean;
}

export function LogTable({ showAppColumn = true, appKey, appKeys, hideTitle }: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  // Source column is CSS-hidden at max-width: 1024px (see global.css .ht-table-log .ht-col-source)
  // Ideally the Source <th>/<td> would be conditionally rendered like the App column,
  // but for now we just adjust the colSpan to match the CSS-only hide.
  const isTablet = useMediaQuery(BREAKPOINT_TABLET);
  const showSourceColumn = !isTablet;
  const { logs, updateLogSubscription, reconnectVersion, tick } = useAppState();
  useSubscribe(tick, logs.version);
  const qp = useQueryParams();
  // Keep a stable ref to the latest qp so event handlers always use the most
  // recent URL params without needing to close over the render-cycle value.
  const qpRef = useRef(qp);
  qpRef.current = qp;

  // Filter/sort state read from query params; defaults omitted from URL.
  // level="INFO" is the omitted default; level="all" in URL means show everything (minLevel="").
  const levelParam = qp.get("level");
  const minLevel = levelParam === "all" ? "" : (levelParam ?? "INFO");
  const appFilter = qp.get("app") ?? "";
  const tierFilterRaw = qp.get("tier");
  // App-scoped views default to "all" (show both app + framework logs for that app).
  // Global views default to "app" (hide noisy framework logs unless explicitly requested).
  const tierFilter: "all" | "app" | "framework" =
    tierFilterRaw === "all" || tierFilterRaw === "framework"
      ? tierFilterRaw
      : (appKey ? "all" : "app");
  const search = qp.get("search") ?? "";
  const sortColumn = (qp.get("sort") ?? "timestamp") as SortColumn;
  const sortDir = qp.get("dir");
  // Default dir: "desc" for timestamp (asc: false), "desc" for all others (asc: false as well
  // when clicking a new non-timestamp column). "asc" is only set when explicitly in URL.
  const sortAsc = sortDir === "asc";
  const sortConfig: SortConfig = { column: sortColumn, asc: sortAsc };

  // UI-only state (not URL state)
  const initialEntries = useSignal<LogEntry[]>([]);
  const expandedRows = useSignal<Set<string>>(new Set());

  const watermarkRef = useRef(0);

  // Sync WS subscription to current level — re-syncs on back/forward navigation
  useEffect(() => {
    updateLogSubscription(minLevel || "DEBUG");
  }, [minLevel]);

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

  // Combine initial entries + ring buffer entries, deduplicating by seq watermark
  const wsEntries = logs.toArray().filter((e) => {
    if (e.seq <= watermarkRef.current) return false;
    if (appKey && e.app_key !== appKey) return false;
    return true;
  });

  // Live pause: when sorting by non-timestamp column, exclude WS entries
  const livePaused = sortConfig.column !== "timestamp";
  const allEntries = livePaused
    ? [...initialEntries.value]
    : [...initialEntries.value, ...wsEntries];

  // Apply level filter
  const levelFiltered = minLevel
    ? allEntries.filter((e) => {
        const levelIndex = LEVELS.indexOf(minLevel as (typeof LEVELS)[number]);
        const entryIndex = LEVELS.indexOf(e.level as (typeof LEVELS)[number]);
        return entryIndex >= levelIndex;
      })
    : allEntries; // "" = All Levels — show everything

  // Apply source tier filter
  const tierFiltered = tierFilter === "all"
    ? levelFiltered
    : tierFilter === "app"
      ? levelFiltered.filter((e) => !!e.app_key)
      : levelFiltered.filter((e) => !e.app_key);

  // Apply app filter (only for global logs)
  const appFiltered = appFilter
    ? tierFiltered.filter((e) => e.app_key === appFilter)
    : tierFiltered;

  // Apply search filter
  const filtered = search
    ? appFiltered.filter(
        (e) =>
          e.message.toLowerCase().includes(search.toLowerCase()) ||
          e.logger_name.toLowerCase().includes(search.toLowerCase()),
      )
    : appFiltered;

  // Sort
  const sorted = sortEntries(filtered, sortConfig.column, sortConfig.asc);

  const handleSort = (column: SortColumn) => {
    // Read current sort state via qpRef.current (always latest after re-renders)
    // so rapid successive clicks see the current URL state, not stale closure values.
    const current = qpRef.current;
    const currentSortCol = (current.get("sort") ?? "timestamp") as SortColumn;
    const currentSortAsc = current.get("dir") === "asc";

    if (column === "timestamp") {
      // Toggling timestamp: flip asc. Default for timestamp is desc (false).
      const newAsc = currentSortCol === "timestamp" ? !currentSortAsc : false;
      if (newAsc) {
        current.set({ sort: null, dir: "asc" });
      } else {
        // Default: omit both sort and dir
        current.set({ sort: null, dir: null });
      }
    } else if (currentSortCol === column) {
      // Toggle direction on the same non-timestamp column
      const newAsc = !currentSortAsc;
      current.set({ sort: column, dir: newAsc ? "asc" : null });
    } else {
      // New non-timestamp column — default dir is desc
      current.set({ sort: column, dir: null });
    }
  };

  const handleResume = () => {
    // Reset to default timestamp sort (omit sort and dir from URL)
    qpRef.current.set({ sort: null, dir: null });
  };

  // Track which rows have truncated message text (scrollWidth > clientWidth).
  //
  // NOTE: Expanded rows have `text-overflow: ellipsis` removed by CSS (via the
  // `.is-expanded` class), so `scrollWidth === clientWidth` for them — they will
  // NOT appear in `truncatedRows`. The `|| isExpanded` guard in the render path
  // (`canExpand = truncatedRows.value.has(rowKey) || isExpanded`) is load-bearing:
  // it keeps expanded rows collapsible even when recheckTruncation() doesn't
  // include them. Do NOT remove that guard.
  const truncatedRows = useSignal(new Set<string>());
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

  const LogSortHeader = ({ col, children, class: className }: { col: SortColumn; children: preact.ComponentChildren; class?: string }) => {
    const isActive = sortConfig.column === col;
    return (
      <SortHeader
        active={isActive}
        direction={isActive ? (sortConfig.asc ? "asc" : "desc") : "asc"}
        onClick={() => handleSort(col)}
        class={className}
        data-testid={`sort-${col}`}
      >
        {children}
      </SortHeader>
    );
  };

  const levelLabel = minLevel ? `level: ${minLevel}+` : "level: all";

  return (
    <div class="ht-log-table-container" ref={tableContainerRef}>
      <div class="ht-table-toolbar">
        <div class="ht-table-toolbar__title">
          {!hideTitle && <h2 class="ht-table-toolbar__heading">logs</h2>}
          <span class="ht-table-toolbar__note" aria-live="polite">{pluralize(filtered.length, "entry", "entries")}</span>
        </div>
        <div class="ht-table-toolbar__controls">
          {!appKey && (
            <TierToolbar
              tierFilter={tierFilter}
              onTierChange={(t) => {
                const defaultTier = appKey ? "all" : "app";
                qp.set({ tier: t === defaultTier ? null : t });
              }}
              appKeys={showAppColumn ? appKeys : undefined}
              selectedApp={appFilter}
              onAppChange={(a) => { qp.set({ app: a || null }); }}
              testIdPrefix="log"
            />
          )}
          {livePaused && (
            <button
              type="button"
              class="ht-pill ht-pill--warn"
              onClick={handleResume}
              aria-label="Resume live log streaming"
            >
              <StatusShape kind="warn" size={6} />
              paused — click to resume
            </button>
          )}
          <label class="ht-pill ht-pill--mute ht-pill--interactive">
            {levelLabel}
            <select
              class="ht-pill__select"
              aria-label="Minimum log level"
              data-testid="filter-level"
              value={minLevel}
              onChange={(e) => {
                const newLevel = (e.target as HTMLSelectElement).value;
                // Omit level param when it's the default (INFO).
                // Store "" (all levels) as "all" in the URL since empty string is stripped.
                if (newLevel === "INFO") {
                  qp.set({ level: null });
                } else if (newLevel === "") {
                  qp.set({ level: "all" });
                } else {
                  qp.set({ level: newLevel });
                }
                updateLogSubscription(newLevel || "DEBUG");
              }}
            >
              <option value="">all</option>
              {LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}+
                </option>
              ))}
            </select>
          </label>
          <input
            class="ht-search"
            type="text"
            aria-label="Search logs"
            placeholder="Search..."
            value={search}
            onInput={(e) => {
              const value = (e.target as HTMLInputElement).value;
              qp.set({ search: value || null });
            }}
          />
        </div>
      </div>
      <div class="ht-table-card-scroll">
        <table class="ht-table ht-table--compact ht-table-log">
          <thead>
            <tr>
              <LogSortHeader col="level" class="ht-col-level">{isMobile ? "Lvl" : "Level"}</LogSortHeader>
              <LogSortHeader col="timestamp" class="ht-col-time">Timestamp</LogSortHeader>
              {showAppColumn && !isMobile && (
                <LogSortHeader col="app" class="ht-col-app">App</LogSortHeader>
              )}
              <LogSortHeader col="source" class="ht-col-source">Source</LogSortHeader>
              <LogSortHeader col="message">Message</LogSortHeader>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={isMobile ? 3 : 2 + (showAppColumn ? 1 : 0) + (showSourceColumn ? 1 : 0) + 1} class="ht-empty">
                  <div class="ht-empty__icon">∅</div>
                  <div class="ht-empty__title">no log lines in window</div>
                  <div class="ht-empty__body">nothing has been logged recently. change the level filter or extend the time window to see older lines.</div>
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
              const mobileColCount = 3;
              const sourceAdjust = showSourceColumn ? 0 : -1;
              const desktopColCount = (showAppColumn ? 5 : 4) + sourceAdjust;
              const colCount = isMobile ? mobileColCount : desktopColCount;
              const rows = [
              <tr key={rowKey} data-level={entry.level}>
                <td>
                  <span class="ht-log-level-badge">
                    <StatusShape kind={levelToKind(entry.level)} size={10} />
                    <span class="ht-log-level-badge__text">
                      {isMobile ? (LEVEL_ABBREV[entry.level] ?? entry.level) : entry.level}
                    </span>
                  </span>
                </td>
                <td class="ht-text-mono">{isMobile ? formatRelativeTime(entry.timestamp) : formatTimestamp(entry.timestamp)}</td>
                {showAppColumn && !isMobile && (
                  <td>
                    {entry.app_key ? (
                      <AppLink appKey={entry.app_key} />
                    ) : (
                      <span class="ht-text-muted">—</span>
                    )}
                  </td>
                )}
                <td class="ht-col-source" title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
                  <span class="ht-log-source__fn">{entry.func_name}() · {entry.logger_name.split(".").pop()}:{entry.lineno}</span>
                </td>
                <td
                  class={`ht-log-message-cell${canExpand ? " is-expandable" : ""}${isExpanded ? " is-expanded" : ""}`}
                  {...(canExpand ? { role: "button", tabIndex: 0, "aria-expanded": isExpanded,
                    "aria-label": isExpanded ? "Collapse log message" : "Expand log message" } : {})}
                  onClick={toggle}
                  onKeyDown={(e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
                >
                  {isMobile && entry.func_name && (
                    <div class="ht-log-source-inline">
                      {showAppColumn && entry.app_key ? `${entry.app_key}.` : ""}{entry.func_name}()
                    </div>
                  )}
                  <div data-row-key={rowKey} class="ht-log-message__text">
                    {entry.message}
                  </div>
                </td>
              </tr>,
              ];
              if (isExpanded) {
                rows.push(
                  <tr key={`${rowKey}-expanded`} class="ht-log-expanded-row">
                    <td colSpan={colCount} class="ht-log-expanded-cell">
                      <pre class="ht-log-expanded-message">{entry.message}</pre>
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
