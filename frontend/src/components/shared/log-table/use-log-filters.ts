import { computed, type ReadonlySignal } from "@preact/signals";
import { useEffect, useMemo, useRef } from "preact/hooks";

import type { LogEntry } from "../../../api/endpoints";
import { useQueryParams } from "../../../hooks/use-query-params";
import { useSignal } from "../../../hooks/use-signal";
import {
  ALL_LEVELS,
  DEFAULT_LEVEL,
  DEFAULT_SORT,
  LEVEL_INDEX,
  LEVELS,
  RENDER_CAP,
  resolveSortKey,
  SEARCH_DEBOUNCE_MS,
} from "./constants";
import type { FilterState, LevelFilter, LogSortState, TierFilter } from "./types";

interface UseLogFiltersParams {
  allEntries: LogEntry[];
  restEntries: LogEntry[];
  useLocalState?: boolean;
  appKey?: string;
  executionId?: string | null;
}

interface UseLogFiltersResult {
  visibleEntries: LogEntry[];
  totalFilteredCount: number;
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

export interface FilteredLogEntriesResult {
  entries: LogEntry[];
  count: number;
}

export function filterLogEntries(
  source: readonly LogEntry[],
  { level, tier, app, search, func, sort }: FilterState,
  visibleLimit = RENDER_CAP,
): FilteredLogEntriesResult {
  const lowerSearch = search.toLowerCase();
  const lowerFunc = func.toLowerCase();
  const minLevelIndex = level ? LEVELS.indexOf(level as (typeof LEVELS)[number]) : -1;
  let count = 0;

  const matches = (e: LogEntry): boolean => {
    if (level) {
      const idx = LEVELS.indexOf(e.level as (typeof LEVELS)[number]);
      if (idx < minLevelIndex) return false;
    }
    if (tier !== "all" && e.source_tier !== tier) return false;
    if (app && e.app_key !== app) return false;
    if (
      lowerSearch &&
      !e.message.toLowerCase().includes(lowerSearch) &&
      !e.logger_name.toLowerCase().includes(lowerSearch)
    ) {
      return false;
    }
    if (lowerFunc && !(e.func_name ?? "").toLowerCase().includes(lowerFunc)) return false;
    return true;
  };

  // useLogData provides rows in timestamp DESC order: REST comes from
  // /logs/recent ordered DESC, and live WS rows are reversed before merge.
  // Preserve that order for the hot live path instead of re-sorting every batch.
  const keepTimestampSourceOrder = sort.key === "timestamp";
  const visibleTimestampDescEntries: LogEntry[] = [];
  const sortableEntries: LogEntry[] = [];
  for (const entry of source) {
    if (!matches(entry)) continue;
    count++;

    if (keepTimestampSourceOrder && sort.dir === "desc") {
      if (visibleTimestampDescEntries.length < visibleLimit) visibleTimestampDescEntries.push(entry);
      continue;
    }

    sortableEntries.push(entry);
  }

  if (keepTimestampSourceOrder) {
    return {
      entries: sort.dir === "asc" ? sortableEntries.reverse().slice(0, visibleLimit) : visibleTimestampDescEntries,
      count,
    };
  }

  return {
    entries: sortEntries(sortableEntries, sort).slice(0, visibleLimit),
    count,
  };
}

export function useLogFilters({
  allEntries,
  restEntries,
  useLocalState = false,
  appKey,
  executionId,
}: UseLogFiltersParams): UseLogFiltersResult {
  const qp = useQueryParams();
  const qpRef = useRef(qp);
  qpRef.current = qp;

  // An execution_id already scopes rows to a single execution, whose logs can span
  // both tiers (its app logs plus framework diagnostics about it). Tier-filtering there
  // would only hide some of the execution's own logs, so default to "all" — same as appKey.
  const defaultTier: TierFilter = appKey || executionId ? "all" : "app";

  const localLevel = useSignal<LevelFilter>(DEFAULT_LEVEL);
  const localTier = useSignal<TierFilter>(defaultTier);
  const localApp = useSignal("");
  const localSearch = useSignal("");
  const localFunc = useSignal("");
  const localSort = useSignal<LogSortState>(DEFAULT_SORT);

  // localTier is seeded from defaultTier once at mount, but defaultTier is reactive: on the
  // global /logs page, adding execution_id to the URL flips useLocalState true and recomputes
  // defaultTier "app"->"all" without remounting. Re-sync so a stale "app" doesn't keep hiding
  // framework rows. Clears the app filter too when leaving the "app" tier.
  useEffect(() => {
    if (!useLocalState) return;
    localTier.value = defaultTier;
    if (defaultTier !== "app") localApp.value = "";
  }, [useLocalState, defaultTier]);

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

  const filtered = useMemo<FilteredLogEntriesResult>(
    () => filterLogEntries(source, { level, tier, app, search, func, sort }),
    [source, level, tier, app, search, func, sort.key, sort.dir],
  );

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
    const isDefault = next.key === DEFAULT_SORT.key && next.dir === DEFAULT_SORT.dir;
    qpRef.current.set({ sort: isDefault ? null : next.key, dir: next.dir === "asc" ? "asc" : null });
  }

  function resetSort() {
    if (useLocalState) {
      localSort.value = DEFAULT_SORT;
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
    visibleEntries: filtered.entries,
    totalFilteredCount: filtered.count,
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
