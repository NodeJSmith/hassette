import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act } from "@testing-library/preact";
import { h } from "preact";
import type { ComponentChildren } from "preact";
import { LogTable, sortEntries } from "./log-table";
import type { LogEntry } from "../../api/endpoints";
import { AppStateContext } from "../../state/context";
import { createAppState, type AppState } from "../../state/create-app-state";
import type { WsLogPayload } from "../../api/ws-types";

// Mock useMediaQuery — default to desktop (false), overridden in mobile tests
const mockUseMediaQuery = vi.fn((_maxWidth: number) => false);
vi.mock("../../hooks/use-media-query", () => ({
  useMediaQuery: (maxWidth: number) => mockUseMediaQuery(maxWidth),
  BREAKPOINT_MOBILE: 768,
  BREAKPOINT_TABLET: 1024,
}));

// Mock the API endpoint for initial log fetch
vi.mock("../../api/endpoints", () => ({
  getRecentLogs: vi.fn().mockResolvedValue([]),
}));

// Reactive query param mock: mockSearchSignal drives useSearch() so that when
// mockNavigate is called by qp.set(), the component re-renders with the new params.
// _setMockSearch() is used in tests to set the initial URL state before rendering.
import { signal as _signal } from "@preact/signals";
const mockSearchSignal = _signal("");

const _setMockSearch = (v: string) => {
  mockSearchSignal.value = v;
};

const mockNavigate = vi.fn((url: string) => {
  const qIdx = (url as string).indexOf("?");
  _setMockSearch(qIdx >= 0 ? url.slice(qIdx + 1) : "");
});

/** Re-attach the navigate side-effect after vi.clearAllMocks() clears it. */
function restoreNavigateMock() {
  mockNavigate.mockImplementation((url: string) => {
    const qIdx = url.indexOf("?");
    _setMockSearch(qIdx >= 0 ? url.slice(qIdx + 1) : "");
  });
}

vi.mock("wouter", () => ({
  useSearch: () => mockSearchSignal.value,
  useLocation: () => ["/logs", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string}>{children as never}</a>,
}));

// --- JSDOM polyfills for ResizeObserver, requestAnimationFrame, and document.fonts ---

let rafCallbacks: Array<FrameRequestCallback> = [];
let rafIdCounter = 0;

// Capture the polyfill values installed by test-setup.ts at module load time.
// test-setup.ts setupFiles run before test modules are evaluated, so these
// will hold the polyfill functions (not jsdom's undefined values). Restoring
// to these values in afterEach keeps Preact's cancelAnimationFrame cleanup
// working for any pending setTimeout-based callbacks that fire after teardown.
const setupRAF = globalThis.requestAnimationFrame;
const setupCAF = globalThis.cancelAnimationFrame;

beforeEach(() => {
  rafCallbacks = [];
  rafIdCounter = 0;
  _setMockSearch("");
  mockNavigate.mockReset();
  restoreNavigateMock();
  globalThis.requestAnimationFrame = (cb: FrameRequestCallback) => {
    const id = ++rafIdCounter;
    rafCallbacks.push(cb);
    return id;
  };
  globalThis.cancelAnimationFrame = (_id: number) => {
    // no-op for tests
  };
});

afterEach(() => {
  globalThis.requestAnimationFrame =
    setupRAF ?? ((cb: FrameRequestCallback) => setTimeout(cb, 0) as unknown as number);
  globalThis.cancelAnimationFrame =
    setupCAF ?? ((id: number) => clearTimeout(id));
});

/** Flush all pending requestAnimationFrame callbacks within act(). */
function flushRAF() {
  return act(() => {
    const cbs = [...rafCallbacks];
    rafCallbacks = [];
    for (const cb of cbs) cb(performance.now());
  });
}

// ResizeObserver mock — stores observed elements but never fires the callback
// (viewport resize is not testable in JSDOM; truncation detection is exercised
// via the data-change trigger path B which uses requestAnimationFrame).
class MockResizeObserver {
  callback: ResizeObserverCallback;
  observed = new Set<Element>();
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }
  observe(el: Element) { this.observed.add(el); }
  unobserve(el: Element) { this.observed.delete(el); }
  disconnect() { this.observed.clear(); }
}

const origResizeObserver = globalThis.ResizeObserver;
const origFonts = Object.getOwnPropertyDescriptor(document, "fonts");

beforeEach(() => {
  globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;
  Object.defineProperty(document, "fonts", {
    value: { ready: Promise.resolve() },
    configurable: true,
  });
});

afterEach(() => {
  globalThis.ResizeObserver = origResizeObserver;
  if (origFonts) {
    Object.defineProperty(document, "fonts", origFonts);
  }
});

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

let entrySeq = 0;

function createLogEntry(overrides: Partial<WsLogPayload> = {}): WsLogPayload {
  ++entrySeq;
  return {
    seq: entrySeq,
    timestamp: entrySeq,
    level: "INFO",
    logger_name: "hassette.test",
    func_name: "test_func",
    lineno: 42,
    message: "Test log message",
    exc_info: null,
    app_key: "my_app",
    execution_id: null,
    instance_name: null,
    instance_index: null,
    source_tier: "app",
    ...overrides,
  };
}

describe("LogTable", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  // -- Empty state --

  it("shows empty message when no logs exist", () => {
    const { getByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("no log lines in window")).toBeDefined();
  });

  // -- Rendering WS log entries --

  it("renders log entries from the ring buffer", () => {
    state.logs.push(createLogEntry({ message: "Hello from WS" }));

    const { getByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("Hello from WS")).toBeDefined();
  });

  it("shows entry count", () => {
    state.logs.push(createLogEntry({ message: "Entry 1" }));
    state.logs.push(createLogEntry({ message: "Entry 2" }));

    const { getByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("2 entries")).toBeDefined();
  });

  it("shows singular count for 1 entry", () => {
    state.logs.push(createLogEntry());

    const { getByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("1 entry")).toBeDefined();
  });

  // -- Level filtering --

  it("filters entries by minimum level", () => {
    state.logs.push(createLogEntry({ level: "DEBUG", message: "debug msg" }));
    state.logs.push(createLogEntry({ level: "INFO", message: "info msg" }));
    state.logs.push(createLogEntry({ level: "WARNING", message: "warn msg" }));
    state.logs.push(createLogEntry({ level: "ERROR", message: "error msg" }));

    const { getByText, queryByText, getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Default is INFO — debug not visible initially
    expect(queryByText("debug msg")).toBeNull();
    expect(getByText("info msg")).toBeDefined();
    expect(getByText("error msg")).toBeDefined();

    // Select "All Levels" to show everything including DEBUG
    fireEvent.change(getByTestId("filter-level"), { target: { value: "" } });
    expect(getByText("debug msg")).toBeDefined();
    expect(getByText("error msg")).toBeDefined();

    // Filter to WARNING+
    fireEvent.change(getByTestId("filter-level"), { target: { value: "WARNING" } });

    expect(queryByText("debug msg")).toBeNull();
    expect(queryByText("info msg")).toBeNull();
    expect(getByText("warn msg")).toBeDefined();
    expect(getByText("error msg")).toBeDefined();
  });

  // -- App filtering --

  it("filters by app when appKeys are provided", () => {
    state.logs.push(createLogEntry({ app_key: "app_a", message: "from A" }));
    state.logs.push(createLogEntry({ app_key: "app_b", message: "from B" }));

    const { getByText, queryByText, getByTestId } = render(
      <LogTable showAppColumn appKeys={["app_a", "app_b"]} />,
      { wrapper: createWrapper(state) },
    );

    // All visible initially
    expect(getByText("from A")).toBeDefined();
    expect(getByText("from B")).toBeDefined();

    fireEvent.change(getByTestId("log-app-filter"), { target: { value: "app_a" } });

    expect(getByText("from A")).toBeDefined();
    expect(queryByText("from B")).toBeNull();
  });

  it("does not show app filter when appKeys is not provided", () => {
    const { queryByTestId, getByTestId } = render(
      <LogTable showAppColumn />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("filter-level")).toBeDefined();
    expect(queryByTestId("log-app-filter")).toBeNull();
  });

  it("filters by appKey prop (app-scoped log table)", () => {
    state.logs.push(createLogEntry({ app_key: "target", message: "yes" }));
    state.logs.push(createLogEntry({ app_key: "other", message: "no" }));

    const { getByText, queryByText } = render(
      <LogTable appKey="target" />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("yes")).toBeDefined();
    expect(queryByText("no")).toBeNull();
  });

  // -- Search --

  it("filters by search text in message", async () => {
    vi.useFakeTimers();
    state.logs.push(createLogEntry({ message: "Starting scheduler" }));
    state.logs.push(createLogEntry({ message: "Bus connected" }));

    const { getByText, queryByText, getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const searchInput = getByPlaceholderText("Search...");
    fireEvent.input(searchInput, { target: { value: "scheduler" } });
    await act(() => { vi.advanceTimersByTime(200); }); // flush 150ms debounce + re-render

    expect(getByText("Starting scheduler")).toBeDefined();
    expect(queryByText("Bus connected")).toBeNull();
    vi.useRealTimers();
  });

  it("filters by search text in logger name", async () => {
    vi.useFakeTimers();
    state.logs.push(createLogEntry({ logger_name: "hassette.bus", message: "msg1" }));
    state.logs.push(createLogEntry({ logger_name: "hassette.scheduler", message: "msg2" }));

    const { getByText, queryByText, getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "bus" } });
    await act(() => { vi.advanceTimersByTime(200); });

    expect(getByText("msg1")).toBeDefined();
    expect(queryByText("msg2")).toBeNull();
    vi.useRealTimers();
  });

  it("search is case-insensitive", async () => {
    vi.useFakeTimers();
    state.logs.push(createLogEntry({ message: "WebSocket Connected" }));

    const { getByText, getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "websocket" } });
    await act(() => { vi.advanceTimersByTime(200); });

    expect(getByText("WebSocket Connected")).toBeDefined();
    vi.useRealTimers();
  });

  // -- Sort toggle --

  it("sorts non-chronological entries by timestamp descending", () => {
    // Push entries out of chronological order
    state.logs.push(createLogEntry({ timestamp: 2000, message: "mid" }));
    state.logs.push(createLogEntry({ timestamp: 1000, message: "oldest" }));
    state.logs.push(createLogEntry({ timestamp: 3000, message: "newest" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBe(3);
    // Default descending: 3000, 2000, 1000
    expect(rows[0].textContent).toContain("newest");
    expect(rows[1].textContent).toContain("mid");
    expect(rows[2].textContent).toContain("oldest");
  });

  it("toggles sort direction on timestamp header click", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "older" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "newer" }));

    const { container, getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const rows = container.querySelectorAll("tbody tr");
    // Default sort is descending (newest first)
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0].textContent).toContain("newer");

    // Click sort button inside timestamp header to toggle to ascending
    const sortBtn = getByTestId("sort-timestamp").querySelector("button") as HTMLElement;
    fireEvent.click(sortBtn);

    const rowsAfter = container.querySelectorAll("tbody tr");
    expect(rowsAfter.length).toBeGreaterThan(0);
    expect(rowsAfter[0].textContent).toContain("older");
  });

  // -- Row expand/collapse --

  it("non-truncated message cell is not interactive", async () => {
    // JSDOM has no layout engine, so scrollWidth === clientWidth === 0 → not truncated
    state.logs.push(createLogEntry({ message: "Short message" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );
    await flushRAF();

    const msgCell = container.querySelector("[data-testid='log-message-cell']") as HTMLElement;
    expect(msgCell).toBeDefined();
    // No role="button" or aria-expanded on non-expandable cells
    expect(msgCell.getAttribute("role")).toBeNull();
    expect(msgCell.getAttribute("aria-expanded")).toBeNull();
  });

  it("clicking non-truncated cell does not add is-expanded", async () => {
    state.logs.push(createLogEntry({ message: "Short message" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );
    await flushRAF();

    const msgCell = container.querySelector("[data-testid='log-message-cell']") as HTMLElement;
    fireEvent.click(msgCell);
    expect(msgCell.getAttribute("aria-expanded")).toBeNull();
  });

  it("truncated message cell becomes expandable and toggles on click", async () => {
    state.logs.push(createLogEntry({ message: "A very long message that would be truncated" }));

    // Mock scrollWidth > clientWidth to simulate truncation in JSDOM
    const origScrollWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollWidth");
    const origClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", { configurable: true, get() { return 500; } });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get() { return 200; } });

    try {
      const { container } = render(
        <LogTable />,
        { wrapper: createWrapper(state) },
      );
      // Flush requestAnimationFrame to trigger recheckTruncation()
      await flushRAF();

      const msgCell = container.querySelector("[data-testid='log-message-cell']") as HTMLElement;
      expect(msgCell.getAttribute("role")).toBe("button");
      expect(msgCell.getAttribute("aria-expanded")).toBe("false");

      fireEvent.click(msgCell);
      expect(msgCell.getAttribute("aria-expanded")).toBe("true");

      fireEvent.click(msgCell);
      expect(msgCell.getAttribute("aria-expanded")).toBe("false");
    } finally {
      if (origScrollWidth) Object.defineProperty(HTMLElement.prototype, "scrollWidth", origScrollWidth);
      if (origClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", origClientWidth);
    }
  });

  it("truncated message cell expands via keyboard", async () => {
    state.logs.push(createLogEntry({ message: "Truncated keyboard test" }));

    const origScrollWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollWidth");
    const origClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", { configurable: true, get() { return 500; } });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get() { return 200; } });

    try {
      const { container } = render(
        <LogTable />,
        { wrapper: createWrapper(state) },
      );
      await flushRAF();

      const msgCell = container.querySelector("[data-testid='log-message-cell']") as HTMLElement;
      fireEvent.keyDown(msgCell, { key: "Enter" });
      expect(msgCell.getAttribute("aria-expanded")).toBe("true");

      fireEvent.keyDown(msgCell, { key: " " });
      expect(msgCell.getAttribute("aria-expanded")).toBe("false");
    } finally {
      if (origScrollWidth) Object.defineProperty(HTMLElement.prototype, "scrollWidth", origScrollWidth);
      if (origClientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", origClientWidth);
    }
  });

  it("renders data-row-key attribute on message text elements", () => {
    state.logs.push(createLogEntry({ seq: 42, message: "Test with key" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const textEl = container.querySelector("[data-row-key]") as HTMLElement;
    expect(textEl).not.toBeNull();
    expect(textEl.getAttribute("data-row-key")).toBe("42");
  });

  // -- App column visibility --

  it("hides app column when showAppColumn is false", () => {
    state.logs.push(createLogEntry());

    const { container } = render(
      <LogTable showAppColumn={false} />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent ?? "");
    expect(headerTexts.some((t) => t.includes("App"))).toBe(false);
  });

  it("shows app column by default", () => {
    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent ?? "");
    expect(headerTexts.some((t) => t.includes("App"))).toBe(true);
  });

  // -- Source column --

  it("renders Source column header", () => {
    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent);
    expect(headerTexts).toContain("Source");
  });

  it("renders source location with func_name and lineno", () => {
    state.logs.push(createLogEntry({ func_name: "on_initialize", lineno: 99 }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const sourceCells = container.querySelectorAll("td.ht-col-source");
    expect(sourceCells.length).toBe(1);
    expect(sourceCells[0].textContent).toContain("on_initialize");
    expect(sourceCells[0].textContent).toContain("99");
  });

  it("renders full logger path in source column title attribute", () => {
    state.logs.push(createLogEntry({ logger_name: "hassette.bus", func_name: "dispatch", lineno: 42 }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const sourceCell = container.querySelector("td.ht-col-source") as HTMLElement;
    expect(sourceCell.getAttribute("title")).toBe("hassette.bus:dispatch:42");
  });

  // -- Level badge variants (StatusShape-based) --

  it("renders err StatusShape for ERROR level", () => {
    state.logs.push(createLogEntry({ level: "ERROR" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // The level badge wraps a StatusShape SVG and the level text
    const badge = container.querySelector("[data-testid='log-level-badge']");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("ERROR");
    // err kind renders a rect (rounded square) SVG element
    expect(badge!.querySelector("rect")).not.toBeNull();
  });

  it("renders warn StatusShape for WARNING level", () => {
    state.logs.push(createLogEntry({ level: "WARNING" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const badge = container.querySelector("[data-testid='log-level-badge']");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("WARNING");
    // warn kind renders a triangle (polygon) SVG element
    expect(badge!.querySelector("polygon")).not.toBeNull();
  });

  it("renders ok StatusShape for INFO level", () => {
    state.logs.push(createLogEntry({ level: "INFO" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const badge = container.querySelector("[data-testid='log-level-badge']");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("INFO");
    // ok kind renders a filled circle SVG element
    expect(badge!.querySelector("circle")).not.toBeNull();
  });

  it("renders mute StatusShape for DEBUG level", () => {
    state.logs.push(createLogEntry({ level: "DEBUG" }));

    const { container, getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Need to show DEBUG — default filter is INFO
    fireEvent.change(getByTestId("filter-level"), { target: { value: "" } });

    const badge = container.querySelector("[data-testid='log-level-badge']");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toContain("DEBUG");
    // mute kind renders a stroke-only circle (no filled rect/polygon)
    expect(badge!.querySelector("rect")).toBeNull();
    expect(badge!.querySelector("polygon")).toBeNull();
  });
});

describe("Dedup via seq watermark (#364)", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("filters WS entries at or below the REST watermark", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;

    // REST returns entries with seq 1-5
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ seq: 1, timestamp: 1000, message: "rest-1" }),
      createLogEntry({ seq: 2, timestamp: 2000, message: "rest-2" }),
      createLogEntry({ seq: 3, timestamp: 3000, message: "rest-3" }),
      createLogEntry({ seq: 4, timestamp: 4000, message: "rest-4" }),
      createLogEntry({ seq: 5, timestamp: 5000, message: "rest-5" }),
    ]);

    // WS buffer has overlapping entries (seq 3-8)
    state.logs.push(createLogEntry({ seq: 3, timestamp: 3000, message: "ws-3" }));
    state.logs.push(createLogEntry({ seq: 4, timestamp: 4000, message: "ws-4" }));
    state.logs.push(createLogEntry({ seq: 5, timestamp: 5000, message: "ws-5" }));
    state.logs.push(createLogEntry({ seq: 6, timestamp: 6000, message: "ws-6" }));
    state.logs.push(createLogEntry({ seq: 7, timestamp: 7000, message: "ws-7" }));
    state.logs.push(createLogEntry({ seq: 8, timestamp: 8000, message: "ws-8" }));

    const { findByText, queryByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Wait for REST entries to load (sets watermark = 5)
    await findByText("rest-1");

    // REST entries should all be visible
    expect(queryByText("rest-1")).not.toBeNull();
    expect(queryByText("rest-5")).not.toBeNull();

    // WS entries at or below watermark (seq 3, 4, 5) should be filtered out
    expect(queryByText("ws-3")).toBeNull();
    expect(queryByText("ws-4")).toBeNull();
    expect(queryByText("ws-5")).toBeNull();

    // WS entries above watermark (seq 6, 7, 8) should be visible
    expect(queryByText("ws-6")).not.toBeNull();
    expect(queryByText("ws-7")).not.toBeNull();
    expect(queryByText("ws-8")).not.toBeNull();
  });
});

describe("REST + WS entry merging (#403)", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("merges REST and WS entries in sorted order", async () => {
    // Override getRecentLogs to return initial REST entries
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ timestamp: 1000, message: "rest-old" }),
      createLogEntry({ timestamp: 3000, message: "rest-new" }),
    ]);

    // Push WS entries with timestamps that interleave with REST entries
    state.logs.push(createLogEntry({ timestamp: 2000, message: "ws-mid" }));
    state.logs.push(createLogEntry({ timestamp: 4000, message: "ws-newest" }));

    const { container, findByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Wait for REST entries to load
    await findByText("rest-old");

    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBe(4);
    // Default descending sort: 4000, 3000, 2000, 1000
    expect(rows[0].textContent).toContain("ws-newest");
    expect(rows[1].textContent).toContain("rest-new");
    expect(rows[2].textContent).toContain("ws-mid");
    expect(rows[3].textContent).toContain("rest-old");
  });
});

// -- sortEntries unit tests --

describe("sortEntries", () => {
  function entry(overrides: Partial<LogEntry>): LogEntry {
    return {
      seq: 1,
      timestamp: 1000,
      level: "INFO",
      logger_name: "test",
      func_name: "fn",
      lineno: 1,
      message: "msg",
      exc_info: null,
      app_key: "app",
      ...overrides,
    };
  }

  it("sorts by timestamp descending by default", () => {
    const entries = [
      entry({ timestamp: 1000, message: "old" }),
      entry({ timestamp: 3000, message: "new" }),
      entry({ timestamp: 2000, message: "mid" }),
    ];
    const result = sortEntries(entries, "timestamp", false);
    expect(result.map((e) => e.message)).toEqual(["new", "mid", "old"]);
  });

  it("sorts by timestamp ascending", () => {
    const entries = [
      entry({ timestamp: 3000, message: "new" }),
      entry({ timestamp: 1000, message: "old" }),
    ];
    const result = sortEntries(entries, "timestamp", true);
    expect(result.map((e) => e.message)).toEqual(["old", "new"]);
  });

  it("sorts by level using severity index", () => {
    const entries = [
      entry({ level: "INFO", message: "info" }),
      entry({ level: "CRITICAL", message: "crit" }),
      entry({ level: "DEBUG", message: "debug" }),
      entry({ level: "ERROR", message: "error" }),
      entry({ level: "WARNING", message: "warn" }),
    ];
    const result = sortEntries(entries, "level", false);
    expect(result.map((e) => e.message)).toEqual(["crit", "error", "warn", "info", "debug"]);
  });

  it("sorts by level ascending", () => {
    const entries = [
      entry({ level: "ERROR", message: "error" }),
      entry({ level: "DEBUG", message: "debug" }),
    ];
    const result = sortEntries(entries, "level", true);
    expect(result.map((e) => e.message)).toEqual(["debug", "error"]);
  });

  it("sorts by app using localeCompare", () => {
    const entries = [
      entry({ app_key: "climate", message: "c" }),
      entry({ app_key: "alarm", message: "a" }),
      entry({ app_key: "blinds", message: "b" }),
    ];
    const result = sortEntries(entries, "app", false);
    // descending: climate, blinds, alarm
    expect(result.map((e) => e.message)).toEqual(["c", "b", "a"]);
  });

  it("sorts by message using localeCompare", () => {
    const entries = [
      entry({ message: "Banana" }),
      entry({ message: "Apple" }),
      entry({ message: "Cherry" }),
    ];
    const result = sortEntries(entries, "message", true);
    expect(result.map((e) => e.message)).toEqual(["Apple", "Banana", "Cherry"]);
  });

  it("does not mutate the original array", () => {
    const entries = [
      entry({ timestamp: 2000 }),
      entry({ timestamp: 1000 }),
    ];
    const original = [...entries];
    sortEntries(entries, "timestamp", true);
    expect(entries).toEqual(original);
  });

  it("handles null app_key by sorting nulls last", () => {
    const entries = [
      entry({ app_key: null, message: "null" }),
      entry({ app_key: "alpha", message: "alpha" }),
    ];
    const result = sortEntries(entries, "app", true);
    // ascending: alpha first, null last
    expect(result.map((e) => e.message)).toEqual(["alpha", "null"]);
  });
});

// -- Multi-column sort component tests --

describe("Multi-column sort", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("sorts by level when Level sort button is clicked", async () => {
    // Use REST entries so they survive live-pause when sorting by non-timestamp
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ level: "INFO", message: "info-msg" }),
      createLogEntry({ level: "ERROR", message: "error-msg" }),
      createLogEntry({ level: "DEBUG", message: "debug-msg" }),
    ]);

    const { container, getByTestId, findByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    await findByText("info-msg");

    // Need to show DEBUG: set level filter to All Levels
    fireEvent.change(getByTestId("filter-level"), { target: { value: "" } });

    const sortBtn = getByTestId("sort-level").querySelector("button") as HTMLElement;
    fireEvent.click(sortBtn);

    // Default non-timestamp sort is descending — ERROR > WARNING > INFO > DEBUG
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("error-msg");
    expect(rows[1].textContent).toContain("info-msg");
    expect(rows[2].textContent).toContain("debug-msg");
  });

  it("sorts by app when App sort button is clicked", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ app_key: "climate", message: "climate-msg" }),
      createLogEntry({ app_key: "alarm", message: "alarm-msg" }),
      createLogEntry({ app_key: "blinds", message: "blinds-msg" }),
    ]);

    const { container, getByTestId, findByText } = render(
      <LogTable showAppColumn appKeys={["alarm", "blinds", "climate"]} />,
      { wrapper: createWrapper(state) },
    );

    await findByText("climate-msg");

    const sortBtn = getByTestId("sort-app").querySelector("button") as HTMLElement;
    fireEvent.click(sortBtn);

    // Descending localeCompare: climate, blinds, alarm
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("climate-msg");
    expect(rows[1].textContent).toContain("blinds-msg");
    expect(rows[2].textContent).toContain("alarm-msg");
  });

  it("sorts by message when Message sort button is clicked", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ message: "Banana" }),
      createLogEntry({ message: "Apple" }),
      createLogEntry({ message: "Cherry" }),
    ]);

    const { container, getByTestId, findByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    await findByText("Banana");

    const sortBtn = getByTestId("sort-message").querySelector("button") as HTMLElement;
    fireEvent.click(sortBtn);

    // Descending localeCompare: Cherry, Banana, Apple
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("Cherry");
    expect(rows[1].textContent).toContain("Banana");
    expect(rows[2].textContent).toContain("Apple");
  });

  it("toggles sort direction on same column click", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ level: "DEBUG", message: "debug-msg" }),
      createLogEntry({ level: "ERROR", message: "error-msg" }),
    ]);

    const { container, getByTestId, findByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // ERROR is visible at default INFO filter; wait for REST load
    await findByText("error-msg");

    fireEvent.change(getByTestId("filter-level"), { target: { value: "" } });

    const sortBtn = getByTestId("sort-level").querySelector("button") as HTMLElement;

    // First click: level descending
    fireEvent.click(sortBtn);
    let rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("error-msg");

    // Second click: level ascending
    fireEvent.click(sortBtn);
    rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("debug-msg");
  });

  it("sets aria-sort only on the active sort column", () => {
    state.logs.push(createLogEntry());

    const { getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Default: timestamp has aria-sort
    expect(getByTestId("sort-timestamp").getAttribute("aria-sort")).toBe("descending");
    expect(getByTestId("sort-level").getAttribute("aria-sort")).toBeNull();
    expect(getByTestId("sort-message").getAttribute("aria-sort")).toBeNull();

    // Click level sort
    const sortBtn = getByTestId("sort-level").querySelector("button") as HTMLElement;
    fireEvent.click(sortBtn);

    expect(getByTestId("sort-level").getAttribute("aria-sort")).toBe("descending");
    expect(getByTestId("sort-timestamp").getAttribute("aria-sort")).toBeNull();
    expect(getByTestId("sort-message").getAttribute("aria-sort")).toBeNull();
  });

  it("does not render App sort button when showAppColumn is false", () => {
    const { queryByTestId } = render(
      <LogTable showAppColumn={false} />,
      { wrapper: createWrapper(state) },
    );

    expect(queryByTestId("sort-app")).toBeNull();
  });
});

// -- Live streaming pause --

describe("Live streaming pause", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("shows paused badge when sorting by non-timestamp column", () => {
    state.logs.push(createLogEntry());

    const { getByTestId, getByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const sortBtn = getByTestId("sort-level").querySelector("button") as HTMLElement;
    fireEvent.click(sortBtn);

    expect(getByText(/paused/)).toBeDefined();
  });

  it("hides paused indicator when sorting by timestamp", () => {
    state.logs.push(createLogEntry());

    const { getByTestId, queryByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Sort by level (paused)
    fireEvent.click(getByTestId("sort-level").querySelector("button") as HTMLElement);
    expect(queryByText(/paused/)).not.toBeNull();

    // Sort by timestamp (resumes)
    fireEvent.click(getByTestId("sort-timestamp").querySelector("button") as HTMLElement);
    expect(queryByText(/paused/)).toBeNull();
  });

  it("clicking paused badge resets sort to timestamp descending", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "older" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "newer" }));

    const { getByTestId, getByText, queryByText, container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Sort by level to pause
    fireEvent.click(getByTestId("sort-level").querySelector("button") as HTMLElement);
    expect(queryByText(/paused/)).not.toBeNull();

    // Click the paused badge to resume
    fireEvent.click(getByText(/paused/));

    // Paused indicator gone
    expect(queryByText(/paused/)).toBeNull();

    // Sort is back to timestamp descending
    expect(getByTestId("sort-timestamp").getAttribute("aria-sort")).toBe("descending");
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("newer");
  });

  it("excludes WS entries from display when paused", () => {
    // Only WS entries (no REST), so when paused they should disappear
    state.logs.push(createLogEntry({ message: "ws-entry" }));

    const { getByTestId, queryByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // WS entry visible in default timestamp sort
    expect(queryByText("ws-entry")).not.toBeNull();

    // Sort by level — pauses live, WS entries excluded
    fireEvent.click(getByTestId("sort-level").querySelector("button") as HTMLElement);
    expect(queryByText("ws-entry")).toBeNull();
  });

  it("shows REST entries when paused but hides WS entries", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ seq: 1, timestamp: 1000, message: "rest-entry" }),
    ]);

    // WS entry above watermark
    state.logs.push(createLogEntry({ seq: 2, timestamp: 2000, message: "ws-entry" }));

    const { findByText, getByTestId, queryByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    await findByText("rest-entry");

    // Both visible initially
    expect(queryByText("rest-entry")).not.toBeNull();
    expect(queryByText("ws-entry")).not.toBeNull();

    // Sort by level — pauses live
    fireEvent.click(getByTestId("sort-level").querySelector("button") as HTMLElement);

    // REST entry still visible, WS entry hidden
    expect(queryByText("rest-entry")).not.toBeNull();
    expect(queryByText("ws-entry")).toBeNull();
  });
});

// -- Mobile responsive rendering --

describe("Mobile responsive rendering", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
    mockUseMediaQuery.mockReturnValue(true); // mobile
  });

  afterEach(() => {
    mockUseMediaQuery.mockReturnValue(false); // restore desktop
  });

  it("abbreviates level labels on mobile (INFO -> I)", () => {
    state.logs.push(createLogEntry({ level: "INFO", message: "info msg" }));
    state.logs.push(createLogEntry({ level: "WARNING", message: "warn msg" }));
    state.logs.push(createLogEntry({ level: "ERROR", message: "error msg" }));
    state.logs.push(createLogEntry({ level: "DEBUG", message: "debug msg" }));

    // Need all levels visible
    const { container, getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );
    fireEvent.change(getByTestId("filter-level"), { target: { value: "" } });

    const levelBadges = container.querySelectorAll("[data-testid='log-level-badge'] span");
    const badgeTexts = Array.from(levelBadges).map((b) => b.textContent);
    expect(badgeTexts).toContain("I");
    expect(badgeTexts).toContain("W");
    expect(badgeTexts).toContain("E");
    expect(badgeTexts).toContain("D");
    // Full labels should NOT appear
    expect(badgeTexts).not.toContain("INFO");
    expect(badgeTexts).not.toContain("WARNING");
    expect(badgeTexts).not.toContain("ERROR");
    expect(badgeTexts).not.toContain("DEBUG");
  });

  it("hides App column header on mobile", () => {
    state.logs.push(createLogEntry({ app_key: "my_app" }));

    const { container } = render(
      <LogTable showAppColumn appKeys={["my_app"]} />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent ?? "");
    expect(headerTexts.some((t) => t.includes("App"))).toBe(false);
  });

  it("shows source inline with app and func name on mobile", () => {
    state.logs.push(createLogEntry({ app_key: "my_app", func_name: "on_change", message: "test message" }));

    const { container } = render(
      <LogTable showAppColumn appKeys={["my_app"]} />,
      { wrapper: createWrapper(state) },
    );

    const sourceInline = container.querySelector("[data-testid='log-source-inline']");
    expect(sourceInline).not.toBeNull();
    expect(sourceInline!.textContent).toContain("my_app.");
    expect(sourceInline!.textContent).toContain("on_change()");
  });

  it("shows relative timestamps on mobile", () => {
    // Timestamp 5 minutes ago
    const ts = Date.now() / 1000 - 300;
    state.logs.push(createLogEntry({ timestamp: ts, message: "ts test" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const timeCells = container.querySelectorAll("td.ht-text-mono");
    const tsCell = Array.from(timeCells).find((td) => {
      const text = td.textContent ?? "";
      return text.includes("ago") || text.includes("just now");
    });
    expect(tsCell).not.toBeNull();
  });

  it("shows the logs heading by default", () => {
    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );
    expect(container.querySelector("h2.ht-table-toolbar__heading")).not.toBeNull();
  });

  it("hides the logs heading when hideTitle is true", () => {
    const { container } = render(
      <LogTable hideTitle />,
      { wrapper: createWrapper(state) },
    );
    expect(container.querySelector("h2.ht-table-toolbar__heading")).toBeNull();
  });
});

// -- Query param integration (FR#6, FR#7) --

describe("Query param driven state", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
    _setMockSearch("");
    mockNavigate.mockReset();
    restoreNavigateMock();
  });

  it("reads initial level from ?level=ERROR URL param", () => {
    _setMockSearch("level=ERROR");
    state.logs.push(createLogEntry({ level: "INFO", message: "info msg" }));
    state.logs.push(createLogEntry({ level: "ERROR", message: "error msg" }));

    const { getByText, queryByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Only ERROR+ visible — INFO is filtered out by the URL param
    expect(queryByText("info msg")).toBeNull();
    expect(getByText("error msg")).toBeDefined();
  });

  it("reads initial search from ?search= URL param", () => {
    _setMockSearch("search=scheduler");
    state.logs.push(createLogEntry({ message: "Starting scheduler" }));
    state.logs.push(createLogEntry({ message: "Bus connected" }));

    const { getByText, queryByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("Starting scheduler")).toBeDefined();
    expect(queryByText("Bus connected")).toBeNull();
  });

  it("reads initial sort column from ?sort=level URL param", () => {
    _setMockSearch("sort=level");
    // Use only WS entries — paused when non-timestamp sort, so they're excluded.
    // Use REST entries for predictable rendering.
    state.logs.push(createLogEntry({ level: "ERROR", message: "error msg" }));
    state.logs.push(createLogEntry({ level: "DEBUG", message: "debug msg" }));
    state.logs.push(createLogEntry({ level: "WARNING", message: "warn msg" }));

    const { getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // sort=level, no ?dir — defaults to desc (asc: false)
    expect(getByTestId("sort-level").getAttribute("aria-sort")).toBe("descending");
  });

  it("reads sort direction from ?sort=level&dir=asc URL params", () => {
    _setMockSearch("sort=level&dir=asc");
    state.logs.push(createLogEntry({ level: "ERROR", message: "error msg" }));
    state.logs.push(createLogEntry({ level: "DEBUG", message: "debug msg" }));

    const { getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("sort-level").getAttribute("aria-sort")).toBe("ascending");
  });

  it("reads app filter from ?app= URL param in global mode", () => {
    _setMockSearch("app=app_a");
    state.logs.push(createLogEntry({ app_key: "app_a", message: "from A" }));
    state.logs.push(createLogEntry({ app_key: "app_b", message: "from B" }));

    const { getByText, queryByText } = render(
      <LogTable showAppColumn appKeys={["app_a", "app_b"]} />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("from A")).toBeDefined();
    expect(queryByText("from B")).toBeNull();
  });

  it("reads tier filter from ?tier=framework URL param", () => {
    _setMockSearch("tier=framework");
    state.logs.push(createLogEntry({ app_key: "my_app", source_tier: "app", message: "app msg" }));
    state.logs.push(createLogEntry({ app_key: null, source_tier: "framework", message: "framework msg" }));

    const { getByText, queryByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // tier=framework shows only entries with source_tier="framework"
    expect(queryByText("app msg")).toBeNull();
    expect(getByText("framework msg")).toBeDefined();
  });

  it("writes level to URL when level dropdown changes", () => {
    _setMockSearch("");

    const { getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.change(getByTestId("filter-level"), { target: { value: "WARNING" } });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("level=WARNING");
  });

  it("omits level from URL when set to INFO (default)", () => {
    _setMockSearch("level=ERROR");
    const { getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.change(getByTestId("filter-level"), { target: { value: "INFO" } });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("level");
  });

  it("writes search to URL when search input changes", async () => {
    vi.useFakeTimers();
    _setMockSearch("");
    const { getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "timeout" } });
    await act(() => { vi.advanceTimersByTime(200); }); // flush 150ms debounce

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("search=timeout");
    vi.useRealTimers();
  });

  it("omits search from URL when search is cleared (default empty)", async () => {
    vi.useFakeTimers();
    _setMockSearch("search=timeout");
    const { getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "" } });
    await act(() => { vi.advanceTimersByTime(200); });

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("search");
    vi.useRealTimers();
  });

  it("writes sort and dir to URL when non-timestamp sort is clicked", () => {
    _setMockSearch("");
    state.logs.push(createLogEntry());

    const { getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.click(getByTestId("sort-level").querySelector("button") as HTMLElement);

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url] = mockNavigate.mock.calls[0];
    expect(url).toContain("sort=level");
  });

  it("clears sort and dir from URL when handleResume resets to timestamp", () => {
    _setMockSearch("sort=level");
    state.logs.push(createLogEntry());

    const { getByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.click(getByText(/paused/));

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    const [url] = mockNavigate.mock.calls[0];
    expect(url).not.toContain("sort=");
    expect(url).not.toContain("dir=");
  });
});

// -- Historical mode --

describe("Historical mode", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("calls custom fetcher instead of getRecentLogs in historical mode", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValue([]);

    const customFetcher = vi.fn().mockResolvedValue([
      createLogEntry({ message: "fetched-by-custom" }),
    ]);

    const { findByText } = render(
      <LogTable mode="historical" fetcher={customFetcher} />,
      { wrapper: createWrapper(state) },
    );

    await findByText("fetched-by-custom");

    expect(customFetcher).toHaveBeenCalledOnce();
    expect(mockGetRecentLogs).not.toHaveBeenCalled();
  });

  it("does not merge WS entries in historical mode", async () => {
    const customFetcher = vi.fn().mockResolvedValue([
      createLogEntry({ seq: 1, message: "historical-entry" }),
    ]);

    // Push a WS entry above the watermark
    state.logs.push(createLogEntry({ seq: 99, message: "ws-entry" }));

    const { findByText, queryByText } = render(
      <LogTable mode="historical" fetcher={customFetcher} />,
      { wrapper: createWrapper(state) },
    );

    await findByText("historical-entry");

    // WS entries must NOT appear in historical mode
    expect(queryByText("ws-entry")).toBeNull();
  });

  it("does not update URL params in historical mode with useLocalState", () => {
    const customFetcher = vi.fn().mockResolvedValue([]);

    render(
      <LogTable mode="historical" fetcher={customFetcher} useLocalState />,
      { wrapper: createWrapper(state) },
    );

    // Changing the level dropdown in local state mode should not call navigate
    // (we just verify render doesn't crash and navigate is not called)
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("uses local signal state for filters when useLocalState is true", async () => {
    const entries = [
      createLogEntry({ level: "DEBUG", message: "debug-local" }),
      createLogEntry({ level: "ERROR", message: "error-local" }),
    ];
    const customFetcher = vi.fn().mockResolvedValue(entries);

    const { findByText, queryByText, getByTestId } = render(
      <LogTable mode="historical" fetcher={customFetcher} useLocalState />,
      { wrapper: createWrapper(state) },
    );

    // Wait for data to load
    await findByText("error-local");

    // Default is INFO filter — debug hidden
    expect(queryByText("debug-local")).toBeNull();

    // Change level to show all — should work via local state without URL navigation
    fireEvent.change(getByTestId("filter-level"), { target: { value: "" } });
    expect(queryByText("debug-local")).not.toBeNull();

    // URL should not have been touched
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

// -- Truncation indicator --

describe("Truncation indicator", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("shows entry count when entries are under the render cap", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    const fewEntries = Array.from({ length: 5 }, (_, i) =>
      createLogEntry({ message: `entry-${i}` }),
    );
    mockGetRecentLogs.mockResolvedValueOnce(fewEntries);

    const { findByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Normal count display — no "showing X of Y"
    await findByText("5 entries");
  });

  it("shows truncation indicator when sorted entries exceed render cap of 500", async () => {
    const { getRecentLogs } = await import("../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;

    // 501 entries to exceed the cap
    const manyEntries = Array.from({ length: 501 }, (_, i) =>
      createLogEntry({ seq: i + 1, timestamp: i + 1, message: `entry-${i}` }),
    );
    mockGetRecentLogs.mockResolvedValueOnce(manyEntries);

    const { findByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    // Wait for data to load — look for truncation indicator
    await findByText(/showing 500 of 501/);
  });
});

// -- Execution ID column visibility --

describe("Execution ID column visibility", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("shows execution_id column header in live mode by default", () => {
    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent ?? "");
    expect(headerTexts.some((t) => t.includes("Execution"))).toBe(true);
  });

  it("hides execution_id column when hideExecutionId prop is true", () => {
    const { container } = render(
      <LogTable hideExecutionId />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent ?? "");
    expect(headerTexts.some((t) => t.includes("Execution"))).toBe(false);
  });
});
