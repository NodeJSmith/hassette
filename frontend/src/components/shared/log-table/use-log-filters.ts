import { computed, type ReadonlySignal } from "@preact/signals";
import { useEffect, useMemo, useRef } from "preact/hooks";

import type { LogEntry } from "../../../api/endpoints";
import { useQueryParams } from "../../../hooks/use-query-params";
import { useSignal } from "../../../hooks/use-signal";
import { ALL_LEVELS, DEFAULT_LEVEL, LEVEL_INDEX, LEVELS, resolveSortKey, SEARCH_DEBOUNCE_MS } from "./constants";
import type { FilterState, LevelFilter, LogSortState, TierFilter } from "./types";

interface UseLogFiltersParams {
  allEntries: LogEntry[];
  restEntries: LogEntry[];
  useLocalState?: boolean;
  appKey?: string;
}

interface UseLogFiltersResult {
  filtered: LogEntry[];
  filterState: ReadonlySignal<FilterState>;
  livePaused: ReadonlySignal<boolean>;
  defaultTier: TierFilter;
  setLevel: (level: LevelFilter) => void;
  setTier: (tier: TierFilter) => void;
  setApp: (app: string) => void;
  setSearch: (search: string) => void;
  setFunc: (func: string) => void;
  setSort: (sort: LogSortState) => void;
  resetSort: () => void;
  resetFilters: () => void;
}

export function sortEntries(entries: readonly LogEntry[], sort: LogSortState): LogEntry[] {
  const direction = sort.dir === "asc" ? 1 : -1;
  return [...entries].sort((a, b) => {
    switch (sort.key) {
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
        return (a.func_name ?? "").localeCompare(b.func_name ?? "") * direction;
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
  const localSort = useSignal<LogSortState>({ key: "timestamp", dir: "desc" });

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
        sort: localSort.value,
      };
    }

    const current = qpRef.current;
    const levelParam = current.get("level");
    const level: LevelFilter = levelParam === "all" ? ALL_LEVELS : ((levelParam as LevelFilter) ?? DEFAULT_LEVEL);
    const tierRaw = current.get("tier");
    const tier: TierFilter = tierRaw === "all" || tierRaw === "framework" || tierRaw === "app" ? tierRaw : defaultTier;
    const app = current.get("app") ?? "";
    const search = current.get("search") ?? "";
    const func = current.get("func") ?? current.get("fn") ?? "";
    const rawSort = current.get("sort") ?? "timestamp";
    const key = resolveSortKey(rawSort);
    const dir = current.get("dir") === "asc" ? "asc" : "desc";

    return { level, tier, app, search, func, sort: { key, dir } };
  });

  const livePaused = computed(() => filterState.value.sort.key !== "timestamp");

  const paused = livePaused.value;
  const { level, tier, app, search, func, sort } = filterState.value;
  const source = paused ? restEntries : allEntries;

  const filtered = useMemo<LogEntry[]>(() => {
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
      result = result.filter((e) => (e.func_name ?? "").toLowerCase().includes(lower));
    }

    return sortEntries(result, sort);
  }, [source, level, tier, app, search, func, sort.key, sort.dir]);

  function setLevel(level: LevelFilter) {
    if (useLocalState) {
      localLevel.value = level;
      return;
    }
    if (level === DEFAULT_LEVEL) {
      qpRef.current.set({ level: null });
    } else if (level === ALL_LEVELS) {
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
    qpRef.current.set({ func: func || null, fn: null });
  }

  function setSort(next: LogSortState) {
    if (useLocalState) {
      localSort.value = next;
      return;
    }
    const isDefault = next.key === "timestamp" && next.dir === "desc";
    qpRef.current.set({ sort: isDefault ? null : next.key, dir: next.dir === "asc" ? "asc" : null });
  }

  function resetSort() {
    if (useLocalState) {
      localSort.value = { key: "timestamp", dir: "desc" };
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
