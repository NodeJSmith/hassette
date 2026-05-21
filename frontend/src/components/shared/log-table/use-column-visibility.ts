import { useCallback } from "preact/hooks";

import { BREAKPOINT_MOBILE, BREAKPOINT_TABLET, useMediaQuery } from "../../../hooks/use-media-query";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import {
  COLUMNS,
  DEFAULT_COLUMNS_APP,
  DEFAULT_COLUMNS_EXECUTION,
  DEFAULT_COLUMNS_GLOBAL,
  REQUIRED_COLUMNS,
} from "./constants";
import type { ColumnId, ViewContext } from "./types";

const STORAGE_VERSION = 1;
const STORAGE_KEY_PREFIX = "hassette-log-columns";

interface StoredColumnState {
  version: number;
  columns: ColumnId[];
}

const ALL_COLUMN_IDS: ColumnId[] = COLUMNS.map((c) => c.id);
const MOBILE_HIDDEN: ReadonlySet<ColumnId> = new Set(["app", "instance", "execution", "function", "module"]);
const TABLET_HIDDEN: ReadonlySet<ColumnId> = new Set(["module"]);
const NO_HIDDEN: ReadonlySet<ColumnId> = new Set();

function storageKey(context: ViewContext): string {
  return `${STORAGE_KEY_PREFIX}-${context}`;
}

function defaultColumns(context: ViewContext): ColumnId[] {
  switch (context) {
    case "global":
      return DEFAULT_COLUMNS_GLOBAL;
    case "app":
      return DEFAULT_COLUMNS_APP;
    case "execution":
      return DEFAULT_COLUMNS_EXECUTION;
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
    const knownIds = new Set<string>(ALL_COLUMN_IDS);
    const validated = parsed.columns.filter((id) => knownIds.has(id));
    for (const req of REQUIRED_COLUMNS) {
      if (!validated.includes(req)) validated.push(req);
    }
    if (validated.length === 0) return null;
    return validated;
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

interface UseColumnVisibilityResult {
  visibleColumns: ColumnId[];
  selectedColumns: ColumnId[];
  viewportHidden: ReadonlySet<ColumnId>;
  toggle: (id: ColumnId) => void;
  reset: () => void;
}

export function useColumnVisibility(context: ViewContext): UseColumnVisibilityResult {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const isTablet = useMediaQuery(BREAKPOINT_TABLET);

  const userColumns = useSignal<ColumnId[]>(readStored(context) ?? defaultColumns(context));
  useSubscribe(userColumns);

  const viewportHidden: ReadonlySet<ColumnId> = isMobile ? MOBILE_HIDDEN : isTablet ? TABLET_HIDDEN : NO_HIDDEN;

  const visibleColumns = userColumns.value.filter((id) => !viewportHidden.has(id));

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

  return { visibleColumns, selectedColumns: userColumns.value, viewportHidden, toggle, reset };
}
