import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/preact";
import { h } from "preact";
import type { ComponentChildren } from "preact";
import { signal } from "@preact/signals";
import { toast } from "sonner";
import { LogTable } from "./log-table";
import { sortEntries } from "./use-log-filters";
import { resolveSortColumn, levelClass } from "./constants";
import { rowKey } from "./types";
import { getRecentLogs } from "../../../api/endpoints";
import type { LogEntry } from "../../../api/endpoints";
import { AppStateContext } from "../../../state/context";
import { createAppState, type AppState } from "../../../state/create-app-state";
import type { WsLogPayload } from "../../../api/ws-types";

// keep in sync with use-column-visibility.test.ts and hooks/use-media-query.ts
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

const mockGetRecentLogs = getRecentLogs as unknown as ReturnType<typeof vi.fn>;

const mockSearchSignal = signal("");
const mockNavigate = vi.fn((url: string) => {
  const qIdx = url.indexOf("?");
  mockSearchSignal.value = qIdx >= 0 ? url.slice(qIdx + 1) : "";
});

vi.mock("wouter", () => ({
  useSearch: () => mockSearchSignal.value,
  useLocation: () => ["/logs", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string}>{children as never}</a>,
}));

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return h(AppStateContext.Provider, { value: state }, children);
  };
}

let state: AppState;
let entrySeq = 0;

beforeEach(() => {
  state = createAppState();
  entrySeq = 0;
  mockSearchSignal.value = "";
  mockUseMediaQuery.mockReturnValue(false);
  vi.clearAllMocks();
  mockNavigate.mockImplementation((url: string) => {
    const qIdx = url.indexOf("?");
    mockSearchSignal.value = qIdx >= 0 ? url.slice(qIdx + 1) : "";
  });
});

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
  it("filters WS entries at or below the REST timestamp watermark", async () => {
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
  it("shows toast when getRecentLogs rejects", async () => {
    mockGetRecentLogs.mockRejectedValueOnce(new Error("Network timeout"));

    render(<LogTable />, { wrapper: createWrapper(state) });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Network timeout");
    });
  });
});

describe("Live pause", () => {
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
  beforeEach(() => {
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
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders column picker button in footer", () => {
    const { getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    expect(getByTestId("column-picker")).toBeDefined();
  });
});

describe("Truncation", () => {
  it("shows truncation indicator when entries exceed render cap", async () => {
    const manyEntries = Array.from({ length: 501 }, (_, i) =>
      createLogEntry({ seq: i + 1, timestamp: i + 1, message: `entry-${i}` }),
    );
    mockGetRecentLogs.mockResolvedValueOnce(manyEntries);

    const { findByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    await findByText(/showing 500 of 501/);
  });
});

describe("resolveSortColumn", () => {
  it("returns the column as-is for valid sort columns", () => {
    expect(resolveSortColumn("timestamp")).toBe("timestamp");
    expect(resolveSortColumn("level")).toBe("level");
    expect(resolveSortColumn("app")).toBe("app");
    expect(resolveSortColumn("function")).toBe("function");
    expect(resolveSortColumn("message")).toBe("message");
  });

  it("maps deprecated 'source' alias to 'function'", () => {
    expect(resolveSortColumn("source")).toBe("function");
  });

  it("falls back to 'timestamp' for invalid input", () => {
    expect(resolveSortColumn("bogus")).toBe("timestamp");
    expect(resolveSortColumn("")).toBe("timestamp");
  });
});

describe("rowKey", () => {
  it("uses timestamp-seq when seq is present", () => {
    const entry = { seq: 42, timestamp: 1000, logger_name: "test", lineno: 10 } as LogEntry;
    expect(rowKey(entry)).toBe("1000-42");
  });

  it("falls back to timestamp-logger-lineno when seq is 0", () => {
    const entry = { seq: 0, timestamp: 1000, logger_name: "hassette.apps.my_app", lineno: 55 } as LogEntry;
    expect(rowKey(entry)).toBe("1000-hassette.apps.my_app-55");
  });
});

describe("levelClass", () => {
  it("returns the matching class for a known level", () => {
    const mockStyles: Record<string, string> = { "levelINFO": "abc123", "levelERROR": "def456" };
    expect(levelClass(mockStyles, "level", "INFO")).toBe("abc123");
    expect(levelClass(mockStyles, "level", "ERROR")).toBe("def456");
  });

  it("returns undefined for unknown level", () => {
    const mockStyles: Record<string, string> = { "levelINFO": "abc123" };
    expect(levelClass(mockStyles, "level", "TRACE")).toBeUndefined();
  });
});

describe("Tier filtering", () => {
  it("filters to app-tier entries by default", () => {
    state.logs.push(createLogEntry({ source_tier: "app", message: "app msg" }));
    state.logs.push(createLogEntry({ source_tier: "framework", message: "framework msg" }));

    const { getByText, queryByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    expect(getByText("app msg")).toBeDefined();
    expect(queryByText("framework msg")).toBeNull();
  });

  it("shows all tiers when tier filter is set to 'all'", () => {
    state.logs.push(createLogEntry({ source_tier: "app", message: "app msg" }));
    state.logs.push(createLogEntry({ source_tier: "framework", message: "framework msg" }));

    const { getByText, getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });

    fireEvent.click(getByTestId("filter-app-btn"));
    const dialog = document.querySelector("[role='dialog']")!;
    const allBtn = Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "All")!;
    fireEvent.click(allBtn);

    expect(getByText("app msg")).toBeDefined();
    expect(getByText("framework msg")).toBeDefined();
  });
});

describe("App filtering", () => {
  it("filters entries by specific app key", () => {
    state.logs.push(createLogEntry({ app_key: "alpha", source_tier: "app", message: "alpha msg" }));
    state.logs.push(createLogEntry({ app_key: "beta", source_tier: "app", message: "beta msg" }));

    const { getByText, queryByText, getByTestId } = render(
      <LogTable appKeys={["alpha", "beta"]} />, { wrapper: createWrapper(state) },
    );

    fireEvent.click(getByTestId("filter-app-btn"));
    const dialog = document.querySelector("[role='dialog']")!;
    const select = dialog.querySelector("select")!;
    fireEvent.change(select, { target: { value: "alpha" } });

    expect(getByText("alpha msg")).toBeDefined();
    expect(queryByText("beta msg")).toBeNull();
  });
});

describe("Function name filtering", () => {
  it("filters entries by function name", () => {
    state.logs.push(createLogEntry({ func_name: "on_initialize", message: "init msg" }));
    state.logs.push(createLogEntry({ func_name: "on_shutdown", message: "shutdown msg" }));

    const { getByText, queryByText, getByTestId } = render(
      <LogTable />, { wrapper: createWrapper(state) },
    );

    fireEvent.click(getByTestId("filter-function-btn"));
    const dialog = document.querySelector("[role='dialog']")!;
    const input = dialog.querySelector("input[type='text']")!;
    fireEvent.input(input, { target: { value: "initialize" } });

    expect(getByText("init msg")).toBeDefined();
    expect(queryByText("shutdown msg")).toBeNull();
  });
});

describe("Search filtering", () => {
  it("updates search input value on typing", () => {
    state.logs.push(createLogEntry({ message: "findable text" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const searchInput = container.querySelector("input[aria-label='Search logs']") as HTMLInputElement;
    fireEvent.input(searchInput, { target: { value: "findable" } });

    expect(searchInput.value).toBe("findable");
  });
});

describe("Detail drawer metadata", () => {
  it("displays exception section when exc_info is present", () => {
    state.logs.push(createLogEntry({
      message: "Error occurred",
      exc_info: "Traceback (most recent call last):\n  File ...\nValueError: bad",
    }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).toContain("exception");
    expect(drawer.textContent).toContain("Traceback");
  });

  it("does not show exception section when exc_info is null", () => {
    state.logs.push(createLogEntry({ message: "Normal log", exc_info: null }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).not.toContain("exception");
  });

  it("displays app link in drawer metadata", () => {
    state.logs.push(createLogEntry({ app_key: "my_cool_app", message: "app log" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);

    const drawer = queryByRole("complementary")!;
    const link = drawer.querySelector("a[href='/apps/my_cool_app']");
    expect(link).not.toBeNull();
    expect(link!.textContent).toContain("my_cool_app");
  });

  it("displays instance name when present", () => {
    state.logs.push(createLogEntry({ instance_name: "worker-3", message: "instance log" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).toContain("Instance");
    expect(drawer.textContent).toContain("worker-3");
  });

  it("displays execution ID with copy button when present", () => {
    state.logs.push(createLogEntry({ execution_id: "exec-abc-123", message: "exec log" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).toContain("Execution");
    expect(drawer.textContent).toContain("exec-abc-123");
    const copyBtn = drawer.querySelector("button[aria-label='Copy execution ID']");
    expect(copyBtn).not.toBeNull();
  });

  it("displays function, module, line, and logger in metadata grid", () => {
    state.logs.push(createLogEntry({
      func_name: "on_ready",
      logger_name: "hassette.apps.thermostat",
      lineno: 77,
      message: "meta test",
    }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).toContain("on_ready()");
    expect(drawer.textContent).toContain("thermostat");
    expect(drawer.textContent).toContain("77");
    expect(drawer.textContent).toContain("hassette.apps.thermostat");
  });
});

describe("Detail drawer keyboard navigation", () => {
  it("navigates to next entry with ArrowDown", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "first-nav" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "second-nav" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    const rows = container.querySelectorAll("tbody tr");
    fireEvent.click(rows[0]); // newest first = second-nav

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).toContain("second-nav");

    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(drawer.textContent).toContain("first-nav");
  });

  it("navigates to previous entry with ArrowUp", () => {
    state.logs.push(createLogEntry({ timestamp: 1000, message: "first-nav" }));
    state.logs.push(createLogEntry({ timestamp: 2000, message: "second-nav" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    const rows = container.querySelectorAll("tbody tr");
    fireEvent.click(rows[1]); // first-nav (older)

    const drawer = queryByRole("complementary")!;
    expect(drawer.textContent).toContain("first-nav");

    fireEvent.keyDown(document, { key: "ArrowUp" });
    expect(drawer.textContent).toContain("second-nav");
  });
});

describe("Row keyboard interaction", () => {
  it("opens drawer when Enter is pressed on a row", () => {
    state.logs.push(createLogEntry({ message: "keyboard test" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    const row = container.querySelector("tbody tr") as HTMLElement;
    fireEvent.keyDown(row, { key: "Enter" });

    expect(queryByRole("complementary")).not.toBeNull();
  });

  it("opens drawer when Space is pressed on a row", () => {
    state.logs.push(createLogEntry({ message: "space test" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    const row = container.querySelector("tbody tr") as HTMLElement;
    fireEvent.keyDown(row, { key: " " });

    expect(queryByRole("complementary")).not.toBeNull();
  });

  it("rows have role=button and tabIndex for a11y", () => {
    state.logs.push(createLogEntry({ message: "a11y test" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const row = container.querySelector("tbody tr") as HTMLElement;
    expect(row.getAttribute("role")).toBe("button");
    expect(row.getAttribute("tabindex")).toBe("0");
  });
});

describe("Row data rendering", () => {
  it("truncates execution ID to 8 chars with ellipsis", () => {
    state.logs.push(createLogEntry({
      execution_id: "abcdef01-2345-6789-abcd-ef0123456789",
      source_tier: "app",
      message: "exec row",
    }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const cells = container.querySelectorAll("tbody td");
    const execCell = Array.from(cells).find((td) => td.textContent?.includes("abcdef01"));
    expect(execCell).toBeDefined();
    expect(execCell!.textContent).toContain("…");
  });

  it("shows mdash for null app_key in row", () => {
    state.logs.push(createLogEntry({ app_key: null, source_tier: "app", message: "no app" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const cells = container.querySelectorAll("tbody td");
    const dashCell = Array.from(cells).find((td) => td.textContent === "—");
    expect(dashCell).toBeDefined();
  });

  it("appends () to function name in row", () => {
    state.logs.push(createLogEntry({ func_name: "handle_event", message: "fn test" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const cells = container.querySelectorAll("tbody td");
    const fnCell = Array.from(cells).find((td) => td.textContent?.includes("handle_event()"));
    expect(fnCell).toBeDefined();
  });

  it("shows module short name and line number", () => {
    state.logs.push(createLogEntry({ logger_name: "hassette.apps.lights", lineno: 42, message: "module test" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const cells = container.querySelectorAll("tbody td");
    const moduleCell = Array.from(cells).find((td) => td.textContent?.includes("lights:42"));
    expect(moduleCell).toBeDefined();
  });
});

describe("Column picker interaction", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("opens column picker popover on click", () => {
    const { getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(getByTestId("column-picker"));
    expect(document.querySelector("[role='dialog']")).not.toBeNull();
  });

  it("lists all columns with checkboxes", () => {
    const { getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(getByTestId("column-picker"));

    const dialog = document.querySelector("[role='dialog']")!;
    const checkboxes = dialog.querySelectorAll("input[type='checkbox']");
    expect(checkboxes.length).toBe(8);
  });

  it("disables required columns (level, message)", () => {
    const { getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(getByTestId("column-picker"));

    const dialog = document.querySelector("[role='dialog']")!;
    const labels = dialog.querySelectorAll("label");
    const levelCheckbox = Array.from(labels)
      .find((l) => l.textContent?.includes("Level"))
      ?.querySelector("input") as HTMLInputElement;
    const messageCheckbox = Array.from(labels)
      .find((l) => l.textContent?.includes("Message"))
      ?.querySelector("input") as HTMLInputElement;

    expect(levelCheckbox.disabled).toBe(true);
    expect(messageCheckbox.disabled).toBe(true);
  });

  it("has a reset button", () => {
    const { getByTestId } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(getByTestId("column-picker"));

    const dialog = document.querySelector("[role='dialog']")!;
    const resetBtn = Array.from(dialog.querySelectorAll("button"))
      .find((b) => b.textContent === "Reset to defaults");
    expect(resetBtn).toBeDefined();
  });
});

describe("hasActiveFilter indicator", () => {
  it("does not show reset filters when no filters are active", () => {
    state.logs.push(createLogEntry());

    mockUseMediaQuery.mockReturnValue(true);
    const { getByTestId, queryByText } = render(<LogTable />, { wrapper: createWrapper(state) });
    fireEvent.click(getByTestId("mobile-filters-btn"));

    expect(queryByText("Reset to defaults")).toBeNull();
  });
});

describe("Selected row highlight", () => {
  it("marks selected row with aria-current", () => {
    state.logs.push(createLogEntry({ message: "selectable" }));

    const { container } = render(<LogTable />, { wrapper: createWrapper(state) });
    const row = container.querySelector("tbody tr") as HTMLElement;
    fireEvent.click(row);

    expect(row.getAttribute("aria-current")).toBe("true");
  });

  it("deselects row on second click", () => {
    state.logs.push(createLogEntry({ message: "toggle select" }));

    const { container, queryByRole } = render(<LogTable />, { wrapper: createWrapper(state) });
    const row = container.querySelector("tbody tr") as HTMLElement;
    fireEvent.click(row);
    expect(queryByRole("complementary")).not.toBeNull();

    fireEvent.click(row);
    expect(queryByRole("complementary")).toBeNull();
    expect(row.getAttribute("aria-current")).toBeNull();
  });
});
