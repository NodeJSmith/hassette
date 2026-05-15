import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent, act, waitFor } from "@testing-library/preact";
import { h } from "preact";
import type { ComponentChildren } from "preact";
import { toast } from "sonner";
import { LogTable } from "./log-table";
import { sortEntries } from "./use-log-filters";
import type { LogEntry } from "../../../api/endpoints";
import { AppStateContext } from "../../../state/context";
import { createAppState, type AppState } from "../../../state/create-app-state";
import type { WsLogPayload } from "../../../api/ws-types";

const mockUseMediaQuery = vi.fn((_maxWidth: number) => false);
vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: (maxWidth: number) => mockUseMediaQuery(maxWidth),
  BREAKPOINT_MOBILE: 768,
  BREAKPOINT_TABLET: 1024,
}));

vi.mock("../../../api/endpoints", () => ({
  getRecentLogs: vi.fn().mockResolvedValue([]),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

import { signal as _signal } from "@preact/signals";
const mockSearchSignal = _signal("");
const _setMockSearch = (v: string) => { mockSearchSignal.value = v; };
const mockNavigate = vi.fn((url: string) => {
  const qIdx = url.indexOf("?");
  _setMockSearch(qIdx >= 0 ? url.slice(qIdx + 1) : "");
});
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

beforeEach(() => {
  _setMockSearch("");
  mockNavigate.mockReset();
  restoreNavigateMock();
  mockUseMediaQuery.mockReturnValue(false);
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

  it("shows empty message when no logs exist", async () => {
    const { findByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    expect(await findByText("no log lines in window")).toBeDefined();
  });

  it("renders log entries from the ring buffer", () => {
    state.logs.push(createLogEntry({ message: "Hello from WS" }));
    const { getByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    expect(getByText("Hello from WS")).toBeDefined();
  });

  it("shows entry count in footer", () => {
    state.logs.push(createLogEntry({ message: "Entry 1" }));
    state.logs.push(createLogEntry({ message: "Entry 2" }));
    const { getByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    expect(getByText("2 entries")).toBeDefined();
  });

  it("shows singular count for 1 entry", () => {
    state.logs.push(createLogEntry());
    const { getByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    expect(getByText("1 entry")).toBeDefined();
  });
});

describe("Level filtering", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("filters entries by minimum level via header filter", () => {
    state.logs.push(createLogEntry({ level: "DEBUG", message: "debug msg" }));
    state.logs.push(createLogEntry({ level: "INFO", message: "info msg" }));
    state.logs.push(createLogEntry({ level: "ERROR", message: "error msg" }));

    const { getByText, queryByText, getByTestId } = render(
      <LogTable />, { wrapper: createWrapper(state) },
    );

    expect(queryByText("debug msg")).toBeNull();
    expect(getByText("info msg")).toBeDefined();
    expect(getByText("error msg")).toBeDefined();

    fireEvent.click(getByTestId("filter-level-btn"));
    const dialog = document.querySelector("[role='dialog']")!;
    fireEvent.change(dialog.querySelector("select")!, { target: { value: "" } });
    expect(getByText("debug msg")).toBeDefined();
  });
});

describe("Sorting", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("sorts by timestamp descending by default", () => {
    state.logs.push(createLogEntry({ timestamp: 2000, message: "mid" }));
    state.logs.push(createLogEntry({ timestamp: 1000, message: "oldest" }));
    state.logs.push(createLogEntry({ timestamp: 3000, message: "newest" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("newest");
    expect(rows[1].textContent).toContain("mid");
    expect(rows[2].textContent).toContain("oldest");
  });

  it("toggles sort direction on timestamp header click", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "older" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "newer" }));

    const { container, getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    const sortBtn = getByTestId("sort-timestamp") as HTMLElement;
    fireEvent.click(sortBtn);

    const rowsAfter = container.querySelectorAll("tbody tr");
    expect(rowsAfter[0].textContent).toContain("older");
  });

  it("sets aria-sort on active column", () => {
    state.logs.push(createLogEntry());
    const { getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    const th = getByTestId("sort-timestamp").closest("th")!;
    expect(th.getAttribute("aria-sort")).toBe("descending");
  });
});

describe("Row click opens detail drawer", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("opens drawer on row click and shows entry details", () => {
    state.logs.push(createLogEntry({
      message: "Test detail message",
      func_name: "on_initialize",
      logger_name: "hassette.apps.my_app",
      lineno: 99,
    }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    const row = container.querySelector("tbody tr") as HTMLElement;
    fireEvent.click(row);

    const drawer = queryByRole("complementary");
    expect(drawer).not.toBeNull();
    expect(drawer!.textContent).toContain("on_initialize()");
    expect(drawer!.textContent).toContain("my_app");
    expect(drawer!.textContent).toContain("Test detail message");
  });

  it("closes drawer on close button click", () => {
    state.logs.push(createLogEntry({ message: "Closeable msg" }));

    const { container, getByLabelText, queryByRole } = render(
      <LogTable />, { wrapper: createWrapper(state) },
    );
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);

    expect(queryByRole("complementary")).not.toBeNull();

    fireEvent.click(getByLabelText("Close detail panel"));
    expect(queryByRole("complementary")).toBeNull();
  });

  it("closes drawer on Escape key", () => {
    state.logs.push(createLogEntry({ message: "Escape test" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);
    expect(queryByRole("complementary")).not.toBeNull();

    const drawer = queryByRole("complementary")!;
    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(queryByRole("complementary")).toBeNull();
  });
});

describe("Detail drawer navigation", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("navigates between entries with arrow buttons", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "first-entry" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "second-entry" }));

    const { container, getByLabelText, queryByRole } = render(
      <LogTable />, { wrapper: createWrapper(state) },
    );

    const rows = container.querySelectorAll("tbody tr");
    fireEvent.click(rows[0]); // click "second-entry" (newest first)

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).toContain("second-entry");

    fireEvent.click(getByLabelText("Next entry"));
    expect(drawer.textContent).toContain("first-entry");
  });
});

describe("sortEntries", () => {
  function entry(overrides: Partial<LogEntry>): LogEntry {
    return {
      seq: 1, timestamp: 1000, level: "INFO", logger_name: "test",
      func_name: "fn", lineno: 1, message: "msg", exc_info: null, app_key: "app",
      ...overrides,
    };
  }

  it("sorts by timestamp descending", () => {
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

  it("sorts by function name", () => {
    const entries = [
      entry({ func_name: "charlie", message: "c" }),
      entry({ func_name: "alpha", message: "a" }),
      entry({ func_name: "bravo", message: "b" }),
    ];
    const result = sortEntries(entries, "function", true);
    expect(result.map((e) => e.message)).toEqual(["a", "b", "c"]);
  });

  it("does not mutate the original array", () => {
    const entries = [entry({ timestamp: 2000 }), entry({ timestamp: 1000 })];
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
    expect(result.map((e) => e.message)).toEqual(["alpha", "null"]);
  });
});

describe("REST + WS merge", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("filters WS entries at or below the REST timestamp watermark", async () => {
    const { getRecentLogs } = await import("../../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ seq: 1, timestamp: 1000, message: "rest-1" }),
      createLogEntry({ seq: 5, timestamp: 5000, message: "rest-5" }),
    ]);

    state.logs.push(createLogEntry({ seq: 3, timestamp: 3000, message: "ws-3" }));
    state.logs.push(createLogEntry({ seq: 6, timestamp: 6000, message: "ws-6" }));

    const { findByText, queryByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    await findByText("rest-1");

    expect(queryByText("ws-3")).toBeNull();
    expect(queryByText("ws-6")).not.toBeNull();
  });

  it("merges REST and WS entries in sorted order", async () => {
    const { getRecentLogs } = await import("../../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockResolvedValueOnce([
      createLogEntry({ timestamp: 1000, message: "rest-old" }),
      createLogEntry({ timestamp: 2000, message: "rest-new" }),
    ]);

    state.logs.push(createLogEntry({ timestamp: 3000, message: "ws-newer" }));
    state.logs.push(createLogEntry({ timestamp: 4000, message: "ws-newest" }));

    const { container, findByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    await findByText("rest-old");

    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("ws-newest");
    expect(rows[3].textContent).toContain("rest-old");
  });
});

describe("Error handling", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("shows toast when getRecentLogs rejects", async () => {
    const { getRecentLogs } = await import("../../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    mockGetRecentLogs.mockRejectedValueOnce(new Error("Network timeout"));

    render(<LogTable />, { wrapper: createWrapper(state) });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Network timeout");
    });
  });
});

describe("Live pause", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("shows paused indicator when sorting by non-timestamp column", () => {
    state.logs.push(createLogEntry());

    const { getByTestId, getByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(getByTestId("sort-level"));
    expect(getByText(/paused/)).toBeDefined();
  });

  it("clicking paused indicator resets sort", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "older" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "newer" }));

    const { getByTestId, getByText, queryByText, container } = render(
      <LogTable />, { wrapper: createWrapper(state) },
    );

    fireEvent.click(getByTestId("sort-level"));
    expect(queryByText(/paused/)).not.toBeNull();

    fireEvent.click(getByText(/paused/));
    expect(queryByText(/paused/)).toBeNull();

    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].textContent).toContain("newer");
  });
});

describe("Mobile responsive", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
    mockUseMediaQuery.mockReturnValue(true);
  });

  it("abbreviates level labels on mobile", () => {
    state.logs.push(createLogEntry({ level: "INFO", message: "info msg" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const levelCells = container.querySelectorAll("td");
    const levelTexts = Array.from(levelCells).map((c) => c.textContent);
    expect(levelTexts.some((t) => t?.includes("I"))).toBe(true);
    expect(levelTexts.some((t) => t?.includes("INFO"))).toBe(false);
  });

  it("shows relative timestamps on mobile", () => {
    const ts = Date.now() / 1000 - 300;
    state.logs.push(createLogEntry({ timestamp: ts, message: "ts test" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const cells = container.querySelectorAll("td");
    const hasRelative = Array.from(cells).some((td) => {
      const text = td.textContent ?? "";
      return text.includes("ago") || text.includes("just now");
    });
    expect(hasRelative).toBe(true);
  });
});

describe("Column picker", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
    localStorage.clear();
  });

  it("renders column picker button in footer", () => {
    const { getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    expect(getByTestId("column-picker")).toBeDefined();
  });
});

describe("Truncation", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    vi.clearAllMocks();
    restoreNavigateMock();
    entrySeq = 0;
  });

  it("shows truncation indicator when entries exceed render cap", async () => {
    const { getRecentLogs } = await import("../../../api/endpoints");
    const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;
    const manyEntries = Array.from({ length: 501 }, (_, i) =>
      createLogEntry({ seq: i + 1, timestamp: i + 1, message: `entry-${i}` }),
    );
    mockGetRecentLogs.mockResolvedValueOnce(manyEntries);

    const { findByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    await findByText(/showing 500 of 501/);
  });
});
