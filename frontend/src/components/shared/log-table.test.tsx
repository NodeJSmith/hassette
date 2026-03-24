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
  return {
    timestamp: ++entrySeq,
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

    // All visible initially
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

  it("toggles sort direction on timestamp header click", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "older" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "newer" }));

    const { container, getByTestId } = render(
      <LogTable />,
      { wrapper: createWrapper(state) },
    );

    const rows = container.querySelectorAll("tbody tr");
    // Default sort is descending (newest first)
    expect(rows[0]?.textContent).toContain("newer");

    // Click timestamp header to toggle to ascending
    fireEvent.click(getByTestId("sort-timestamp"));

    const rowsAfter = container.querySelectorAll("tbody tr");
    expect(rowsAfter[0]?.textContent).toContain("older");
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

// Tests for REST+WS entry merging deferred until the sort bug (#403) is fixed.
// The component concatenates initialEntries (REST) + wsEntries (ring buffer)
// without sorting or deduplicating — these tests need the sort fix first.
describe.todo("REST + WS entry merging (#403)");
