import { act, renderHook } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "../../../api/endpoints";
import { DEFAULT_SORT, RENDER_CAP, SEARCH_DEBOUNCE_MS } from "./constants";
import type { FilterState, LevelFilter } from "./types";
import { filterLogEntries, useLogFilters } from "./use-log-filters";

// --- wouter mock (same pattern as use-query-params.test.ts) ---
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/logs", mockNavigate],
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function entry(overrides: Partial<LogEntry> = {}): LogEntry {
  return {
    seq: 1,
    timestamp: 1000,
    level: "INFO",
    logger_name: "hassette.apps.my_app",
    func_name: "on_event",
    lineno: 42,
    message: "hello world",
    exc_info: null,
    app_key: "my_app",
    source_tier: "app",
    ...overrides,
  } as LogEntry;
}

interface RenderLocalProps {
  entries: LogEntry[];
  rest: LogEntry[];
  appKey?: string;
  executionId?: string | null;
}

/** Render useLogFilters with local state (no URL). Uses initialProps for rerender support. */
function renderLocal(entries: LogEntry[] = [], rest: LogEntry[] = [], appKey?: string, executionId?: string | null) {
  const hook = renderHook(
    ({ entries: allEntries, rest: restEntries, appKey: ak, executionId: eid }: RenderLocalProps) =>
      useLogFilters({ allEntries, restEntries, useLocalState: true, appKey: ak, executionId: eid }),
    { initialProps: { entries, rest, appKey, executionId } },
  );
  return { hook };
}

/** Render useLogFilters in URL mode (reads/writes mockSearch). */
function renderUrl(entries: LogEntry[] = [], rest: LogEntry[] = [], appKey?: string, executionId?: string | null) {
  const hook = renderHook(
    ({ entries: allEntries, rest: restEntries, appKey: ak, executionId: eid }: RenderLocalProps) =>
      useLogFilters({ allEntries, restEntries, useLocalState: false, appKey: ak, executionId: eid }),
    { initialProps: { entries, rest, appKey, executionId } },
  );
  return { hook };
}

function filterState(overrides: Partial<FilterState> = {}): FilterState {
  return {
    level: "INFO",
    tier: "app",
    app: "",
    search: "",
    func: "",
    sort: DEFAULT_SORT,
    ...overrides,
  };
}

function waitForSearchDebounce(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 50));
}

beforeEach(() => {
  mockSearch = "";
  mockNavigate.mockReset();
});

describe("filterLogEntries", () => {
  it("keeps an exact filtered count while returning only the render-capped rows", () => {
    const entries = Array.from({ length: RENDER_CAP + 25 }, (_, i) =>
      entry({ seq: i, timestamp: 1000 + (RENDER_CAP + 24 - i), message: `row-${i}` }),
    );

    const result = filterLogEntries(entries, filterState());

    expect(result.count).toBe(RENDER_CAP + 25);
    expect(result.entries).toHaveLength(RENDER_CAP);
    expect(result.entries[0].message).toBe("row-0");
    expect(result.entries[result.entries.length - 1]?.message).toBe(`row-${RENDER_CAP - 1}`);
  });

  it("preserves timestamp-desc source order for the default hot path", () => {
    const entries = [
      entry({ timestamp: 2000, message: "source-first" }),
      entry({ timestamp: 3000, message: "source-second" }),
      entry({ timestamp: 1000, message: "source-third" }),
    ];

    const result = filterLogEntries(entries, filterState());

    expect(result.entries.map((e) => e.message)).toEqual(["source-first", "source-second", "source-third"]);
  });

  it("reverses timestamp-desc source order for timestamp-asc sort", () => {
    const entries = [
      entry({ timestamp: 3000, message: "newest" }),
      entry({ timestamp: 2000, message: "middle" }),
      entry({ timestamp: 1000, message: "oldest" }),
    ];

    const result = filterLogEntries(entries, filterState({ sort: { key: "timestamp", dir: "asc" } }));

    expect(result.entries.map((e) => e.message)).toEqual(["oldest", "middle", "newest"]);
  });
});

// ---------------------------------------------------------------------------
// defaultTier
// ---------------------------------------------------------------------------

describe("defaultTier", () => {
  it('is "app" when no appKey is provided', () => {
    const { hook } = renderLocal();
    expect(hook.result.current.defaultTier).toBe("app");
  });

  it('is "all" when appKey is provided', () => {
    const { hook } = renderLocal([], [], "my_app");
    expect(hook.result.current.defaultTier).toBe("all");
  });

  it('is "all" when executionId is provided (no appKey)', () => {
    const { hook } = renderLocal([], [], undefined, "exec-1");
    expect(hook.result.current.defaultTier).toBe("all");
  });
});

// ---------------------------------------------------------------------------
// Level filtering
// ---------------------------------------------------------------------------

describe("level filtering", () => {
  it("defaults to INFO level and filters out DEBUG entries", () => {
    const entries = [
      entry({ level: "DEBUG", message: "debug" }),
      entry({ level: "INFO", message: "info" }),
      entry({ level: "WARNING", message: "warn" }),
    ];
    const { hook } = renderLocal(entries);
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).not.toContain("debug");
    expect(messages).toContain("info");
    expect(messages).toContain("warn");
  });

  it('shows all levels when set to empty string ("all levels")', () => {
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "INFO", message: "info" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setLevel("" as LevelFilter));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("debug");
    expect(messages).toContain("info");
  });

  it("filters by minimum level: WARNING+ excludes DEBUG and INFO", () => {
    const entries = [
      entry({ level: "DEBUG", message: "debug" }),
      entry({ level: "INFO", message: "info" }),
      entry({ level: "WARNING", message: "warn" }),
      entry({ level: "ERROR", message: "error" }),
      entry({ level: "CRITICAL", message: "crit" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setLevel("WARNING"));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).not.toContain("debug");
    expect(messages).not.toContain("info");
    expect(messages).toContain("warn");
    expect(messages).toContain("error");
    expect(messages).toContain("crit");
  });

  it("CRITICAL only shows CRITICAL entries", () => {
    const entries = [entry({ level: "ERROR", message: "error" }), entry({ level: "CRITICAL", message: "crit" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setLevel("CRITICAL"));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toEqual(["crit"]);
  });
});

// ---------------------------------------------------------------------------
// Tier filtering
// ---------------------------------------------------------------------------

describe("tier filtering", () => {
  it('defaults to "app" tier (no appKey) and excludes framework entries', () => {
    const entries = [
      entry({ source_tier: "app", message: "from app" }),
      entry({ source_tier: "framework", message: "from framework" }),
    ];
    const { hook } = renderLocal(entries);
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("from app");
    expect(messages).not.toContain("from framework");
  });

  it('"all" tier shows both app and framework entries', () => {
    const entries = [
      entry({ source_tier: "app", message: "from app" }),
      entry({ source_tier: "framework", message: "from framework" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setTier("all"));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("from app");
    expect(messages).toContain("from framework");
  });

  it('"framework" tier shows only framework entries', () => {
    const entries = [
      entry({ source_tier: "app", message: "from app" }),
      entry({ source_tier: "framework", message: "from framework" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setTier("framework"));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).not.toContain("from app");
    expect(messages).toContain("from framework");
  });

  it("defaults to showing framework entries when executionId is provided", () => {
    // An execution_id scopes rows to one execution; its logs can be framework-tier
    // (e.g. CommandExecutor timeout warnings) even when the execution itself is app-tier.
    const entries = [
      entry({ source_tier: "app", message: "from app" }),
      entry({ source_tier: "framework", message: "from framework" }),
    ];
    const { hook } = renderLocal(entries, [], undefined, "exec-1");
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("from app");
    expect(messages).toContain("from framework");
  });

  it('defaults to "all" when appKey is provided', () => {
    const entries = [entry({ source_tier: "framework", message: "from framework" })];
    const { hook } = renderLocal(entries, [], "my_app");
    // "all" tier means framework entries pass through
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("from framework");
  });

  it("re-syncs tier to default when executionId appears after mount (local state)", () => {
    // Regression: on the global /logs page, useLocalState flips true once execution_id
    // is added to the URL in-place (same mounted hook). defaultTier recomputes "app"->"all",
    // but a stale localTier="app" would keep hiding framework rows — the exact bug this PR fixes.
    const entries = [
      entry({ source_tier: "app", message: "from app" }),
      entry({ source_tier: "framework", message: "from framework" }),
    ];
    const { hook } = renderLocal(entries, [], undefined, null);
    // No execution scope yet: tier defaults to "app", framework hidden.
    expect(hook.result.current.visibleEntries.map((e) => e.message)).not.toContain("from framework");

    // Execution scope applied to the same mounted hook.
    act(() => hook.rerender({ entries, rest: [], appKey: undefined, executionId: "exec-1" }));

    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("from app");
    expect(messages).toContain("from framework");
  });

  it("preserves a manual tier selection across same-scope rerenders (exec -> exec)", () => {
    // The re-sync must fire only when defaultTier actually flips (scope gained/lost), not on
    // every prop change. Navigating between two executions keeps defaultTier "all", so a user's
    // explicit "framework" choice must survive.
    const entries = [
      entry({ source_tier: "app", message: "from app" }),
      entry({ source_tier: "framework", message: "from framework" }),
    ];
    const { hook } = renderLocal(entries, [], undefined, "exec-1");
    act(() => hook.result.current.setTier("framework"));
    expect(hook.result.current.visibleEntries.map((e) => e.message)).toEqual(["from framework"]);

    // Same scope kind (still execution-scoped), different id — defaultTier stays "all".
    act(() => hook.rerender({ entries, rest: [], appKey: undefined, executionId: "exec-2" }));

    expect(hook.result.current.visibleEntries.map((e) => e.message)).toEqual(["from framework"]);
  });

  it("clears app filter when tier is changed away from app", () => {
    const entries = [
      entry({ app_key: "alpha", source_tier: "app", message: "alpha" }),
      entry({ app_key: "beta", source_tier: "app", message: "beta" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setApp("alpha"));
    expect(hook.result.current.visibleEntries.map((e) => e.message)).toEqual(["alpha"]);
    // Changing to "all" should reset app filter
    act(() => hook.result.current.setTier("all"));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("alpha");
    expect(messages).toContain("beta");
  });
});

// ---------------------------------------------------------------------------
// App filtering
// ---------------------------------------------------------------------------

describe("app filtering", () => {
  it("filters entries to only matching app_key", () => {
    const entries = [
      entry({ app_key: "alpha", message: "alpha msg", source_tier: "app" }),
      entry({ app_key: "beta", message: "beta msg", source_tier: "app" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => {
      hook.result.current.setTier("all");
      hook.result.current.setApp("alpha");
    });
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toEqual(["alpha msg"]);
  });
});

// ---------------------------------------------------------------------------
// Search filtering
// ---------------------------------------------------------------------------

describe("search filtering", () => {
  it("matches message case-insensitively", async () => {
    const entries = [
      entry({ message: "Hello World", logger_name: "logger" }),
      entry({ message: "unrelated", logger_name: "other" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setSearch("hello"));
    await waitForSearchDebounce();
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("Hello World");
    expect(messages).not.toContain("unrelated");
  });

  it("matches logger_name case-insensitively", async () => {
    const entries = [
      entry({ message: "msg", logger_name: "hassette.apps.my_app" }),
      entry({ message: "other", logger_name: "hassette.core.bus" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setSearch("MY_APP"));
    await waitForSearchDebounce();
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("msg");
    expect(messages).not.toContain("other");
  });
});

// ---------------------------------------------------------------------------
// Function filtering
// ---------------------------------------------------------------------------

describe("func filtering", () => {
  it("filters by func_name case-insensitively", () => {
    const entries = [
      entry({ func_name: "on_state_change", message: "a" }),
      entry({ func_name: "handle_event", message: "b" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setFunc("ON_STATE"));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("a");
    expect(messages).not.toContain("b");
  });
});

// ---------------------------------------------------------------------------
// Sort
// ---------------------------------------------------------------------------

describe("sort", () => {
  it("defaults to timestamp descending", () => {
    const entries = [
      entry({ timestamp: 3000, message: "new" }),
      entry({ timestamp: 2000, message: "mid" }),
      entry({ timestamp: 1000, message: "old" }),
    ];
    const { hook } = renderLocal(entries);
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toEqual(["new", "mid", "old"]);
  });

  it("applies sort state directly", () => {
    const entries = [entry({ timestamp: 3000, message: "new" }), entry({ timestamp: 1000, message: "old" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setSort({ key: "timestamp", dir: "asc" }));
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toEqual(["old", "new"]);
  });

  it("applies a different sort column", () => {
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "CRITICAL", message: "crit" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setLevel(""));
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    const { sort } = hook.result.current.filterState.value;
    expect(sort.key).toBe("level");
    expect(sort.dir).toBe("desc");
  });

  it("can toggle direction on same column", () => {
    const { hook } = renderLocal();
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    act(() => hook.result.current.setSort({ key: "level", dir: "asc" }));
    const { sort } = hook.result.current.filterState.value;
    expect(sort.key).toBe("level");
    expect(sort.dir).toBe("asc");
  });

  it("resets to timestamp desc on resetSort", () => {
    const { hook } = renderLocal();
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    act(() => hook.result.current.resetSort());
    const { sort } = hook.result.current.filterState.value;
    expect(sort.key).toBe("timestamp");
    expect(sort.dir).toBe("desc");
  });
});

// ---------------------------------------------------------------------------
// Live pause
// ---------------------------------------------------------------------------

describe("livePaused", () => {
  it("is false when sorting by timestamp", () => {
    const { hook } = renderLocal();
    expect(hook.result.current.livePaused.value).toBe(false);
  });

  it("is true when sorting by any non-timestamp column", () => {
    const { hook } = renderLocal();
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(hook.result.current.livePaused.value).toBe(true);
  });

  it("reads from restEntries when paused", () => {
    const live = [entry({ message: "live" })];
    const rest = [entry({ message: "rest" })];
    const { hook } = renderLocal(live, rest);

    act(() => {
      hook.result.current.setSort({ key: "level", dir: "desc" });
    });

    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("rest");
    expect(messages).not.toContain("live");
  });

  it("reads from allEntries when not paused", () => {
    const live = [entry({ message: "live" })];
    const rest = [entry({ message: "rest" })];
    const { hook } = renderLocal(live, rest);

    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("live");
    expect(messages).not.toContain("rest");
  });

  it("switches to allEntries when paused is cleared", () => {
    const live = [entry({ message: "live" })];
    const rest = [entry({ message: "rest" })];
    const { hook } = renderLocal(live, rest);

    // Pause by sorting by level
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(hook.result.current.visibleEntries.map((e) => e.message)).toContain("rest");

    // Unpause by resetting sort
    act(() => hook.result.current.resetSort());
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).toContain("live");
    expect(messages).not.toContain("rest");
  });
});

// ---------------------------------------------------------------------------
// resetFilters
// ---------------------------------------------------------------------------

describe("resetFilters", () => {
  it("resets level, tier, app, func back to defaults", () => {
    const { hook } = renderLocal([], [], undefined);
    act(() => {
      hook.result.current.setLevel("ERROR");
      hook.result.current.setTier("framework");
      hook.result.current.setFunc("some_func");
    });
    act(() => hook.result.current.resetFilters());

    const { level, tier, app, func } = hook.result.current.filterState.value;
    expect(level).toBe("INFO");
    expect(tier).toBe("app");
    expect(app).toBe("");
    expect(func).toBe("");
  });

  it("resets search after debounce clears", async () => {
    const entries = [entry({ message: "hello" }), entry({ message: "world" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setSearch("hello"));
    await new Promise((r) => setTimeout(r, SEARCH_DEBOUNCE_MS + 50));

    act(() => hook.result.current.resetFilters());
    // Search is reset synchronously via direct signal assignment
    const { search } = hook.result.current.filterState.value;
    expect(search).toBe("");
  });
});

// ---------------------------------------------------------------------------
// URL state (useLocalState: false)
// ---------------------------------------------------------------------------

describe("URL state mode", () => {
  it("reads level from URL param", () => {
    mockSearch = "level=WARNING";
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "WARNING", message: "warn" })];
    const { hook } = renderUrl(entries);
    const messages = hook.result.current.visibleEntries.map((e) => e.message);
    expect(messages).not.toContain("debug");
    expect(messages).toContain("warn");
  });

  it('reads level "all" from URL as empty string filter', () => {
    mockSearch = "level=all";
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "INFO", message: "info" })];
    const { hook } = renderUrl(entries);
    const { level } = hook.result.current.filterState.value;
    expect(level).toBe("");
  });

  it("writes level to URL via navigate", () => {
    const { hook } = renderUrl();
    act(() => hook.result.current.setLevel("ERROR"));
    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("level=ERROR");
  });

  it("removes level param from URL when reset to default INFO", () => {
    mockSearch = "level=ERROR";
    const { hook } = renderUrl();
    act(() => hook.result.current.setLevel("INFO"));
    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("level");
  });

  it("reads sort and dir from URL", () => {
    mockSearch = "sort=level&dir=asc";
    const { hook } = renderUrl();
    const { sort } = hook.result.current.filterState.value;
    expect(sort.key).toBe("level");
    expect(sort.dir).toBe("asc");
  });

  it("resets sort by clearing params from URL", () => {
    mockSearch = "sort=level&dir=asc";
    const { hook } = renderUrl();
    act(() => hook.result.current.resetSort());
    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("sort");
    expect(url).not.toContain("dir");
  });

  it("does not write sort/dir for default timestamp-desc", () => {
    mockSearch = "sort=level";
    const { hook } = renderUrl();
    // Click level once (desc) then timestamp (goes back to default desc)
    act(() => hook.result.current.setSort(DEFAULT_SORT));
    const lastCall = mockNavigate.mock.calls[mockNavigate.mock.calls.length - 1];
    const [url] = lastCall;
    expect(url).not.toContain("sort");
    expect(url).not.toContain("dir");
  });
});

// ---------------------------------------------------------------------------
// Search debounce
// ---------------------------------------------------------------------------

describe("search debounce", () => {
  it("does not update filter immediately", async () => {
    const entries = [entry({ message: "needle" }), entry({ message: "haystack" })];
    const { hook } = renderLocal(entries);

    // Fire setSearch but do NOT wait for debounce
    act(() => hook.result.current.setSearch("needle"));

    // Immediately after — search should still be empty (not yet applied)
    const { search } = hook.result.current.filterState.value;
    expect(search).toBe("");
  });

  it("applies filter after 150ms debounce", async () => {
    const entries = [entry({ message: "needle" }), entry({ message: "haystack" })];
    const { hook } = renderLocal(entries);

    act(() => hook.result.current.setSearch("needle"));
    await new Promise((r) => setTimeout(r, SEARCH_DEBOUNCE_MS + 50));

    const { search } = hook.result.current.filterState.value;
    expect(search).toBe("needle");
  });
});
