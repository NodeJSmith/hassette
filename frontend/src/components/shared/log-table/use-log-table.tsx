import { useSignalEffect } from "@preact/signals";
import clsx from "clsx";
import { useCallback, useEffect, useMemo, useRef } from "preact/hooks";

import type { LogEntry } from "../../../api/endpoints";
import { BREAKPOINT_MOBILE, useMediaQuery } from "../../../hooks/use-media-query";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { useAppState } from "../../../state/context";
import { pluralize } from "../../../utils/format";
import filterStyles from "../column-filter-popover/index.module.css";
import type { ColumnFilters } from "../table-types";
import { DEFAULT_LEVEL, LEVEL_OPTIONS, RENDER_CAP, TIER_OPTIONS } from "./constants";
import type { ColumnId, LevelFilter, LogSortState, RowKey, ViewContext } from "./types";
import { rowKey } from "./types";
import { useColumnVisibility } from "./use-column-visibility";
import { useLogData } from "./use-log-data";
import { useLogFilters } from "./use-log-filters";

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
  sort: LogSortState;
  onSort: (sort: LogSortState) => void;
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
    filtered,
    filterState,
    livePaused,
    defaultTier,
    setLevel,
    setTier,
    setApp,
    setSearch,
    setFunc,
    setSort,
    resetSort,
    resetFilters,
  } = useLogFilters({
    allEntries,
    restEntries,
    // Execution-scoped views always use local state — URL params are owned by the parent page.
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
  const entries = filtered;
  const paused = livePaused.value;
  const isLoading = loading;

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

  const hasActiveFilter =
    state.level !== DEFAULT_LEVEL ||
    state.tier !== defaultTier ||
    state.app !== "" ||
    state.func !== "" ||
    state.search !== "";

  const isTruncated = entries.length > RENDER_CAP;
  const countLabel = isTruncated
    ? `showing ${RENDER_CAP} of ${entries.length}`
    : pluralize(entries.length, "entry", "entries");

  const columnFilters: ColumnFilters = useMemo(() => {
    const filters: ColumnFilters = {
      level: {
        active: state.level !== DEFAULT_LEVEL,
        label: "Level",
        content: (
          <select
            value={state.level}
            onChange={(e) => setLevel((e.target as HTMLSelectElement).value as LevelFilter)}
            data-testid="filter-level"
          >
            {LEVEL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        ),
      },
      function: {
        active: state.func !== "",
        label: "Function",
        content: (
          <input
            type="text"
            value={state.func}
            placeholder="Filter..."
            onInput={(e) => setFunc((e.target as HTMLInputElement).value)}
            data-testid="filter-fn"
          />
        ),
      },
    };

    if (!appKey) {
      filters.app = {
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
              <select
                value={state.app}
                onChange={(e) => setApp((e.target as HTMLSelectElement).value)}
                data-testid="filter-app"
              >
                <option value="">All apps</option>
                {appKeys.map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
            )}
          </div>
        ),
      };
    }

    return filters;
  }, [
    state.level,
    state.tier,
    state.app,
    state.func,
    defaultTier,
    appKey,
    appKeys,
    setLevel,
    setTier,
    setApp,
    setFunc,
  ]);

  const cappedEntries = entries.slice(0, RENDER_CAP);

  return {
    tableProps: {
      visibleColumns,
      sort: state.sort,
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
