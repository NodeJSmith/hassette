import { useCallback, useEffect, useMemo, useRef } from "preact/hooks";
import { useSignalEffect } from "@preact/signals";
import clsx from "clsx";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../../hooks/use-media-query";
import { useAppState } from "../../../state/context";
import type { LogEntry } from "../../../api/endpoints";
import type { RowKey, ViewContext } from "./types";
import { rowKey } from "./types";
import { RENDER_CAP, COLUMN_MAP, DEFAULT_LEVEL, LEVEL_OPTIONS, TIER_OPTIONS } from "./constants";
import type { LevelFilter } from "./types";
import { useLogData } from "./use-log-data";
import { useLogFilters } from "./use-log-filters";
import { useColumnVisibility } from "./use-column-visibility";
import { LogTableHeader } from "./log-table-header";
import { LogTableRow } from "./log-table-row";
import { LogDetailDrawer } from "./log-detail-drawer";
import { ColumnPicker } from "./column-picker";
import { EmptyState } from "../empty-state";
import { TableFooter } from "../table-footer";
import type { ColumnFilters } from "../table-types";
import { pluralize } from "../../../utils/format";
import filterStyles from "../column-filter-popover/index.module.css";
import styles from "./log-table.module.css";

interface Props {
  context?: ViewContext;
  appKey?: string;
  appKeys?: string[];
  executionId?: string | null;
  useLocalState?: boolean;
  emptyTitle?: string;
  emptyBody?: string;
  /** External search value — when provided, LogTable forwards it into the filter state immediately. */
  search?: string;
}

export function LogTable({
  context = "global",
  appKey,
  appKeys,
  executionId,
  useLocalState = false,
  emptyTitle,
  emptyBody,
  search: externalSearch,
}: Props) {
  const { visibleColumns, selectedColumns, viewportHidden, toggle, reset } = useColumnVisibility(context);
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const { updateLogSubscription } = useAppState();

  const selectedKey = useSignal<RowKey | null>(null);
  useSubscribe(selectedKey);

  const { allEntries, restEntries, loading } = useLogData({
    appKey,
    executionId,
  });

  const {
    filtered, filterState, livePaused, defaultTier,
    setLevel, setTier, setApp, setSearch, setFunc, setSort, resetSort, resetFilters,
  } = useLogFilters({
    allEntries,
    restEntries,
    useLocalState: useLocalState || !!executionId,
    appKey,
  });

  useSignalEffect(() => {
    const level = filterState.value.level;
    updateLogSubscription(level || "DEBUG");
  });

  // When an external search prop is provided, forward it into the filter state.
  const prevExternalSearch = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (externalSearch !== undefined && externalSearch !== prevExternalSearch.current) {
      prevExternalSearch.current = externalSearch;
      setSearch(externalSearch);
    }
  }, [externalSearch, setSearch]);

  const state = filterState.value;
  const entries = filtered.value;
  const paused = livePaused.value;
  const isLoading = loading.value;

  const colCount = visibleColumns.length;

  const handleRowClick = useCallback((entry: LogEntry) => {
    const key = rowKey(entry);
    selectedKey.value = selectedKey.value === key ? null : key;
  }, []);

  const handleDrawerNavigate = useCallback((key: RowKey) => {
    selectedKey.value = key;
  }, []);

  const handleDrawerClose = useCallback(() => {
    selectedKey.value = null;
  }, []);

  const drawerOpen = selectedKey.value !== null;

  const hasActiveFilter = state.level !== DEFAULT_LEVEL
    || state.tier !== defaultTier || state.app !== "" || state.func !== "" || state.search !== "";

  // Count label — mirrors the logic from the former LogTableFooter
  const isTruncated = entries.length > RENDER_CAP;
  const countLabel = isTruncated
    ? `showing ${RENDER_CAP} of ${entries.length}`
    : pluralize(entries.length, "entry", "entries");

  const columnFilters: ColumnFilters = useMemo(() => ({
    level: {
      active: state.level !== DEFAULT_LEVEL,
      label: "Level",
      content: (
        <div>
          <div class={filterStyles.heading}>Minimum level</div>
          <select
            value={state.level}
            onChange={(e) => setLevel((e.target as HTMLSelectElement).value as LevelFilter)}
            data-testid="filter-level"
          >
            {LEVEL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      ),
    },
    app: {
      active: state.tier !== defaultTier || state.app !== "",
      label: "App",
      content: (
        <div>
          <div class={filterStyles.tierGroup}>
            {TIER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                class={clsx(filterStyles.tierBtn, state.tier === opt.value && filterStyles.active)}
                onClick={() => setTier(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {state.tier !== "framework" && appKeys && appKeys.length > 0 && (
            <>
              <div class={filterStyles.heading}>App</div>
              <select
                value={state.app}
                onChange={(e) => setApp((e.target as HTMLSelectElement).value)}
                data-testid="filter-app"
              >
                <option value="">All apps</option>
                {appKeys.map((key) => (
                  <option key={key} value={key}>{key}</option>
                ))}
              </select>
            </>
          )}
        </div>
      ),
    },
    function: {
      active: state.func !== "",
      label: "Function",
      content: (
        <div>
          <div class={filterStyles.heading}>Function name</div>
          <input
            type="text"
            value={state.func}
            placeholder="Filter..."
            onInput={(e) => setFunc((e.target as HTMLInputElement).value)}
            data-testid="filter-fn"
          />
        </div>
      ),
    },
  }), [state.level, state.tier, state.app, state.func, defaultTier, appKeys, setLevel, setTier, setApp, setFunc]);

  // Extras for TableFooter: paused indicator + ColumnPicker (desktop only)
  const footerExtras = (
    <>
      {paused && (
        <button
          type="button"
          class={styles.pausedBtn}
          onClick={resetSort}
          aria-label="Resume live log streaming"
        >
          paused — click to resume
        </button>
      )}
      {!isMobile && (
        <ColumnPicker
          selectedColumns={selectedColumns}
          viewportHidden={viewportHidden}
          onToggle={toggle}
          onReset={reset}
        />
      )}
    </>
  );

  return (
    <div class={clsx(styles.wrapper, drawerOpen && styles.drawerOpen)}>
      <div class={styles.tableArea}>
        <div class={styles.scroll}>
          <table class="ht-table" data-testid="log-table">
            <colgroup>
              {visibleColumns.map((id) => {
                const col = COLUMN_MAP[id];
                const w = isMobile ? col.mobileWidth : col.width;
                return <col key={id} style={w ? { width: w } : undefined} />;
              })}
            </colgroup>
            <LogTableHeader
              visibleColumns={visibleColumns}
              sortConfig={state.sort}
              onSort={setSort}
              columnFilters={columnFilters}
            />
            <tbody>
              {!isLoading && entries.length === 0 && (
                <tr>
                  <td colSpan={colCount}>
                    <EmptyState
                      title={emptyTitle ?? "no log lines in window"}
                      body={emptyBody ?? "nothing has been logged recently. change the level filter or extend the time window to see older lines."}
                    />
                  </td>
                </tr>
              )}
              {entries.slice(0, RENDER_CAP).map((entry) => {
                const key = rowKey(entry);
                return (
                  <LogTableRow
                    key={key}
                    entry={entry}
                    rowKey={key}
                    visibleColumns={visibleColumns}
                    isSelected={selectedKey.value === key}
                    onClick={() => handleRowClick(entry)}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
        <TableFooter
          count={countLabel}
          columnFilters={columnFilters}
          onResetFilters={hasActiveFilter ? resetFilters : undefined}
          extras={footerExtras}
        />
      </div>

      <LogDetailDrawer
        selectedKey={selectedKey.value}
        entries={entries}
        onClose={handleDrawerClose}
        onNavigate={handleDrawerNavigate}
      />
    </div>
  );
}
