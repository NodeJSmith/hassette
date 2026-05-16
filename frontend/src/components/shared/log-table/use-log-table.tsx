import { useCallback, useEffect, useMemo, useRef } from "preact/hooks";
import { useSignalEffect } from "@preact/signals";
import clsx from "clsx";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../../hooks/use-media-query";
import { useAppState } from "../../../state/context";
import type { LogEntry } from "../../../api/endpoints";
import type { RowKey, ViewContext, ColumnId, SortColumn, SortConfig, LevelFilter } from "./types";
import { rowKey } from "./types";
import { RENDER_CAP, DEFAULT_LEVEL, LEVEL_OPTIONS, TIER_OPTIONS } from "./constants";
import { useLogData } from "./use-log-data";
import { useLogFilters } from "./use-log-filters";
import { useColumnVisibility } from "./use-column-visibility";
import type { ColumnFilters } from "../table-types";
import { pluralize } from "../../../utils/format";
import filterStyles from "../column-filter-popover/index.module.css";

export interface UseLogTableParams {
  context?: ViewContext;
  appKey?: string;
  appKeys?: string[];
  executionId?: string | null;
  useLocalState?: boolean;
  search?: string;
}

export interface LogTableViewProps {
  visibleColumns: ColumnId[];
  sortConfig: SortConfig;
  onSort: (col: SortColumn) => void;
  columnFilters: ColumnFilters;
  entries: LogEntry[];
  selectedKey: RowKey | null;
  onRowClick: (entry: LogEntry) => void;
  isMobile: boolean;
}

export interface LogDrawerProps {
  selectedKey: RowKey | null;
  entries: LogEntry[];
  onClose: () => void;
  onNavigate: (key: RowKey) => void;
}

export interface ColumnPickerProps {
  selectedColumns: ColumnId[];
  viewportHidden: ReadonlySet<ColumnId>;
  onToggle: (id: ColumnId) => void;
  onReset: () => void;
}

export interface UseLogTableResult {
  tableProps: LogTableViewProps;
  drawerProps: LogDrawerProps;
  columnFilters: ColumnFilters;
  countLabel: string;
  hasActiveFilter: boolean;
  resetFilters: () => void;
  livePaused: boolean;
  resetSort: () => void;
  columnPickerProps: ColumnPickerProps;
  isMobile: boolean;
  isEmpty: boolean;
  isLoading: boolean;
}

export function useLogTable({
  context = "global",
  appKey,
  appKeys,
  executionId,
  useLocalState: useLocal = false,
  search: externalSearch,
}: UseLogTableParams): UseLogTableResult {
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
    useLocalState: useLocal || !!executionId,
    appKey,
  });

  useSignalEffect(() => {
    const level = filterState.value.level;
    updateLogSubscription(level || "DEBUG");
  });

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

  const handleRowClick = useCallback((entry: LogEntry) => {
    const key = rowKey(entry);
    selectedKey.value = selectedKey.value === key ? null : key;
  }, []);

  const handleDrawerClose = useCallback(() => {
    selectedKey.value = null;
  }, []);

  const handleDrawerNavigate = useCallback((key: RowKey) => {
    selectedKey.value = key;
  }, []);

  const hasActiveFilter = state.level !== DEFAULT_LEVEL
    || state.tier !== defaultTier || state.app !== "" || state.func !== "" || state.search !== "";

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

  const cappedEntries = entries.slice(0, RENDER_CAP);

  return {
    tableProps: {
      visibleColumns,
      sortConfig: state.sort,
      onSort: setSort,
      columnFilters,
      entries: cappedEntries,
      selectedKey: selectedKey.value,
      onRowClick: handleRowClick,
      isMobile,
    },
    drawerProps: {
      selectedKey: selectedKey.value,
      entries: cappedEntries,
      onClose: handleDrawerClose,
      onNavigate: handleDrawerNavigate,
    },
    columnFilters,
    countLabel,
    hasActiveFilter,
    resetFilters,
    livePaused: paused,
    resetSort,
    columnPickerProps: {
      selectedColumns,
      viewportHidden,
      onToggle: toggle,
      onReset: reset,
    },
    isMobile,
    isEmpty: !isLoading && entries.length === 0,
    isLoading,
  };
}
