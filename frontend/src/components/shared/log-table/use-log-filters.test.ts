import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "@/api/endpoints";
import { useAppStore } from "@/state/store";
import { createLogEntry } from "@/test/factories";
import { createWouterMock } from "@/test/mock-wouter";

import { DEFAULT_SORT, RENDER_CAP, SEARCH_DEBOUNCE_MS } from "./constants";
import type { FilterState, LevelFilter } from "./types";
import { filterLogEntries, useLogFilters } from "./use-log-filters";

// dup-ignore-start: vi.mock("wouter", ...) must be written literally in every consumer file for
// Vitest's hoisting transform to detect it (see mock-wouter.ts's createWouterMock docstring) —
// also present in use-correct-url.test.ts and use-query-params.test.ts (T07)
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () =>
  createWouterMock({
    useSearch: () => mockSearch,
    useLocation: () => ["/logs", mockNavigate],
  }),
);
// dup-ignore-end

function entry(overrides: Partial<LogEntry> = {}) {
  return createLogEntry({ app_key: "my_app", source_tier: "app", message: "hello world", ...overrides });
}

/** One app-tier entry and one framework-tier entry — the fixture the "tier filtering" tests
 * reuse to exercise app/framework visibility across tier settings. */
function appAndFrameworkEntries(): LogEntry[] {
  return [
    entry({ source_tier: "app", message: "from app" }),
    entry({ source_tier: "framework", message: "from framework" }),
  ];
}

interface RenderLocalProps {
  entries: LogEntry[];
  appKey?: string;
  executionId?: string | null;
  loading?: boolean;
  fetching?: boolean;
}

/** Render useLogFilters with local state (no URL). Uses initialProps for rerender support. */
function renderLocal(
  entries: LogEntry[] = [],
  appKey?: string,
  executionId?: string | null,
  loading?: boolean,
  fetching?: boolean,
) {
  const hook = renderHook<ReturnType<typeof useLogFilters>, RenderLocalProps>(
    ({ entries: allEntries, appKey, executionId, loading, fetching }) =>
      useLogFilters({ allEntries, useLocalState: true, appKey, executionId, loading, fetching }),
    { initialProps: { entries, appKey, executionId, loading, fetching } },
  );
  return { hook };
}

/** Render useLogFilters in URL mode (reads/writes mockSearch). */
function renderUrl(entries: LogEntry[] = [], appKey?: string, executionId?: string | null) {
  const hook = renderHook(
    ({ entries: allEntries, appKey, executionId }: RenderLocalProps) =>
      useLogFilters({ allEntries, useLocalState: false, appKey, executionId }),
    { initialProps: { entries, appKey, executionId } },
  );
  return { hook };
}

/** Extracts the current visible entries' messages from a `renderLocal`/`renderUrl` result. */
function messagesOf(hook: ReturnType<typeof renderLocal>["hook"] | ReturnType<typeof renderUrl>["hook"]): string[] {
  return hook.result.current.visibleEntries.map((e) => e.message);
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
  useAppStore.setState({ timePreset: "since-restart", urlWindowParam: null });
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

describe("defaultTier", () => {
  it('is "app" when no appKey is provided', () => {
    const { hook } = renderLocal();
    expect(hook.result.current.defaultTier).toBe("app");
  });

  it('is "all" when appKey is provided', () => {
    const { hook } = renderLocal([], "my_app");
    expect(hook.result.current.defaultTier).toBe("all");
  });

  it('is "all" when executionId is provided (no appKey)', () => {
    const { hook } = renderLocal([], undefined, "exec-1");
    expect(hook.result.current.defaultTier).toBe("all");
  });
});

describe("level filtering", () => {
  it("defaults to INFO level and filters out DEBUG entries", () => {
    const entries = [
      entry({ level: "DEBUG", message: "debug" }),
      entry({ level: "INFO", message: "info" }),
      entry({ level: "WARNING", message: "warn" }),
    ];
    const { hook } = renderLocal(entries);
    const messages = messagesOf(hook);
    expect(messages).not.toContain("debug");
    expect(messages).toContain("info");
    expect(messages).toContain("warn");
  });

  it('shows all levels when set to empty string ("all levels")', () => {
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "INFO", message: "info" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setLevel("" as LevelFilter));
    const messages = messagesOf(hook);
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
    const messages = messagesOf(hook);
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
    const messages = messagesOf(hook);
    expect(messages).toEqual(["crit"]);
  });
});

describe("tier filtering", () => {
  // dup-ignore-start: each test below documents a distinct tier-filtering scenario (default tier,
  // explicit tier switch, execution-scope override) via its own comment; the renderLocal/entries
  // setup and paired toContain assertions read as duplicates once CPD normalizes literals, but
  // collapsing them further would replace that per-scenario explanatory context with an opaque
  // helper — see appAndFrameworkEntries()/messagesOf() above for the setup that was extractable
  it('defaults to "app" tier (no appKey) and excludes framework entries', () => {
    const entries = appAndFrameworkEntries();
    const { hook } = renderLocal(entries);
    const messages = messagesOf(hook);
    expect(messages).toContain("from app");
    expect(messages).not.toContain("from framework");
  });

  it('"all" tier shows both app and framework entries', () => {
    const entries = appAndFrameworkEntries();
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setTier("all"));
    const messages = messagesOf(hook);
    expect(messages).toContain("from app");
    expect(messages).toContain("from framework");
  });

  it('"framework" tier shows only framework entries', () => {
    const entries = appAndFrameworkEntries();
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setTier("framework"));
    const messages = messagesOf(hook);
    expect(messages).not.toContain("from app");
    expect(messages).toContain("from framework");
  });

  it("defaults to showing framework entries when executionId is provided", () => {
    // An execution_id scopes rows to one execution; its logs can be framework-tier
    // (e.g. CommandExecutor timeout warnings) even when the execution itself is app-tier.
    const entries = appAndFrameworkEntries();
    const { hook } = renderLocal(entries, undefined, "exec-1");
    const messages = messagesOf(hook);
    expect(messages).toContain("from app");
    expect(messages).toContain("from framework");
  });

  it('defaults to "all" when appKey is provided', () => {
    const entries = [entry({ source_tier: "framework", message: "from framework" })];
    const { hook } = renderLocal(entries, "my_app");
    // "all" tier means framework entries pass through
    const messages = messagesOf(hook);
    expect(messages).toContain("from framework");
  });

  it("re-syncs tier to default when executionId appears after mount (local state)", () => {
    // Regression: on the global /logs page, useLocalState flips true once execution_id
    // is added to the URL in-place (same mounted hook). defaultTier recomputes "app"->"all",
    // but a stale localTier="app" would keep hiding framework rows — the exact bug this PR fixes.
    const entries = appAndFrameworkEntries();
    const { hook } = renderLocal(entries, undefined, null);
    // No execution scope yet: tier defaults to "app", framework hidden.
    expect(messagesOf(hook)).not.toContain("from framework");

    // Execution scope applied to the same mounted hook.
    act(() => hook.rerender({ entries, appKey: undefined, executionId: "exec-1" }));

    const messages = messagesOf(hook);
    expect(messages).toContain("from app");
    expect(messages).toContain("from framework");
  });

  it("preserves a manual tier selection across same-scope rerenders (exec -> exec)", () => {
    // The re-sync must fire only when defaultTier actually flips (scope gained/lost), not on
    // every prop change. Navigating between two executions keeps defaultTier "all", so a user's
    // explicit "framework" choice must survive.
    const entries = appAndFrameworkEntries();
    const { hook } = renderLocal(entries, undefined, "exec-1");
    act(() => hook.result.current.setTier("framework"));
    expect(messagesOf(hook)).toEqual(["from framework"]);

    // Same scope kind (still execution-scoped), different id — defaultTier stays "all".
    act(() => hook.rerender({ entries, appKey: undefined, executionId: "exec-2" }));

    expect(messagesOf(hook)).toEqual(["from framework"]);
  });

  it("clears app filter when tier is changed away from app", () => {
    const entries = [
      entry({ app_key: "alpha", source_tier: "app", message: "alpha" }),
      entry({ app_key: "beta", source_tier: "app", message: "beta" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setApp("alpha"));
    expect(messagesOf(hook)).toEqual(["alpha"]);
    // Changing to "all" should reset app filter
    act(() => hook.result.current.setTier("all"));
    const messages = messagesOf(hook);
    expect(messages).toContain("alpha");
    expect(messages).toContain("beta");
  });
  // dup-ignore-end
});

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
    const messages = messagesOf(hook);
    expect(messages).toEqual(["alpha msg"]);
  });
});

describe("search filtering", () => {
  it("matches message case-insensitively", async () => {
    const entries = [
      entry({ message: "Hello World", logger_name: "logger" }),
      entry({ message: "unrelated", logger_name: "other" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setSearch("hello"));
    await waitForSearchDebounce();
    const messages = messagesOf(hook);
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
    const messages = messagesOf(hook);
    expect(messages).toContain("msg");
    expect(messages).not.toContain("other");
  });
});

describe("func filtering", () => {
  it("filters by func_name case-insensitively", () => {
    const entries = [
      entry({ func_name: "on_state_change", message: "a" }),
      entry({ func_name: "handle_event", message: "b" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setFunc("ON_STATE"));
    const messages = messagesOf(hook);
    expect(messages).toContain("a");
    expect(messages).not.toContain("b");
  });
});

describe("sort", () => {
  it("defaults to timestamp descending", () => {
    const entries = [
      entry({ timestamp: 3000, message: "new" }),
      entry({ timestamp: 2000, message: "mid" }),
      entry({ timestamp: 1000, message: "old" }),
    ];
    const { hook } = renderLocal(entries);
    const messages = messagesOf(hook);
    expect(messages).toEqual(["new", "mid", "old"]);
  });

  it("applies sort state directly", () => {
    const entries = [entry({ timestamp: 3000, message: "new" }), entry({ timestamp: 1000, message: "old" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setSort({ key: "timestamp", dir: "asc" }));
    const messages = messagesOf(hook);
    expect(messages).toEqual(["old", "new"]);
  });

  it("applies a different sort column", () => {
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "CRITICAL", message: "crit" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setLevel(""));
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    const { sort } = hook.result.current.filterState;
    expect(sort.key).toBe("level");
    expect(sort.dir).toBe("desc");
  });

  it("can toggle direction on same column", () => {
    const { hook } = renderLocal();
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    act(() => hook.result.current.setSort({ key: "level", dir: "asc" }));
    const { sort } = hook.result.current.filterState;
    expect(sort.key).toBe("level");
    expect(sort.dir).toBe("asc");
  });

  it("resets to timestamp desc on resetSort", () => {
    const { hook } = renderLocal();
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    act(() => hook.result.current.resetSort());
    const { sort } = hook.result.current.filterState;
    expect(sort.key).toBe("timestamp");
    expect(sort.dir).toBe("desc");
  });
});

describe("livePaused", () => {
  it("is false when sorting by timestamp", () => {
    const { hook } = renderLocal();
    expect(hook.result.current.livePaused).toBe(false);
  });

  it("is true when sorting by any non-timestamp column", () => {
    const { hook } = renderLocal();
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(hook.result.current.livePaused).toBe(true);
  });

  it("freezes entries at the moment pausing began, ignoring later live updates", () => {
    const beforePause = [entry({ message: "before-pause" })];
    const { hook } = renderLocal(beforePause);

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toContain("before-pause");

    // A live update arrives while paused — its own live source changed, but the frozen
    // snapshot captured at the moment pausing began must not reflect it.
    const afterPause = [...beforePause, entry({ message: "after-pause" })];
    hook.rerender({ entries: afterPause, appKey: undefined, executionId: undefined });
    const messages = messagesOf(hook);
    expect(messages).toContain("before-pause");
    expect(messages).not.toContain("after-pause");
  });

  it("reads live entries when not paused", () => {
    const live = [entry({ message: "live" })];
    const { hook } = renderLocal(live);

    const messages = messagesOf(hook);
    expect(messages).toContain("live");
  });

  it("resumes live entries immediately when paused is cleared", () => {
    const beforePause = [entry({ message: "before-pause" })];
    const { hook } = renderLocal(beforePause);

    // Pause by sorting by level, then a live update arrives that the frozen view must miss.
    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    const afterPause = [...beforePause, entry({ message: "after-pause" })];
    hook.rerender({ entries: afterPause, appKey: undefined, executionId: undefined });
    expect(messagesOf(hook)).not.toContain("after-pause");

    // Unpause by resetting sort — the live update missed while paused must now be visible.
    act(() => hook.result.current.resetSort());
    expect(messagesOf(hook)).toContain("after-pause");
  });

  it("re-captures the paused snapshot when appKey/executionId changes while still paused", () => {
    const execAEntries = [entry({ message: "exec-a-row" })];
    const { hook } = renderLocal(execAEntries, "my_app", "exec-a");

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual(["exec-a-row"]);

    // Scope changes to a different execution without unmounting (e.g. LogsPage updating
    // executionId from a query param) while still paused — the frozen snapshot must not keep
    // showing the previous execution's rows.
    const execBEntries = [entry({ message: "exec-b-row" })];
    hook.rerender({ entries: execBEntries, appKey: "my_app", executionId: "exec-b" });

    expect(messagesOf(hook)).toEqual(["exec-b-row"]);
  });

  it("keeps tracking a scope change's data until it loads, instead of freezing on the transient empty result", () => {
    const execAEntries = [entry({ message: "exec-a-row" })];
    const { hook } = renderLocal(execAEntries, "my_app", "exec-a");

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual(["exec-a-row"]);

    // Scope changes to a different execution while still paused, but its query hasn't resolved
    // yet — allEntries is transiently empty. Snapshotting this instant and never revisiting it
    // (the old behavior) would freeze the table on nothing forever, even once real data arrives.
    // A scope-change freeze tracks `fetching` (isFetching), not `loading` (isPending) — see
    // use-log-filters.ts: a scope change to an already-cached scope can leave `loading` false
    // immediately while a background refetch is still settling.
    hook.rerender({ entries: [], appKey: "my_app", executionId: "exec-b", fetching: true });
    expect(messagesOf(hook)).toEqual([]);

    // Data for the new scope lands, but fetching is still true one more render (e.g. react-query
    // still settling a background refetch) — the snapshot must keep tracking, not freeze on this
    // transitional render.
    const execBEntries = [entry({ message: "exec-b-row" })];
    hook.rerender({ entries: execBEntries, appKey: "my_app", executionId: "exec-b", fetching: true });
    expect(messagesOf(hook)).toEqual(["exec-b-row"]);

    // fetching finally clears — now frozen on the loaded data.
    hook.rerender({ entries: execBEntries, appKey: "my_app", executionId: "exec-b", fetching: false });
    expect(messagesOf(hook)).toEqual(["exec-b-row"]);

    // Now frozen: a further live update to the same scope must not appear until resumed.
    hook.rerender({
      entries: [...execBEntries, entry({ message: "exec-b-later-row" })],
      appKey: "my_app",
      executionId: "exec-b",
      fetching: false,
    });
    expect(messagesOf(hook)).toEqual(["exec-b-row"]);
  });

  it("keeps tracking an ordinary pause transition's data until it loads (loading, not fetching)", () => {
    // Mirrors the scope-change test above, but for the false->true pause transition with no
    // scope change — that branch tracks `loading` (isPending), not `fetching`.
    const { hook } = renderLocal([], "my_app", "exec-a", true);

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual([]);

    const settledEntries = [entry({ message: "settled-row" })];
    hook.rerender({ entries: settledEntries, appKey: "my_app", executionId: "exec-a", loading: true });
    expect(messagesOf(hook)).toEqual(["settled-row"]);

    hook.rerender({ entries: settledEntries, appKey: "my_app", executionId: "exec-a", loading: false });
    expect(messagesOf(hook)).toEqual(["settled-row"]);

    hook.rerender({
      entries: [...settledEntries, entry({ message: "later-row" })],
      appKey: "my_app",
      executionId: "exec-a",
      loading: false,
    });
    expect(messagesOf(hook)).toEqual(["settled-row"]);
  });

  it("re-captures the paused snapshot when the time-window preset changes while still paused", () => {
    const beforeEntries = [entry({ message: "1h-row" })];
    const { hook } = renderLocal(beforeEntries, "my_app", undefined);

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual(["1h-row"]);

    // Preset changes (e.g. the user switches the dashboard's time window) without appKey or
    // executionId changing — useLogData scopes its query by preset too, so the paused snapshot
    // must treat this as a scope change and refresh, not keep showing the previous window's rows.
    // The store update and the new entries land in the same render here, same as they would in
    // the real component tree (useLogTable calls useLogData then useLogFilters in one render
    // pass, so both the preset and the resulting allEntries always update together).
    const afterEntries = [entry({ message: "24h-row" })];
    act(() => {
      useAppStore.setState({ timePreset: "24h" });
      hook.rerender({ entries: afterEntries, appKey: "my_app", executionId: undefined });
    });

    expect(messagesOf(hook)).toEqual(["24h-row"]);
  });
});

describe("resetFilters", () => {
  it("resets level, tier, app, func back to defaults", () => {
    const { hook } = renderLocal([], undefined);
    act(() => {
      hook.result.current.setLevel("ERROR");
      hook.result.current.setTier("framework");
      hook.result.current.setFunc("some_func");
    });
    act(() => hook.result.current.resetFilters());

    const { level, tier, app, func } = hook.result.current.filterState;
    expect(level).toBe("INFO");
    expect(tier).toBe("app");
    expect(app).toBe("");
    expect(func).toBe("");
  });

  it("resets search after debounce clears", async () => {
    const entries = [entry({ message: "hello" }), entry({ message: "world" })];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setSearch("hello"));
    await waitForSearchDebounce();

    act(() => hook.result.current.resetFilters());
    // Search is reset synchronously via direct signal assignment
    const { search } = hook.result.current.filterState;
    expect(search).toBe("");
  });
});

describe("URL state mode", () => {
  it("reads level from URL param", () => {
    mockSearch = "level=WARNING";
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "WARNING", message: "warn" })];
    const { hook } = renderUrl(entries);
    const messages = messagesOf(hook);
    expect(messages).not.toContain("debug");
    expect(messages).toContain("warn");
  });

  it('reads level "all" from URL as empty string filter', () => {
    mockSearch = "level=all";
    const entries = [entry({ level: "DEBUG", message: "debug" }), entry({ level: "INFO", message: "info" })];
    const { hook } = renderUrl(entries);
    const { level } = hook.result.current.filterState;
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
    const { sort } = hook.result.current.filterState;
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

describe("search debounce", () => {
  it("does not update filter immediately", async () => {
    const entries = [entry({ message: "needle" }), entry({ message: "haystack" })];
    const { hook } = renderLocal(entries);

    // Fire setSearch but do NOT wait for debounce
    act(() => hook.result.current.setSearch("needle"));

    // Immediately after — search should still be empty (not yet applied)
    const { search } = hook.result.current.filterState;
    expect(search).toBe("");
  });

  it("applies filter after SEARCH_DEBOUNCE_MS", async () => {
    const entries = [entry({ message: "needle" }), entry({ message: "haystack" })];
    const { hook } = renderLocal(entries);

    act(() => hook.result.current.setSearch("needle"));
    await waitForSearchDebounce();

    const { search } = hook.result.current.filterState;
    expect(search).toBe("needle");
  });
});
