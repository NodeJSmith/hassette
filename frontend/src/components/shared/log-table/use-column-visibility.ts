import { useCallback } from "preact/hooks";
import { useSignal } from "../../../hooks/use-signal";
import { useMediaQuery, BREAKPOINT_MOBILE, BREAKPOINT_TABLET } from "../../../hooks/use-media-query";
import { useSubscribe } from "../../../hooks/use-subscribe";
import type { ColumnId, ViewContext } from "./types";
import { DEFAULT_COLUMNS_GLOBAL, DEFAULT_COLUMNS_APP, DEFAULT_COLUMNS_EXECUTION, COLUMNS } from "./constants";

const STORAGE_VERSION = 1;
const STORAGE_KEY_PREFIX = "hassette-log-columns";

interface StoredColumnState {
  version: number;
  columns: ColumnId[];
}

function storageKey(context: ViewContext): string {
  return `${STORAGE_KEY_PREFIX}-${context}`;
}

function defaultColumns(context: ViewContext): ColumnId[] {
  switch (context) {
    case "global": return DEFAULT_COLUMNS_GLOBAL;
    case "app": return DEFAULT_COLUMNS_APP;
    case "execution": return DEFAULT_COLUMNS_EXECUTION;
  }
}

function readStored(context: ViewContext): ColumnId[] | null {
  try {
    const raw = localStorage.getItem(storageKey(context));
    if (!raw) return null;
    const parsed: StoredColumnState = JSON.parse(raw);
    if (parsed.version !== STORAGE_VERSION) {
      localStorage.removeItem(storageKey(context));
      return null;
    }
    return parsed.columns;
  } catch {
    return null;
  }
}

function writeStored(context: ViewContext, columns: ColumnId[]): void {
  try {
    const state: StoredColumnState = { version: STORAGE_VERSION, columns };
    localStorage.setItem(storageKey(context), JSON.stringify(state));
  } catch {
    // localStorage unavailable — degrade silently
  }
}

const MOBILE_HIDDEN: ReadonlySet<ColumnId> = new Set(["app", "instance", "execution", "function", "module"]);
const TABLET_HIDDEN: ReadonlySet<ColumnId> = new Set(["module"]);
const ALL_COLUMN_IDS: ColumnId[] = COLUMNS.map((c) => c.id);

interface UseColumnVisibilityResult {
  visibleColumns: ColumnId[];
  isVisible: (id: ColumnId) => boolean;
  toggle: (id: ColumnId) => void;
  reset: () => void;
  allColumns: ColumnId[];
}

export function useColumnVisibility(context: ViewContext): UseColumnVisibilityResult {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const isTablet = useMediaQuery(BREAKPOINT_TABLET);

  const userColumns = useSignal<ColumnId[]>(readStored(context) ?? defaultColumns(context));
  useSubscribe(userColumns);

  const viewportHidden: ReadonlySet<ColumnId> = isMobile ? MOBILE_HIDDEN : isTablet ? TABLET_HIDDEN : new Set();

  const visibleColumns = userColumns.value.filter((id) => !viewportHidden.has(id));

  const isVisible = useCallback(
    (id: ColumnId) => userColumns.value.includes(id) && !viewportHidden.has(id),
    [userColumns.value, viewportHidden],
  );

  const toggle = useCallback(
    (id: ColumnId) => {
      const current = userColumns.value;
      const next = current.includes(id)
        ? current.filter((c) => c !== id)
        : [...current, id].sort((a, b) => ALL_COLUMN_IDS.indexOf(a) - ALL_COLUMN_IDS.indexOf(b));
      userColumns.value = next;
      writeStored(context, next);
    },
    [context],
  );

  const reset = useCallback(() => {
    const defaults = defaultColumns(context);
    userColumns.value = defaults;
    localStorage.removeItem(storageKey(context));
  }, [context]);

  return { visibleColumns, isVisible, toggle, reset, allColumns: ALL_COLUMN_IDS };
}
