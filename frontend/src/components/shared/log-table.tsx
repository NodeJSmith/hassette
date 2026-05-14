import { useEffect, useRef } from "preact/hooks";
import clsx from "clsx";
import { useSignal } from "../../hooks/use-signal";
import type { LogEntry } from "../../api/endpoints";
import { getRecentLogs } from "../../api/endpoints";
import { useMediaQuery, BREAKPOINT_MOBILE, BREAKPOINT_TABLET } from "../../hooks/use-media-query";
import { useQueryParams } from "../../hooks/use-query-params";
import { useSubscribe } from "../../hooks/use-subscribe";
import { useAppState } from "../../state/context";
import { formatTimestamp, pluralize } from "../../utils/format";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { levelToKind } from "../../utils/status";
import { AppLink } from "./app-link";
import { EmptyState } from "./empty-state";
import { SortHeader } from "./sort-header";
import { StatusShape } from "./status-shape";
import { TierToolbar } from "./tier-toolbar";
import styles from "./log-table.module.css";

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

const VALID_SORT_COLUMNS: ReadonlySet<string> = new Set(["timestamp", "level", "app", "source", "message"]);

const LEVEL_ABBREV: Record<string, string> = {
  DEBUG: "D",
  INFO: "I",
  WARNING: "W",
  ERROR: "E",
  CRITICAL: "C",
};

// ---- Log row component (must be a component to call useRelativeTime hook) ----

interface LogTableRowProps {
  entry: LogEntry;
  rowKey: string;
  isExpanded: boolean;
  isMobile: boolean;
  showAppColumn: boolean;
  showSourceColumn: boolean;
  showExecutionIdColumn: boolean;
  colCount: number;
  onToggle: () => void;
}

function LogTableRow({
  entry,
  rowKey,
  isExpanded,
  isMobile,
  showAppColumn,
  showSourceColumn,
  showExecutionIdColumn,
  colCount,
  onToggle,
}: LogTableRowProps) {
  const relativeTime = useRelativeTime(entry.timestamp);
  const rows = [
    <tr key={rowKey} data-level={entry.level}>
      <td>
        <span class={styles.levelBadge} data-testid="log-level-badge">
          <StatusShape kind={levelToKind(entry.level)} size={10} />
          <span class={styles.badgeText}>
            {isMobile ? (LEVEL_ABBREV[entry.level] ?? entry.level) : entry.level}
          </span>
        </span>
      </td>
      <td class="ht-text-mono">{isMobile ? relativeTime : formatTimestamp(entry.timestamp)}</td>
      {showAppColumn && !isMobile && (
        <td>
          {entry.app_key ? (
            <AppLink appKey={entry.app_key} />
          ) : (
            <span class="ht-text-muted">—</span>
          )}
        </td>
      )}
      {showExecutionIdColumn && !isMobile && (
        <td class="ht-text-mono ht-text-muted">
          {entry.execution_id ? (
            <span title={entry.execution_id}>{entry.execution_id.slice(0, 8)}&hellip;</span>
          ) : (
            <span class="ht-text-muted">—</span>
          )}
        </td>
      )}
      {showSourceColumn && !isMobile ? (
        <td class="ht-col-source" title={`${entry.logger_name}:${entry.func_name}:${entry.lineno}`}>
          <span class={styles.sourceFn}>{entry.func_name}() · {entry.logger_name.split(".").pop()}:{entry.lineno}</span>
        </td>
      ) : null}
      <td
        class={clsx(styles.messageCell, "is-expandable", isExpanded && "is-expanded")}
        data-testid="log-message-cell"
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? "Collapse log message" : "Expand log message"}
        onClick={onToggle}
        onKeyDown={(e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
      >
        {isMobile && entry.func_name && (
          <div class={styles.sourceInline} data-testid="log-source-inline">
            {showAppColumn && entry.app_key ? `${entry.app_key}.` : ""}{entry.func_name}()
          </div>
        )}
        <div data-row-key={rowKey} class={styles.messageText}>
          {entry.message}
        </div>
      </td>
    </tr>,
  ];
  if (isExpanded) {
    rows.push(
      <tr key={`${rowKey}-expanded`} class={styles.expandedRow}>
        <td colSpan={colCount} class={styles.expandedCell}>
          <pre class={styles.expandedMessage}>{entry.message}</pre>
        </td>
      </tr>,
    );
  }
  return <>{rows}</>;
}

// ---- Sort header (defined outside LogTable to avoid re-definition on each render) ----

interface LogSortHeaderProps {
  col: SortColumn;
  children: preact.ComponentChildren;
  class?: string;
  sortConfig: SortConfig;
  onSort: (col: SortColumn) => void;
}

function LogSortHeader({ col, children, class: className, sortConfig, onSort }: LogSortHeaderProps) {
  const isActive = sortConfig.column === col;
  return (
    <SortHeader
      active={isActive}
      direction={isActive ? (sortConfig.asc ? "asc" : "desc") : "asc"}
      onClick={() => onSort(col)}
      class={className}
      data-testid={`sort-${col}`}
    >
      {children}
    </SortHeader>
  );
}

// ---- Log fetch params ----

export interface LogFetchParams {
  app_key?: string;
  limit?: number;
  since?: number | null;
}

function nextSortState(clicked: SortColumn, currentCol: SortColumn, currentAsc: boolean): { column: SortColumn; asc: boolean } {
  if (clicked === "timestamp") {
    return { column: "timestamp", asc: currentCol === "timestamp" ? !currentAsc : false };
  }
  if (currentCol === clicked) {
    return { column: clicked, asc: !currentAsc };
  }
  return { column: clicked, asc: false };
}

// ---- Log table ----

interface Props {
  showAppColumn?: boolean;
  appKey?: string;
  /** List of app keys for the app filter dropdown (global logs page) */
  appKeys?: string[];
  /** Hide the internal "logs" heading when the parent page renders its own */
  hideTitle?: boolean;
  /**
   * Custom fetcher for historical mode. Called instead of getRecentLogs.
   * Required when mode="historical".
   */
  fetcher?: (params?: LogFetchParams) => Promise<LogEntry[]>;
  /** "live" (default): REST fetch + WS merge + URL params. "historical": custom fetcher only, no WS. */
  mode?: "live" | "historical";
  /** When true, use component-local signals for filter/sort state instead of URL query params. */
  useLocalState?: boolean;
  /** When true, hide the execution_id column (use when the view is already filtered to one execution). */
  hideExecutionId?: boolean;
  /** Filter logs to a specific execution. Shows a dismissible pill in the toolbar. */
  executionId?: string | null;
  /** Called when the user dismisses the execution filter pill. */
  onClearExecutionId?: () => void;
  /** Custom empty state title (overrides default "no log lines in window"). */
  emptyTitle?: string;
  /** Custom empty state body (overrides default hint about filters/time window). */
  emptyBody?: string;
}

export function LogTable({
  showAppColumn = true,
  appKey,
  appKeys,
  hideTitle,
  fetcher,
  mode = "live",
  useLocalState: useLocalStateProp = false,
  hideExecutionId: hideExecutionIdProp = false,
  executionId,
  onClearExecutionId,
  emptyTitle,
  emptyBody,
}: Props) {
  if (mode === "historical" && !fetcher) {
    throw new Error("LogTable: fetcher prop is required when mode='historical'");
  }
  const useLocalState = useLocalStateProp || !!executionId;
  const hideExecutionId = hideExecutionIdProp || !!executionId;
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  // Source column is CSS-hidden at max-width: 1024px (see log-table.module.css .tableLog .ht-col-source)
  // Ideally the Source <th>/<td> would be conditionally rendered like the App column,
  // but for now we just adjust the colSpan to match the CSS-only hide.
  const isTablet = useMediaQuery(BREAKPOINT_TABLET);
  const showSourceColumn = !isTablet;
  const showExecutionIdColumn = !hideExecutionId;
  const colCount = isMobile ? 3 : 3 + (showAppColumn ? 1 : 0) + (showSourceColumn ? 1 : 0) + (showExecutionIdColumn ? 1 : 0);
  const { logs, updateLogSubscription, reconnectVersion } = useAppState();

  // In live mode, subscribe to the WS log version signal for reactivity.
  // In historical mode, skip the subscription — no WS merge.
  useSubscribe(mode === "live" ? logs.version : null);

  const qp = useQueryParams();
  // Keep a stable ref to the latest qp so event handlers always use the most
  // recent URL params without needing to close over the render-cycle value.
  const qpRef = useRef(qp);
  qpRef.current = qp;

  // Local signal state for historical mode (useLocalState=true).
  const localLevel = useSignal("INFO");
  const localAppFilter = useSignal("");
  const localTierFilter = useSignal<"all" | "app" | "framework">(appKey ? "all" : "app");
  const localSearch = useSignal("");
  const localSortColumn = useSignal<SortColumn>("timestamp");
  const localSortAsc = useSignal(false);

  // Debounce timer ref for search input
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current); }, []);

  // Read filter/sort state from URL params (live mode) or local signals (historical+useLocalState).
  let minLevel: string;
  let appFilter: string;
  let tierFilter: "all" | "app" | "framework";
  let search: string;
  let sortColumn: SortColumn;
  let sortAsc: boolean;

  if (useLocalState) {
    minLevel = localLevel.value;
    appFilter = localAppFilter.value;
    tierFilter = localTierFilter.value;
    search = localSearch.value;
    sortColumn = localSortColumn.value;
    sortAsc = localSortAsc.value;
  } else {
    // Filter/sort state read from query params; defaults omitted from URL.
    // level="INFO" is the omitted default; level="all" in URL means show everything (minLevel="").
    const levelParam = qp.get("level");
    minLevel = levelParam === "all" ? "" : (levelParam ?? "INFO");
    appFilter = qp.get("app") ?? "";
    const tierFilterRaw = qp.get("tier");
    // App-scoped views default to "all" (show both app + framework logs for that app).
    // Global views default to "app" (hide noisy framework logs unless explicitly requested).
    tierFilter =
      tierFilterRaw === "all" || tierFilterRaw === "framework"
        ? tierFilterRaw
        : (appKey ? "all" : "app");
    search = qp.get("search") ?? "";
    const rawSort = qp.get("sort") ?? "timestamp";
    sortColumn = VALID_SORT_COLUMNS.has(rawSort) ? (rawSort as SortColumn) : "timestamp";
    const sortDir = qp.get("dir");
    // Default dir: "desc" for timestamp (asc: false), "desc" for all others (asc: false as well
    // when clicking a new non-timestamp column). "asc" is only set when explicitly in URL.
    sortAsc = sortDir === "asc";
  }

  const sortConfig: SortConfig = { column: sortColumn, asc: sortAsc };

  // UI-only state (not URL state)
  const initialEntries = useSignal<LogEntry[]>([]);
  const expandedRows = useSignal<Set<string>>(new Set());

  const watermarkRef = useRef(0);

  // In live mode: sync WS subscription to current level — re-syncs on back/forward navigation.
  // In historical mode: skip — no WS subscription to manage.
  useEffect(() => {
    if (mode !== "live") return;
    updateLogSubscription(minLevel || "DEBUG");
  }, [mode, minLevel, updateLogSubscription]);

  // Fetch initial entries on mount and after reconnect (live mode) or once on mount (historical mode).
  // rv drives reconnect-triggered refetch — only meaningful in live mode.
  const rv = mode === "live" ? reconnectVersion.value : null;
  useEffect(() => {
    watermarkRef.current = 0;
    if (mode === "historical" && fetcher) {
      fetcher()
        .then((entries) => {
          initialEntries.value = entries;
          watermarkRef.current = entries.reduce((max, e) => Math.max(max, e.timestamp), 0);
        })
        .catch(() => { /* fetcher error — stay empty */ });
    } else {
      getRecentLogs({ app_key: appKey, limit: 200, execution_id: executionId })
        .then((entries) => {
          initialEntries.value = entries;
          watermarkRef.current = entries.reduce((max, e) => Math.max(max, e.timestamp), 0);
        })
        .catch(() => { /* API error — initial entries stay empty, WS will still stream */ });
    }
  }, [mode, appKey, rv, fetcher, executionId]);

  // Combine initial entries + ring buffer entries, deduplicating by timestamp watermark.
  // Timestamp-based (not seq-based) because seq resets to 1 on process restart while
  // the DB retains records from previous sessions with higher seq values.
  // In historical mode, skip WS merge entirely.
  const wsEntries = mode === "live" ? logs.toArray().filter((e) => {
    if (e.timestamp <= watermarkRef.current) return false;
    if (appKey && e.app_key !== appKey) return false;
    if (executionId && e.execution_id !== executionId) return false;
    return true;
  }) : [];

  // Live pause: when sorting by non-timestamp column, exclude WS entries
  const livePaused = mode === "live" && sortConfig.column !== "timestamp";
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
      ? levelFiltered.filter((e) => e.source_tier === "app")
      : levelFiltered.filter((e) => e.source_tier === "framework");

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
    if (useLocalState) {
      const next = nextSortState(column, localSortColumn.value, localSortAsc.value);
      localSortColumn.value = next.column;
      localSortAsc.value = next.asc;
      return;
    }

    // Read current sort state via qpRef.current (always latest after re-renders)
    // so rapid successive clicks see the current URL state, not stale closure values.
    const current = qpRef.current;
    const currentSortCol = (current.get("sort") ?? "timestamp") as SortColumn;
    const currentSortAsc = current.get("dir") === "asc";
    const next = nextSortState(column, currentSortCol, currentSortAsc);

    // Omit defaults from URL: timestamp+desc is the default state
    const isDefault = next.column === "timestamp" && !next.asc;
    current.set({
      sort: isDefault ? null : next.column,
      dir: next.asc ? "asc" : null,
    });
  };

  const handleResume = () => {
    // Reset to default timestamp sort (omit sort and dir from URL)
    qpRef.current.set({ sort: null, dir: null });
  };


  const setLevel = (newLevel: string) => {
    if (useLocalState) {
      localLevel.value = newLevel;
      return;
    }
    // Omit level param when it's the default (INFO).
    // Store "" (all levels) as "all" in the URL since empty string is stripped.
    if (newLevel === "INFO") {
      qpRef.current.set({ level: null });
    } else if (newLevel === "") {
      qpRef.current.set({ level: "all" });
    } else {
      qpRef.current.set({ level: newLevel });
    }
    // In live mode, re-sync WS subscription to the new level
    if (mode === "live") {
      updateLogSubscription(newLevel || "DEBUG");
    }
  };

  const setSearch = (value: string) => {
    if (useLocalState) {
      localSearch.value = value;
      return;
    }
    qpRef.current.set({ search: value || null });
  };

  const levelLabel = minLevel ? `level: ${minLevel}+` : "level: all";

  // Truncation indicator: when the render cap (500) is exceeded, show "showing 500 of N"
  const renderCap = 500;
  const isTruncated = sorted.length > renderCap;
  const countLabel = isTruncated
    ? `showing ${renderCap} of ${sorted.length}`
    : pluralize(filtered.length, "entry", "entries");

  return (
    <div class={styles.container}>
      <div class="ht-table-toolbar">
        <div class="ht-table-toolbar__title">
          {!hideTitle && <h2 class="ht-table-toolbar__heading">logs</h2>}
          <span class="ht-table-toolbar__note" aria-live="polite">{countLabel}</span>
        </div>
        <div class="ht-table-toolbar__controls">
          {executionId && (
            <span class="ht-pill ht-pill--mute" data-testid="execution-filter-pill">
              <span class="ht-text-mono">execution: {executionId.slice(0, 8)}&hellip;</span>
              {onClearExecutionId && (
                <button
                  type="button"
                  class={styles.pillDismiss}
                  onClick={onClearExecutionId}
                  aria-label="Clear execution filter"
                  data-testid="clear-execution-filter"
                >
                  &times;
                </button>
              )}
            </span>
          )}
          {!appKey && !useLocalState && (
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
                setLevel(newLevel);
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
              if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
              searchDebounceRef.current = setTimeout(() => {
                setSearch(value);
              }, 150);
            }}
          />
        </div>
      </div>
      <div class="ht-table-card-scroll">
        <table class={clsx("ht-table ht-table--compact", styles.tableLog)} data-testid="log-table">
          <thead>
            <tr>
              <LogSortHeader col="level" class="ht-col-level" sortConfig={sortConfig} onSort={handleSort}>
                {isMobile ? "Lvl" : "Level"}
              </LogSortHeader>
              <LogSortHeader col="timestamp" class="ht-col-time" sortConfig={sortConfig} onSort={handleSort}>
                Timestamp
              </LogSortHeader>
              {showAppColumn && !isMobile && (
                <LogSortHeader col="app" class="ht-col-app" sortConfig={sortConfig} onSort={handleSort}>
                  App
                </LogSortHeader>
              )}
              {showExecutionIdColumn && !isMobile && (
                <th class="ht-col-execution">Execution</th>
              )}
              <LogSortHeader col="source" class="ht-col-source" sortConfig={sortConfig} onSort={handleSort}>
                Source
              </LogSortHeader>
              <LogSortHeader col="message" sortConfig={sortConfig} onSort={handleSort}>
                Message
              </LogSortHeader>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={colCount}>
                  <EmptyState
                    title={emptyTitle ?? "no log lines in window"}
                    body={emptyBody ?? "nothing has been logged recently. change the level filter or extend the time window to see older lines."}
                  />
                </td>
              </tr>
            )}
            {sorted.slice(0, renderCap).map((entry) => {
              const rowKey = entry.seq ? `${entry.timestamp}-${entry.seq}` : `${entry.timestamp}-${entry.logger_name}-${entry.lineno}`;
              const isExpanded = expandedRows.value.has(rowKey);
              const toggle = () => {
                const next = new Set(expandedRows.value);
                if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                expandedRows.value = next;
              };
              return (
                <LogTableRow
                  key={rowKey}
                  entry={entry}
                  rowKey={rowKey}
                  isExpanded={isExpanded}
                  isMobile={isMobile}
                  showAppColumn={showAppColumn}
                  showSourceColumn={showSourceColumn}
                  showExecutionIdColumn={showExecutionIdColumn}
                  colCount={colCount}
                  onToggle={toggle}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
