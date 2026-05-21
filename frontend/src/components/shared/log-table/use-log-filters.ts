import { computed, type ReadonlySignal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";

import type { LogEntry } from "../../../api/endpoints";
import { useQueryParams } from "../../../hooks/use-query-params";
import { useSignal } from "../../../hooks/use-signal";
import { DEFAULT_LEVEL, LEVEL_INDEX, LEVELS, resolveSortColumn, SEARCH_DEBOUNCE_MS } from "./constants";
import type { FilterState, LevelFilter, SortColumn, SortConfig, TierFilter } from "./types";

interface UseLogFiltersParams {
  allEntries: ReadonlySignal<LogEntry[]>;
  restEntries: ReadonlySignal<LogEntry[]>;
  useLocalState?: boolean;
  appKey?: string;
}

interface UseLogFiltersResult {
  filtered: ReadonlySignal<LogEntry[]>;
  filterState: ReadonlySignal<FilterState>;
  livePaused: ReadonlySignal<boolean>;
  defaultTier: TierFilter;
  setLevel: (level: LevelFilter) => void;
  setTier: (tier: TierFilter) => void;
  setApp: (app: string) => void;
  setSearch: (search: string) => void;
  setFunc: (func: string) => void;
  setSort: (column: SortColumn) => void;
  resetSort: () => void;
  resetFilters: () => void;
}

function nextSortState(clicked: SortColumn, currentCol: SortColumn, currentAsc: boolean): SortConfig {
  if (clicked === "timestamp") {
    return { column: "timestamp", asc: currentCol === "timestamp" ? !currentAsc : false };
  }
  if (currentCol === clicked) {
    return { column: clicked, asc: !currentAsc };
  }
  return { column: clicked, asc: false };
}

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
        if (!aKey && !bKey) return 0;
        if (!aKey) return 1;
        if (!bKey) return -1;
        return aKey.localeCompare(bKey) * direction;
      }
      case "function":
        return a.func_name.localeCompare(b.func_name) * direction;
      case "message":
        return a.message.localeCompare(b.message) * direction;
    }
  });
}

export function useLogFilters({
  allEntries,
  restEntries,
  useLocalState = false,
  appKey,
}: UseLogFiltersParams): UseLogFiltersResult {
  const qp = useQueryParams();
  const qpRef = useRef(qp);
  qpRef.current = qp;

  const defaultTier: TierFilter = appKey ? "all" : "app";

  const localLevel = useSignal<LevelFilter>(DEFAULT_LEVEL);
  const localTier = useSignal<TierFilter>(defaultTier);
  const localApp = useSignal("");
  const localSearch = useSignal("");
  const localFunc = useSignal("");
  const localSortColumn = useSignal<SortColumn>("timestamp");
  const localSortAsc = useSignal(false);

  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    },
    [],
  );

  const filterState = computed<FilterState>(() => {
    if (useLocalState) {
      return {
        level: localLevel.value,
        tier: localTier.value,
        app: localApp.value,
        search: localSearch.value,
        func: localFunc.value,
        sort: { column: localSortColumn.value, asc: localSortAsc.value },
      };
    }

    const current = qpRef.current;
    const levelParam = current.get("level");
    const level: LevelFilter = levelParam === "all" ? "" : ((levelParam as LevelFilter) ?? DEFAULT_LEVEL);
    const tierRaw = current.get("tier");
    const tier: TierFilter = tierRaw === "all" || tierRaw === "framework" || tierRaw === "app" ? tierRaw : defaultTier;
    const app = current.get("app") ?? "";
    const search = current.get("search") ?? "";
    const func = current.get("fn") ?? "";
    const rawSort = current.get("sort") ?? "timestamp";
    const column = resolveSortColumn(rawSort);
    const sortAsc = current.get("dir") === "asc";

    return { level, tier, app, search, func, sort: { column, asc: sortAsc } };
  });

  const livePaused = computed(() => filterState.value.sort.column !== "timestamp");

  const filtered = computed<LogEntry[]>(() => {
    const paused = livePaused.value;
    const source = paused ? restEntries.value : allEntries.value;
    const { level, tier, app, search, func, sort } = filterState.value;

    let result = source;

    if (level) {
      const minIndex = LEVELS.indexOf(level as (typeof LEVELS)[number]);
      result = result.filter((e) => {
        const idx = LEVELS.indexOf(e.level as (typeof LEVELS)[number]);
        return idx >= minIndex;
      });
    }

    if (tier !== "all") {
      result = result.filter((e) => e.source_tier === tier);
    }

    if (app) {
      result = result.filter((e) => e.app_key === app);
    }

    if (search) {
      const lower = search.toLowerCase();
      result = result.filter(
        (e) => e.message.toLowerCase().includes(lower) || e.logger_name.toLowerCase().includes(lower),
      );
    }

    if (func) {
      const lower = func.toLowerCase();
      result = result.filter((e) => e.func_name.toLowerCase().includes(lower));
    }

    return sortEntries(result, sort.column, sort.asc);
  });

  function setLevel(level: LevelFilter) {
    if (useLocalState) {
      localLevel.value = level;
      return;
    }
    if (level === DEFAULT_LEVEL) {
      qpRef.current.set({ level: null });
    } else if (level === "") {
      qpRef.current.set({ level: "all" });
    } else {
      qpRef.current.set({ level });
    }
  }

  function setTier(tier: TierFilter) {
    if (tier !== "app") setApp("");
    if (useLocalState) {
      localTier.value = tier;
      return;
    }
    qpRef.current.set({ tier: tier === defaultTier ? null : tier });
  }

  function setApp(app: string) {
    if (useLocalState) {
      localApp.value = app;
      return;
    }
    qpRef.current.set({ app: app || null });
  }

  function setSearch(value: string) {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      if (useLocalState) {
        localSearch.value = value;
        return;
      }
      qpRef.current.set({ search: value || null });
    }, SEARCH_DEBOUNCE_MS);
  }

  function setFunc(func: string) {
    if (useLocalState) {
      localFunc.value = func;
      return;
    }
    qpRef.current.set({ fn: func || null });
  }

  function setSort(column: SortColumn) {
    if (useLocalState) {
      const next = nextSortState(column, localSortColumn.value, localSortAsc.value);
      localSortColumn.value = next.column;
      localSortAsc.value = next.asc;
      return;
    }
    const current = qpRef.current;
    const currentCol = resolveSortColumn(current.get("sort") ?? "timestamp");
    const currentAsc = current.get("dir") === "asc";
    const next = nextSortState(column, currentCol, currentAsc);
    const isDefault = next.column === "timestamp" && !next.asc;
    current.set({ sort: isDefault ? null : next.column, dir: next.asc ? "asc" : null });
  }

  function resetSort() {
    if (useLocalState) {
      localSortColumn.value = "timestamp";
      localSortAsc.value = false;
      return;
    }
    qpRef.current.set({ sort: null, dir: null });
  }

  function resetFilters() {
    setLevel(DEFAULT_LEVEL);
    setTier(defaultTier);
    setApp("");
    setFunc("");
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (useLocalState) {
      localSearch.value = "";
    } else {
      qpRef.current.set({ search: null });
    }
  }

  return {
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
  };
}
