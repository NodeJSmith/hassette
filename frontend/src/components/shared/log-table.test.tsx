import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { h } from "preact";
import type { ComponentChildren } from "preact";
import { LogTable } from "./log-table";
import { AppStateContext } from "../../state/context";
import { createAppState, type AppState } from "../../state/create-app-state";
import type { WsLogPayload } from "../../api/ws-types";

// Mock the API endpoint for initial log fetch
vi.mock("../../api/endpoints", () => ({
  getRecentLogs: vi.fn().mockResolvedValue([]),
}));

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
    ...overrides,
  };
}

describe("LogTable", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    entrySeq = 0;
  });

  // -- Empty state --

  it("shows empty message when no logs exist", () => {
    const { getByText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    expect(getByText("No log entries.")).toBeDefined();
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

    fireEvent.change(getByTestId("filter-app"), { target: { value: "app_a" } });

    expect(getByText("from A")).toBeDefined();
    expect(queryByText("from B")).toBeNull();
  });

  it("does not show app filter when appKeys is not provided", () => {
    const { queryByTestId, getByTestId } = render(
      <LogTable showAppColumn />,
      { wrapper: createWrapper(state) },
    );

    expect(getByTestId("filter-level")).toBeDefined();
    expect(queryByTestId("filter-app")).toBeNull();
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

  it("filters by search text in message", () => {
    state.logs.push(createLogEntry({ message: "Starting scheduler" }));
    state.logs.push(createLogEntry({ message: "Bus connected" }));

    const { getByText, queryByText, getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const searchInput = getByPlaceholderText("Search...");
    fireEvent.input(searchInput, { target: { value: "scheduler" } });

    expect(getByText("Starting scheduler")).toBeDefined();
    expect(queryByText("Bus connected")).toBeNull();
  });

  it("filters by search text in logger name", () => {
    state.logs.push(createLogEntry({ logger_name: "hassette.bus", message: "msg1" }));
    state.logs.push(createLogEntry({ logger_name: "hassette.scheduler", message: "msg2" }));

    const { getByText, queryByText, getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "bus" } });

    expect(getByText("msg1")).toBeDefined();
    expect(queryByText("msg2")).toBeNull();
  });

  it("search is case-insensitive", () => {
    state.logs.push(createLogEntry({ message: "WebSocket Connected" }));

    const { getByText, getByPlaceholderText } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "websocket" } });

    expect(getByText("WebSocket Connected")).toBeDefined();
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

  it("expands log message on click", () => {
    state.logs.push(createLogEntry({ message: "Expandable message" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const messageCell = container.querySelector("[role='button'][aria-expanded]") as HTMLElement;
    expect(messageCell.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(messageCell);
    expect(messageCell.getAttribute("aria-expanded")).toBe("true");

    // Click again to collapse
    fireEvent.click(messageCell);
    expect(messageCell.getAttribute("aria-expanded")).toBe("false");
  });

  it("expands log message on Enter key", () => {
    state.logs.push(createLogEntry({ message: "Keyboard expand" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const messageCell = container.querySelector("[role='button'][aria-expanded]") as HTMLElement;
    fireEvent.keyDown(messageCell, { key: "Enter" });
    expect(messageCell.getAttribute("aria-expanded")).toBe("true");
  });

  // -- App column visibility --

  it("hides app column when showAppColumn is false", () => {
    state.logs.push(createLogEntry());

    const { container } = render(
      <LogTable showAppColumn={false} />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent);
    expect(headerTexts).not.toContain("App");
  });

  it("shows app column by default", () => {
    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const headers = container.querySelectorAll("th");
    const headerTexts = Array.from(headers).map((h) => h.textContent);
    expect(headerTexts).toContain("App");
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
    expect(sourceCells[0].textContent).toBe("on_initialize:99");
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

  // -- Level badge variants --

  it("renders danger badge for error level", () => {
    state.logs.push(createLogEntry({ level: "ERROR" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const badge = container.querySelector(".ht-badge--danger");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toBe("ERROR");
  });

  it("renders warning badge for warning level", () => {
    state.logs.push(createLogEntry({ level: "WARNING" }));

    const { container } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const badge = container.querySelector(".ht-badge--warning");
    expect(badge).not.toBeNull();
    expect(badge!.textContent).toBe("WARNING");
  });
});

describe("Dedup via seq watermark (#364)", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
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
