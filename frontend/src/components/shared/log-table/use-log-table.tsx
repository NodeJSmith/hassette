import clsx from "clsx";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { LogEntry } from "@/api/endpoints";
import { BREAKPOINT_MOBILE, useMediaQuery } from "@/hooks/use-media-query";
import { useAppStore } from "@/state/store";
import { pluralize } from "@/utils/format";

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
  useLocalState = false,
  search: externalSearch,
}: UseLogTableParams): UseLogTableResult {
  const { visibleColumns, selectedColumns, viewportHidden, toggle, reset } = useColumnVisibility(context);
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  const [selectedKey, setSelectedKey] = useState<RowKey | null>(null);

  const { allEntries, restEntries, loading } = useLogData({
    appKey,
    executionId,
  });

  const {
    visibleEntries,
    totalFilteredCount,
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
    useLocalState: useLocalState || !!executionId,
    appKey,
    executionId,
  });

  const level = filterState.level;
  useEffect(() => {
    useAppStore.getState().sendLogLevel(level || "DEBUG");
  }, [level]);

  const prevExternalSearch = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (externalSearch !== undefined && externalSearch !== prevExternalSearch.current) {
      prevExternalSearch.current = externalSearch;
      setSearch(externalSearch);
    }
  }, [externalSearch, setSearch]);

  const handleRowClick = useCallback((entry: LogEntry) => {
    const key = rowKey(entry);
    setSelectedKey((current) => (current === key ? null : key));
  }, []);

  const handleDrawerClose = useCallback(() => {
    setSelectedKey(null);
  }, []);

  const handleDrawerNavigate = useCallback((key: RowKey) => {
    setSelectedKey(key);
  }, []);

  const hasActiveFilter =
    filterState.level !== DEFAULT_LEVEL ||
    filterState.tier !== defaultTier ||
    filterState.app !== "" ||
    filterState.func !== "" ||
    filterState.search !== "";

  const isTruncated = totalFilteredCount > RENDER_CAP;
  const countLabel = isTruncated
    ? `showing ${RENDER_CAP} of ${totalFilteredCount}`
    : pluralize(totalFilteredCount, "entry", "entries");

  const columnFilters: ColumnFilters = useMemo(() => {
    const filters: ColumnFilters = {
      level: {
        active: filterState.level !== DEFAULT_LEVEL,
        label: "Level",
        content: (
          <select
            value={filterState.level}
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
        active: filterState.func !== "",
        label: "Function",
        content: (
          <input
            type="text"
            value={filterState.func}
            placeholder="Filter..."
            onInput={(e) => setFunc((e.target as HTMLInputElement).value)}
            data-testid="filter-fn"
          />
        ),
      },
    };

    // Execution-scoped panels show every log for one execution; a tier toggle there would
    // only hide some of that execution's own lines, so the tier/app filter is omitted.
    // Note the asymmetry with defaultTier (keyed on executionId): the global /logs page
    // filtered by execution_id still defaults to "all" but keeps this toggle, so a user can
    // narrow further by tier/app. Only the dedicated execution panel removes the toggle.
    if (!appKey && context !== "execution") {
      filters.app = {
        active: filterState.tier !== defaultTier || filterState.app !== "",
        label: "App",
        content: (
          <div>
            <div className="mb-2 flex gap-1">
              {TIER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={clsx(
                    "cursor-pointer rounded-sm px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary",
                    filterState.tier === opt.value && "bg-accent font-medium text-foreground",
                  )}
                  onClick={() => setTier(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {filterState.tier !== "framework" && appKeys && appKeys.length > 0 && (
              <select
                value={filterState.app}
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
    filterState.level,
    filterState.tier,
    filterState.app,
    filterState.func,
    defaultTier,
    appKey,
    appKeys,
    context,
    setLevel,
    setTier,
    setApp,
    setFunc,
  ]);

  return {
    tableProps: {
      visibleColumns,
      sort: filterState.sort,
      onSort: setSort,
      columnFilters,
      entries: visibleEntries,
      selectedKey,
      onRowClick: handleRowClick,
      isMobile,
    },
    drawerProps: {
      selectedKey,
      entries: visibleEntries,
      onClose: handleDrawerClose,
      onNavigate: handleDrawerNavigate,
    },
    columnFilters,
    countLabel,
    hasActiveFilter,
    resetFilters,
    livePaused,
    resetSort,
    columnPickerProps: {
      selectedColumns,
      viewportHidden,
      onToggle: toggle,
      onReset: reset,
    },
    isMobile,
    isEmpty: !loading && totalFilteredCount === 0,
    isLoading: loading,
  };
}
