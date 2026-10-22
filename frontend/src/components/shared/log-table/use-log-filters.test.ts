import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "@/api/endpoints";
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
  return createLogEntry({ app_key: "my_app", message: "hello world", ...overrides });
}

interface RenderOptions {
  loading?: boolean;
  fetching?: boolean;
  scopeKey?: readonly unknown[];
}

interface RenderLocalProps extends RenderOptions {
  entries: LogEntry[];
}

/** Render useLogFilters with local state (no URL). Uses initialProps for rerender support.
 *
 * `scopeKey` is an opaque test double for `useLogData`'s real (app/execution/preset/uptime)
 * query key — `useLogFilters` only ever compares it by value, so tests exercising scope-change
 * behavior pass whatever distinct values are convenient (e.g. `["a"]` vs `["b"]"`) rather than
 * replicating the real key shape. Tests that don't pass one get the hook's own stable default,
 * matching how the real `useLogData`/`useScopedQuery` pipeline is the only source of a
 * scope-change signal in production. */
function renderLocal(entries: LogEntry[] = [], { loading, fetching, scopeKey }: RenderOptions = {}) {
  const hook = renderHook<ReturnType<typeof useLogFilters>, RenderLocalProps>(
    ({ entries: allEntries, loading, fetching, scopeKey }) =>
      useLogFilters({ allEntries, useLocalState: true, loading, fetching, scopeKey }),
    { initialProps: { entries, loading, fetching, scopeKey } },
  );
  return { hook };
}

/** Render useLogFilters in URL mode (reads/writes mockSearch). */
function renderUrl(entries: LogEntry[] = []) {
  const hook = renderHook(
    ({ entries: allEntries }: RenderLocalProps) => useLogFilters({ allEntries, useLocalState: false }),
    { initialProps: { entries } },
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

describe("app filtering", () => {
  it("filters entries to only matching app_key", () => {
    const entries = [
      entry({ app_key: "alpha", message: "alpha msg" }),
      entry({ app_key: "beta", message: "beta msg" }),
    ];
    const { hook } = renderLocal(entries);
    act(() => hook.result.current.setApp("alpha"));
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
    hook.rerender({ entries: afterPause });
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
    hook.rerender({ entries: afterPause });
    expect(messagesOf(hook)).not.toContain("after-pause");

    // Unpause by resetting sort — the live update missed while paused must now be visible.
    act(() => hook.result.current.resetSort());
    expect(messagesOf(hook)).toContain("after-pause");
  });

  it("re-captures the paused snapshot when the scope changes while still paused", () => {
    const execAEntries = [entry({ message: "exec-a-row" })];
    const { hook } = renderLocal(execAEntries, { scopeKey: ["exec-a-scope"] });

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual(["exec-a-row"]);

    // Scope changes to a different execution without unmounting (e.g. LogsPage updating
    // executionId from a query param) while still paused — the frozen snapshot must not keep
    // showing the previous execution's rows.
    const execBEntries = [entry({ message: "exec-b-row" })];
    hook.rerender({ entries: execBEntries, scopeKey: ["exec-b-scope"] });

    expect(messagesOf(hook)).toEqual(["exec-b-row"]);
  });

  it("keeps tracking a scope change's data until it loads, instead of freezing on the transient empty result", () => {
    const execAEntries = [entry({ message: "exec-a-row" })];
    const { hook } = renderLocal(execAEntries, { scopeKey: ["exec-a-scope"] });

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual(["exec-a-row"]);

    // Scope changes to a different execution while still paused, but its query hasn't resolved
    // yet — allEntries is transiently empty. Snapshotting this instant and never revisiting it
    // (the old behavior) would freeze the table on nothing forever, even once real data arrives.
    // A scope-change freeze tracks `fetching` (isFetching), not `loading` (isPending) — see
    // use-log-filters.ts: a scope change to an already-cached scope can leave `loading` false
    // immediately while a background refetch is still settling.
    hook.rerender({ entries: [], fetching: true, scopeKey: ["exec-b-scope"] });
    expect(messagesOf(hook)).toEqual([]);

    // Data for the new scope lands, but fetching is still true one more render (e.g. react-query
    // still settling a background refetch) — the snapshot must keep tracking, not freeze on this
    // transitional render.
    const execBEntries = [entry({ message: "exec-b-row" })];
    hook.rerender({
      entries: execBEntries,
      fetching: true,
      scopeKey: ["exec-b-scope"],
    });
    expect(messagesOf(hook)).toEqual(["exec-b-row"]);

    // fetching finally clears — now frozen on the loaded data.
    hook.rerender({
      entries: execBEntries,
      fetching: false,
      scopeKey: ["exec-b-scope"],
    });
    expect(messagesOf(hook)).toEqual(["exec-b-row"]);

    // Now frozen: a further live update to the same scope must not appear until resumed.
    hook.rerender({
      entries: [...execBEntries, entry({ message: "exec-b-later-row" })],
      fetching: false,
      scopeKey: ["exec-b-scope"],
    });
    expect(messagesOf(hook)).toEqual(["exec-b-row"]);
  });

  it("re-captures the paused snapshot when scopeKey changes for a reason other than app/execution (e.g. since-restart uptime)", () => {
    // Regression test for the exact gap Codex flagged: scopeChanged used to be computed from
    // appKey/executionId/preset alone, so a scope-identity change driven purely by restart uptime
    // (useScopedQuery folds uptime into its query key for the since-restart preset, but nothing
    // else about appKey/executionId/preset changes on a WS reconnect) went undetected and the
    // paused snapshot never re-synced. Comparing the resolved scopeKey directly — same appKey and
    // executionId throughout, only the key's uptime component differs — closes that gap by
    // construction rather than requiring a fourth hand-copied field.
    const beforeEntries = [entry({ message: "pre-reconnect-row" })];
    const { hook } = renderLocal(beforeEntries, {
      scopeKey: ["recent-logs", "my_app", "exec-a", "since-restart", 100],
    });

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual(["pre-reconnect-row"]);

    // WS reconnect updates uptimeSeconds; appKey/executionId/preset are unchanged.
    const afterEntries = [entry({ message: "post-reconnect-row" })];
    hook.rerender({
      entries: afterEntries,
      scopeKey: ["recent-logs", "my_app", "exec-a", "since-restart", 200],
    });

    expect(messagesOf(hook)).toEqual(["post-reconnect-row"]);
  });

  it("keeps tracking an ordinary pause transition's data until it loads (loading, not fetching)", () => {
    // Mirrors the scope-change test above, but for the false->true pause transition with no
    // scope change — that branch tracks `loading` (isPending), not `fetching`.
    const { hook } = renderLocal([], { loading: true });

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual([]);

    const settledEntries = [entry({ message: "settled-row" })];
    hook.rerender({ entries: settledEntries, loading: true });
    expect(messagesOf(hook)).toEqual(["settled-row"]);

    hook.rerender({ entries: settledEntries, loading: false });
    expect(messagesOf(hook)).toEqual(["settled-row"]);

    hook.rerender({
      entries: [...settledEntries, entry({ message: "later-row" })],
      loading: false,
    });
    expect(messagesOf(hook)).toEqual(["settled-row"]);
  });

  it("re-captures the paused snapshot when the time-window preset changes while still paused", () => {
    const beforeEntries = [entry({ message: "1h-row" })];
    const { hook } = renderLocal(beforeEntries, { scopeKey: ["recent-logs", "my_app", null, "1h"] });

    act(() => hook.result.current.setSort({ key: "level", dir: "desc" }));
    expect(messagesOf(hook)).toEqual(["1h-row"]);

    // Preset changes (e.g. the user switches the dashboard's time window) without appKey or
    // executionId changing — useLogData's scopeKey folds preset in too, so the paused snapshot
    // must treat this as a scope change and refresh, not keep showing the previous window's rows.
    // scopeKey changing alongside the new entries in the same render mirrors the real component
    // tree (useLogTable calls useLogData then useLogFilters in one render pass, so scopeKey and
    // the resulting allEntries always update together).
    const afterEntries = [entry({ message: "24h-row" })];
    hook.rerender({
      entries: afterEntries,
      scopeKey: ["recent-logs", "my_app", null, "24h"],
    });

    expect(messagesOf(hook)).toEqual(["24h-row"]);
  });
});

describe("resetFilters", () => {
  it("resets level, app, func back to defaults", () => {
    const { hook } = renderLocal([]);
    act(() => {
      hook.result.current.setLevel("ERROR");
      hook.result.current.setApp("alpha");
      hook.result.current.setFunc("some_func");
    });
    act(() => hook.result.current.resetFilters());

    const { level, app, func } = hook.result.current.filterState;
    expect(level).toBe("INFO");
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
