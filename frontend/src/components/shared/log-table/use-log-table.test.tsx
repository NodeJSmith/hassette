import { signal } from "@preact/signals";
import { act, renderHook } from "@testing-library/preact";
import type { ComponentChildren } from "preact";
import { h } from "preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "../../../api/endpoints";
import { AppStateContext } from "../../../state/context";
import { createAppState } from "../../../state/create-app-state";
import { useLogTable } from "./use-log-table";

// ---------------------------------------------------------------------------
// Module mocks
//
// vi.mock() calls are hoisted by Vitest to run before all other module-level
// code, but the factory *body* executes at import time — after module-scope
// variable declarations have been evaluated. The inner hook functions run at
// call time (inside renderHook), so they safely read the `mock*` variables
// declared below. We use object getter syntax so each property is read lazily
// at call time rather than captured once at factory evaluation.
// ---------------------------------------------------------------------------

vi.mock("./use-log-data", () => ({
  useLogData: () => ({
    allEntries: [],
    restEntries: [],
    // Reading mockLoading.value here subscribes to the signal during render,
    // so Preact re-renders the hook when mockLoading changes.
    get loading() {
      return mockLoading.value;
    },
  }),
}));

vi.mock("./use-log-filters", () => ({
  useLogFilters: () => ({
    get filtered() {
      return mockFiltered.value;
    },
    get filterState() {
      return mockFilterState;
    },
    livePaused: signal(false),
    defaultTier: "all",
    get setLevel() {
      return mockSetLevel;
    },
    get setTier() {
      return mockSetTier;
    },
    get setApp() {
      return mockSetApp;
    },
    get setSearch() {
      return mockSetSearch;
    },
    get setFunc() {
      return mockSetFunc;
    },
    get setSort() {
      return mockSetSort;
    },
    get resetSort() {
      return mockResetSort;
    },
    get resetFilters() {
      return mockResetFilters;
    },
  }),
}));

vi.mock("./use-column-visibility", () => ({
  useColumnVisibility: () => ({
    visibleColumns: ["level", "timestamp", "message"],
    selectedColumns: ["level", "timestamp", "message"],
    viewportHidden: new Set(),
    toggle: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: vi.fn(() => false),
  BREAKPOINT_MOBILE: 768,
}));

vi.mock("wouter", () => ({
  useSearch: () => "",
  useLocation: () => ["/", vi.fn()],
}));

// ---------------------------------------------------------------------------
// Shared mutable signals — initialized at module scope, reset per test.
// The mock factories above close over these bindings via getter functions;
// because getters are evaluated at call time (not at factory evaluation time),
// the signals are guaranteed to be initialized before any test reads them.
// ---------------------------------------------------------------------------

const mockFilterState = signal<{
  level: string;
  tier: string;
  app: string;
  func: string;
  search: string;
  sort: { column: string; asc: boolean };
}>({
  level: "INFO",
  tier: "all",
  app: "",
  func: "",
  search: "",
  sort: { column: "timestamp", asc: false },
});

const mockFiltered = signal<LogEntry[]>([]);
// mockLoading is a signal so the useLogData mock can return mockLoading.value
// (subscribing to it during render) and tests can mutate it to trigger re-renders.
const mockLoading = signal(false);

const mockSetLevel = vi.fn();
const mockSetTier = vi.fn();
const mockSetApp = vi.fn();
const mockSetSearch = vi.fn();
const mockSetFunc = vi.fn();
const mockSetSort = vi.fn();
const mockResetSort = vi.fn();
const mockResetFilters = vi.fn();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapper() {
  const state = createAppState();
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

function renderUseLogTable(params: Parameters<typeof useLogTable>[0] = {}) {
  return renderHook(() => useLogTable(params), { wrapper: createWrapper() });
}

function makeEntry(seq: number): LogEntry {
  return {
    seq,
    timestamp: 1000 + seq,
    level: "INFO",
    logger_name: "test",
    func_name: "f",
    lineno: 1,
    message: `msg-${seq}`,
    exc_info: null,
    app_key: null,
    source_tier: "app",
  };
}

beforeEach(() => {
  mockFilterState.value = {
    level: "INFO",
    tier: "all",
    app: "",
    func: "",
    search: "",
    sort: { column: "timestamp", asc: false },
  };
  mockFiltered.value = [];
  mockLoading.value = false;
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useLogTable — columnFilters", () => {
  it("always includes 'level' filter", () => {
    const { result } = renderUseLogTable();
    expect(result.current.columnFilters).toHaveProperty("level");
  });

  it("always includes 'function' filter", () => {
    const { result } = renderUseLogTable();
    expect(result.current.columnFilters).toHaveProperty("function");
  });

  it("includes 'app' filter when appKey is not provided", () => {
    const { result } = renderUseLogTable({ appKey: undefined });
    expect(result.current.columnFilters).toHaveProperty("app");
  });

  it("does NOT include 'app' filter when appKey is provided", () => {
    const { result } = renderUseLogTable({ appKey: "my_app" });
    expect(result.current.columnFilters).not.toHaveProperty("app");
  });

  it("level filter is active when level differs from default (INFO)", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, level: "ERROR" };
    });
    const { result } = renderUseLogTable();
    expect(result.current.columnFilters.level?.active).toBe(true);
  });

  it("level filter is inactive when level equals default (INFO)", () => {
    const { result } = renderUseLogTable();
    expect(result.current.columnFilters.level?.active).toBe(false);
  });

  it("function filter is active when func is non-empty", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, func: "on_motion" };
    });
    const { result } = renderUseLogTable();
    expect(result.current.columnFilters.function?.active).toBe(true);
  });

  it("function filter is inactive when func is empty", () => {
    const { result } = renderUseLogTable();
    expect(result.current.columnFilters.function?.active).toBe(false);
  });

  it("app filter is active when tier differs from defaultTier", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, tier: "app" };
    });
    const { result } = renderUseLogTable({ appKey: undefined });
    expect(result.current.columnFilters.app?.active).toBe(true);
  });

  it("app filter is active when app is non-empty", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, app: "my_app" };
    });
    const { result } = renderUseLogTable({ appKey: undefined });
    expect(result.current.columnFilters.app?.active).toBe(true);
  });

  it("app filter content is present when tier is not 'framework' and appKeys are provided", () => {
    const { result } = renderUseLogTable({ appKey: undefined, appKeys: ["app_a", "app_b"] });
    expect(result.current.columnFilters.app?.content).toBeTruthy();
  });
});

describe("useLogTable — hasActiveFilter", () => {
  it("is false when all filters are at their defaults", () => {
    const { result } = renderUseLogTable();
    expect(result.current.hasActiveFilter).toBe(false);
  });

  it("is true when level differs from default", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, level: "WARNING" };
    });
    const { result } = renderUseLogTable();
    expect(result.current.hasActiveFilter).toBe(true);
  });

  it("is true when app is non-empty", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, app: "my_app" };
    });
    const { result } = renderUseLogTable();
    expect(result.current.hasActiveFilter).toBe(true);
  });

  it("is true when func is non-empty", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, func: "my_handler" };
    });
    const { result } = renderUseLogTable();
    expect(result.current.hasActiveFilter).toBe(true);
  });

  it("is true when search is non-empty", () => {
    act(() => {
      mockFilterState.value = { ...mockFilterState.value, search: "error" };
    });
    const { result } = renderUseLogTable();
    expect(result.current.hasActiveFilter).toBe(true);
  });
});

describe("useLogTable — countLabel", () => {
  it("shows '0 entries' when filtered list is empty", () => {
    const { result } = renderUseLogTable();
    expect(result.current.countLabel).toBe("0 entries");
  });

  it("shows '1 entry' for a single result", () => {
    act(() => {
      mockFiltered.value = [makeEntry(1)];
    });
    const { result } = renderUseLogTable();
    expect(result.current.countLabel).toBe("1 entry");
  });

  it("shows '3 entries' for multiple results", () => {
    act(() => {
      mockFiltered.value = [makeEntry(1), makeEntry(2), makeEntry(3)];
    });
    const { result } = renderUseLogTable();
    expect(result.current.countLabel).toBe("3 entries");
  });
});

describe("useLogTable — handleRowClick / selectedKey", () => {
  it("sets selectedKey when a row is clicked", () => {
    const { result } = renderUseLogTable();
    act(() => {
      result.current.tableProps.onRowClick(makeEntry(5));
    });
    // rowKey for seq=5, timestamp=1005 → "1005-5"
    expect(result.current.tableProps.selectedKey).toBe("1005-5");
  });

  it("toggles selectedKey to null when the same row is clicked again", () => {
    const { result } = renderUseLogTable();
    const entry = makeEntry(5);
    act(() => {
      result.current.tableProps.onRowClick(entry);
    });
    act(() => {
      result.current.tableProps.onRowClick(entry);
    });
    expect(result.current.tableProps.selectedKey).toBeNull();
  });
});

describe("useLogTable — handleDrawerClose", () => {
  it("sets selectedKey to null when drawer is closed", () => {
    const { result } = renderUseLogTable();
    act(() => {
      result.current.tableProps.onRowClick(makeEntry(7));
    });
    expect(result.current.tableProps.selectedKey).not.toBeNull();

    act(() => {
      result.current.drawerProps.onClose();
    });
    expect(result.current.tableProps.selectedKey).toBeNull();
  });
});

describe("useLogTable — isEmpty / isLoading", () => {
  it("isEmpty is true when not loading and filtered list is empty", () => {
    const { result } = renderUseLogTable();
    expect(result.current.isEmpty).toBe(true);
  });

  it("isEmpty is false when filtered list has entries", () => {
    act(() => {
      mockFiltered.value = [makeEntry(1)];
    });
    const { result } = renderUseLogTable();
    expect(result.current.isEmpty).toBe(false);
  });

  it("isEmpty is false when loading (even if entries are empty)", () => {
    act(() => {
      mockLoading.value = true;
    });
    const { result } = renderUseLogTable();
    expect(result.current.isEmpty).toBe(false);
  });

  it("isLoading reflects the loading value", () => {
    const { result } = renderUseLogTable();
    expect(result.current.isLoading).toBe(false);

    act(() => {
      mockLoading.value = true;
    });
    expect(result.current.isLoading).toBe(true);
  });
});
