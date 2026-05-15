import { useCallback, useRef } from "preact/hooks";
import { useSignalEffect } from "@preact/signals";
import clsx from "clsx";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../../hooks/use-media-query";
import { useAppState } from "../../../state/context";
import type { LogEntry } from "../../../api/endpoints";
import type { RowKey, ViewContext } from "./types";
import { rowKey } from "./types";
import { RENDER_CAP, COLUMN_MAP, DEFAULT_LEVEL } from "./constants";
import { useLogData } from "./use-log-data";
import { useLogFilters } from "./use-log-filters";
import { useColumnVisibility } from "./use-column-visibility";
import { LogTableHeader } from "./log-table-header";
import { LogTableRow } from "./log-table-row";
import { LogTableFooter } from "./log-table-footer";
import { LogDetailDrawer } from "./log-detail-drawer";
import { EmptyState } from "../empty-state";
import styles from "./log-table.module.css";

interface Props {
  context?: ViewContext;
  appKey?: string;
  appKeys?: string[];
  executionId?: string | null;
  useLocalState?: boolean;
  emptyTitle?: string;
  emptyBody?: string;
}

export function LogTable({
  context = "global",
  appKey,
  appKeys,
  executionId,
  useLocalState = false,
  emptyTitle,
  emptyBody,
}: Props) {
  const { visibleColumns, selectedColumns, viewportHidden, toggle, reset } = useColumnVisibility(context);
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const { updateLogSubscription } = useAppState();

  const selectedKey = useSignal<RowKey | null>(null);
  useSubscribe(selectedKey);
  const searchInput = useSignal("");
  useSubscribe(searchInput);

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

  const searchFromInput = useRef(false);
  useSignalEffect(() => {
    const search = filterState.value.search;
    if (!searchFromInput.current && searchInput.value !== search) {
      searchInput.value = search;
    }
    searchFromInput.current = false;
  });

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

  const handleSearchChange = useCallback((value: string) => {
    searchFromInput.current = true;
    searchInput.value = value;
    setSearch(value);
  }, [setSearch]);

  const drawerOpen = selectedKey.value !== null;
  const hasActiveFilter = state.level !== DEFAULT_LEVEL
    || state.tier !== defaultTier || state.app !== "" || state.func !== "" || state.search !== "";

  return (
    <div class={clsx(styles.wrapper, drawerOpen && styles.drawerOpen)}>
      <div class={styles.tableArea}>
        <div class={styles.scroll}>
          <table class={styles.table} data-testid="log-table">
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
              level={state.level}
              onLevelChange={setLevel}
              tier={state.tier}
              onTierChange={setTier}
              appFilter={state.app}
              onAppChange={setApp}
              appKeys={appKeys}
              fnFilter={state.func}
              onFnChange={setFunc}
              defaultTier={defaultTier}
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
        <LogTableFooter
          totalCount={entries.length}
          livePaused={paused}
          onResume={resetSort}
          search={searchInput.value}
          onSearchChange={handleSearchChange}
          selectedColumns={selectedColumns}
          viewportHidden={viewportHidden}
          onToggleColumn={toggle}
          onResetColumns={reset}
          level={state.level}
          onLevelChange={setLevel}
          tier={state.tier}
          onTierChange={setTier}
          appFilter={state.app}
          onAppChange={setApp}
          appKeys={appKeys}
          fnFilter={state.func}
          onFnChange={setFunc}
          hasActiveFilter={hasActiveFilter}
          onResetFilters={resetFilters}
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
