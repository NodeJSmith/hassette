import { useCallback, useState } from "react";

import { BREAKPOINT_MOBILE, BREAKPOINT_TABLET, useMediaQuery } from "@/hooks/use-media-query";
import { getStoredValue, removeStoredValue, setStoredValue } from "@/utils/local-storage";

import {
  COLUMNS,
  DEFAULT_COLUMNS_APP,
  DEFAULT_COLUMNS_EXECUTION,
  DEFAULT_COLUMNS_GLOBAL,
  REQUIRED_COLUMNS,
} from "./constants";
import type { ColumnId, ViewContext } from "./types";

const STORAGE_VERSION = 1;
const STORAGE_KEY_PREFIX = "log-columns";

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

function isStoredColumnState(value: unknown): value is StoredColumnState {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as StoredColumnState).version === "number" &&
    Array.isArray((value as StoredColumnState).columns)
  );
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
  const stored = getStoredValue<StoredColumnState | null>(storageKey(context), null, isStoredColumnState);
  if (stored === null) return null;
  if (stored.version !== STORAGE_VERSION) {
    removeStoredValue(storageKey(context));
    return null;
  }
  const knownIds = new Set<string>(ALL_COLUMN_IDS);
  const validated = stored.columns.filter((id) => knownIds.has(id));
  for (const column of REQUIRED_COLUMNS) {
    if (!validated.includes(column)) validated.push(column);
  }
  if (validated.length === 0) return null;
  return validated;
}

function writeStored(context: ViewContext, columns: ColumnId[]): void {
  setStoredValue<StoredColumnState>(storageKey(context), { version: STORAGE_VERSION, columns });
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

  const [userColumns, setUserColumns] = useState<ColumnId[]>(() => readStored(context) ?? defaultColumns(context));

  const viewportHidden: ReadonlySet<ColumnId> = isMobile ? MOBILE_HIDDEN : isTablet ? TABLET_HIDDEN : NO_HIDDEN;

  const visibleColumns = userColumns.filter((id) => !viewportHidden.has(id));

  const toggle = useCallback(
    (id: ColumnId) => {
      setUserColumns((current) => {
        const next = current.includes(id)
          ? current.filter((c) => c !== id)
          : [...current, id].sort((a, b) => ALL_COLUMN_IDS.indexOf(a) - ALL_COLUMN_IDS.indexOf(b));
        writeStored(context, next);
        return next;
      });
    },
    [context],
  );

  const reset = useCallback(() => {
    const defaults = defaultColumns(context);
    setUserColumns(defaults);
    removeStoredValue(storageKey(context));
  }, [context]);

  return { visibleColumns, selectedColumns: userColumns, viewportHidden, toggle, reset };
}
