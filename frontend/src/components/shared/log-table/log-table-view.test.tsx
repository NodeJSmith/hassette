import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createLogEntry } from "@/test/factories";
import { createWouterMock } from "@/test/mock-wouter";
import { formatTimestamp } from "@/utils/format";

import type { ColumnFilters } from "../table-types";
import { DEFAULT_SORT } from "./constants";
import type { ColumnId } from "./types";

vi.mock("@/hooks/use-media-query", () => ({
  useMediaQuery: vi.fn(() => false),
  BREAKPOINT_MOBILE: 768,
}));

vi.mock("@/hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

vi.mock("wouter", () => createWouterMock());

import { LogTableView } from "./log-table-view";

function makeEntry(seq: number) {
  return createLogEntry({ seq, timestamp: 1000 + seq, message: `msg-${seq}`, app_key: "app", source_tier: "app" });
}

const DEFAULT_COLUMNS: ColumnId[] = ["level", "timestamp", "app", "message"];

const EMPTY_FILTERS: ColumnFilters = {};

function renderView(overrides: Partial<Parameters<typeof LogTableView>[0]> = {}) {
  const props = {
    visibleColumns: DEFAULT_COLUMNS,
    sort: DEFAULT_SORT,
    onSort: vi.fn(),
    columnFilters: EMPTY_FILTERS,
    entries: [],
    selectedKey: null,
    onRowClick: vi.fn(),
    isMobile: false,
    ...overrides,
  };
  return render(<LogTableView {...props} />);
}

describe("LogTableView", () => {
  describe("table root element", () => {
    it("renders a <table> with class ht-table ht-table--fixed and data-testid log-table", () => {
      const { getByTestId } = renderView();
      const table = getByTestId("log-table");
      expect(table.tagName.toLowerCase()).toBe("table");
      expect(table.className).toContain("ht-table");
      expect(table.className).toContain("ht-table--fixed");
    });
  });

  describe("colgroup", () => {
    it("renders a <colgroup> with one <col> per visible column plus the detail column", () => {
      const { getByTestId } = renderView({ visibleColumns: ["level", "timestamp", "app", "message"] });
      const table = getByTestId("log-table");
      const colgroup = table.querySelector("colgroup");
      expect(colgroup).not.toBeNull();
      const cols = colgroup!.querySelectorAll("col");
      expect(cols.length).toBe(5);
    });

    it("colgroup col count adjusts when fewer columns are provided", () => {
      const { getByTestId } = renderView({ visibleColumns: ["level", "message"] });
      const cols = getByTestId("log-table").querySelectorAll("colgroup col");
      expect(cols.length).toBe(3);
    });
  });

  describe("table header", () => {
    it("renders one <th> per visible column plus the detail header", () => {
      const { getByTestId } = renderView({ visibleColumns: ["level", "timestamp", "app", "message"] });
      const ths = getByTestId("log-table").querySelectorAll("thead th");
      expect(ths.length).toBe(5);
    });

    it("applies scope='col' and aria-label to each header", () => {
      const { getByTestId } = renderView({ visibleColumns: ["message"] });
      const th = getByTestId("log-table").querySelector("thead th")!;
      expect(th.getAttribute("scope")).toBe("col");
      expect(th.getAttribute("aria-label")).toBe("Log message");
    });

    it("renders the column label as text content", () => {
      const { getByTestId } = renderView({ visibleColumns: ["message"] });
      const th = getByTestId("log-table").querySelector("thead th")!;
      expect(th.textContent).toContain("Message");
    });

    it("marks the active sort column with aria-sort", () => {
      const { getByTestId } = renderView({
        visibleColumns: ["timestamp"],
        sort: DEFAULT_SORT,
      });
      const th = getByTestId("log-table").querySelector("thead th")!;
      expect(th.getAttribute("aria-sort")).toBe("descending");
    });

    it("does not set aria-sort on an inactive sortable column", () => {
      const { getByTestId } = renderView({
        visibleColumns: ["level"],
        sort: DEFAULT_SORT,
      });
      const th = getByTestId("log-table").querySelector("thead th")!;
      expect(th.getAttribute("aria-sort")).toBeNull();
    });

    it("clicking the sort button calls onSort", async () => {
      const user = userEvent.setup();
      const onSort = vi.fn();
      const { getByTestId } = renderView({ visibleColumns: ["level"], onSort });
      await user.click(getByTestId("sort-header-btn"));
      expect(onSort).toHaveBeenCalledWith({ key: "level", dir: "asc" });
    });
  });

  describe("tbody rows", () => {
    it("renders one row per entry", () => {
      const entries = [makeEntry(1), makeEntry(2), makeEntry(3)];
      const { getByTestId } = renderView({ entries });
      const rows = getByTestId("log-table").querySelectorAll("tbody tr");
      expect(rows.length).toBe(3);
    });

    it("renders empty tbody when entries array is empty", () => {
      const { getByTestId } = renderView({ entries: [] });
      const tbody = getByTestId("log-table").querySelector("tbody");
      expect(tbody).not.toBeNull();
      expect(tbody!.querySelectorAll("tr").length).toBe(0);
    });
  });

  describe("isSelected", () => {
    it("marks the matching row as selected when selectedKey matches", () => {
      const entry = makeEntry(5);
      // rowKey(entry) = "1005-5"
      const { getByTestId } = renderView({ entries: [entry], selectedKey: "1005-5" });
      const row = getByTestId("log-table").querySelector("tbody tr")!;
      expect(row.getAttribute("aria-current")).toBe("true");
    });

    it("does not mark a row as selected when selectedKey does not match", () => {
      const entry = makeEntry(5);
      const { getByTestId } = renderView({ entries: [entry], selectedKey: "0-0" });
      const row = getByTestId("log-table").querySelector("tbody tr")!;
      expect(row.getAttribute("aria-current")).toBeNull();
    });
  });

  describe("onRowClick", () => {
    it("calls onRowClick with the entry when a row is clicked", async () => {
      const user = userEvent.setup();
      const entry = makeEntry(7);
      const onRowClick = vi.fn();
      const { getByTestId } = renderView({ entries: [entry], onRowClick });
      await user.click(getByTestId("log-table").querySelector("tbody tr")!);
      expect(onRowClick).toHaveBeenCalledWith(entry);
    });

    it("does not call onRowClick when the detail button is clicked (row click also fires, then bubbles) but reports the entry once", async () => {
      const user = userEvent.setup();
      const entry = makeEntry(7);
      const onRowClick = vi.fn();
      const { getByLabelText } = renderView({ entries: [entry], onRowClick });
      await user.click(getByLabelText("View log detail"));
      expect(onRowClick).toHaveBeenCalledTimes(1);
      expect(onRowClick).toHaveBeenCalledWith(entry);
    });
  });

  describe("column widths — isMobile flag", () => {
    it("applies desktop widths (col.width) when isMobile is false", () => {
      const { getByTestId } = renderView({ visibleColumns: ["level"], isMobile: false });
      const col = getByTestId("log-table").querySelector("colgroup col") as HTMLElement;
      // "level" desktop width is "70px"
      expect(col.style.width).toBe("70px");
    });

    it("applies mobile widths (col.mobileWidth) when isMobile is true", () => {
      const { getByTestId } = renderView({ visibleColumns: ["level"], isMobile: true });
      const col = getByTestId("log-table").querySelector("colgroup col") as HTMLElement;
      // "level" mobile width is "32px"
      expect(col.style.width).toBe("32px");
    });
  });

  describe("detail button", () => {
    it("renders a detail button with data-roving-item", () => {
      const { getByLabelText } = renderView({ entries: [makeEntry(1)] });
      const btn = getByLabelText("View log detail");
      expect(btn.hasAttribute("data-roving-item")).toBe(true);
    });

    it("has aria-controls pointing to the drawer", () => {
      const { getByLabelText } = renderView({ entries: [makeEntry(1)] });
      const btn = getByLabelText("View log detail");
      expect(btn.getAttribute("aria-controls")).toBe("log-detail-drawer");
    });

    it("has aria-expanded='false' when the row is not selected", () => {
      const entry = makeEntry(1);
      const { getByLabelText } = renderView({ entries: [entry], selectedKey: "0-0" });
      const btn = getByLabelText("View log detail");
      expect(btn.getAttribute("aria-expanded")).toBe("false");
    });

    it("has aria-expanded='true' when the row is selected", () => {
      const entry = makeEntry(1);
      // rowKey(entry) = "1001-1"
      const { getByLabelText } = renderView({ entries: [entry], selectedKey: "1001-1" });
      const btn = getByLabelText("View log detail");
      expect(btn.getAttribute("aria-expanded")).toBe("true");
    });
  });

  describe("cell rendering — level column", () => {
    it("shows the full level text on desktop", () => {
      const entry = createLogEntry({ level: "WARNING" });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["level"], isMobile: false });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toBe("WARNING");
    });

    it("shows the abbreviated level text on mobile", () => {
      const entry = createLogEntry({ level: "WARNING" });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["level"], isMobile: true });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toBe("W");
    });
  });

  describe("cell rendering — timestamp column", () => {
    it("shows the formatted absolute timestamp on desktop", () => {
      const ts = 1700000000;
      const entry = createLogEntry({ timestamp: ts });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["timestamp"], isMobile: false });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toBe(formatTimestamp(ts));
    });

    it("shows the relative time on mobile", () => {
      const entry = createLogEntry({ timestamp: 1700000000 });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["timestamp"], isMobile: true });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toBe("2m ago");
    });
  });

  describe("cell rendering — app column", () => {
    it("renders an AppLink (anchor) when app_key is present", () => {
      const entry = createLogEntry({ app_key: "my_app" });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["app"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      const anchor = td.querySelector("a");
      expect(anchor).not.toBeNull();
      expect(anchor!.getAttribute("href")).toBe("/apps/my_app");
    });

    it("renders an em-dash when app_key is null", () => {
      const entry = createLogEntry({ app_key: null });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["app"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.querySelector("a")).toBeNull();
      expect(td.textContent).toContain("—");
    });
  });

  describe("cell rendering — instance column", () => {
    it("shows instance_name when present", () => {
      const entry = createLogEntry({ instance_name: "inst_2" });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["instance"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toContain("inst_2");
    });

    it("shows an em-dash when instance_name is null", () => {
      const entry = createLogEntry({ instance_name: null });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["instance"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toContain("—");
    });
  });

  describe("cell rendering — execution column", () => {
    it("shows the truncated execution id when present", () => {
      const entry = createLogEntry({ execution_id: "abcdef1234567890" });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["execution"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toContain("34567890");
      expect(td.textContent).not.toContain("abcdef1234567890");
    });

    it("shows an em-dash when execution_id is null", () => {
      const entry = createLogEntry({ execution_id: null });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["execution"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toContain("—");
    });

    it("renders as a link when execution_kind and handler ID are present", () => {
      const entry = createLogEntry({
        execution_id: "abcdef1234567890",
        app_key: "my_app",
        execution_kind: "handler",
        listener_id: 5,
        instance_index: 0,
      });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["execution"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      const link = td.querySelector("a");
      expect(link).not.toBeNull();
      expect(link!.getAttribute("href")).toContain("/apps/my_app/handlers/listener/5/exec/abcdef1234567890");
    });

    it("renders as plain text (no link) when execution_kind is null", () => {
      const entry = createLogEntry({
        execution_id: "abcdef1234567890",
        app_key: "my_app",
        execution_kind: null,
        listener_id: null,
      });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["execution"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.querySelector("a")).toBeNull();
      expect(td.textContent).toContain("34567890");
    });

    it("clicking the execution link does not trigger the row's onRowClick", async () => {
      const user = userEvent.setup();
      const onRowClick = vi.fn();
      const entry = createLogEntry({
        execution_id: "abcdef1234567890",
        app_key: "my_app",
        execution_kind: "handler",
        listener_id: 5,
        instance_index: 0,
      });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["execution"], onRowClick });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      const link = td.querySelector("a")!;
      await user.click(link);
      expect(onRowClick).not.toHaveBeenCalled();
    });
  });

  describe("cell rendering — function column", () => {
    it("shows func_name followed by '()'", () => {
      const entry = createLogEntry({ func_name: "on_ready" });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["function"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toBe("on_ready()");
    });
  });

  describe("cell rendering — module column", () => {
    it("shows the last segment of logger_name + ':' + lineno", () => {
      const entry = createLogEntry({ logger_name: "hassette.apps.my_app", lineno: 42 });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["module"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toBe("my_app:42");
    });

    it("uses the full logger_name when there are no dots", () => {
      const entry = createLogEntry({ logger_name: "root", lineno: 7 });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["module"] });
      const td = getByTestId("log-table").querySelector("tbody td")!;
      expect(td.textContent).toBe("root:7");
    });
  });

  describe("cell rendering — message column", () => {
    it("shows the entry's message text", () => {
      const entry = createLogEntry({ message: "hello world log" });
      const { getByTestId } = renderView({ entries: [entry], visibleColumns: ["message"] });
      const td = getByTestId("log-message-cell");
      expect(td.textContent).toContain("hello world log");
    });

    it("shows the source inline (app_key.func_name) on mobile when the app column isn't visible", () => {
      const entry = createLogEntry({ app_key: "my_app", func_name: "on_ready", message: "hello" });
      const { getByTestId } = renderView({
        entries: [entry],
        visibleColumns: ["message"],
        isMobile: true,
      });
      const td = getByTestId("log-message-cell");
      expect(td.textContent).toContain("my_app.on_ready()");
    });

    it("does not show the source inline on desktop", () => {
      const entry = createLogEntry({ app_key: "my_app", func_name: "on_ready", message: "hello" });
      const { getByTestId } = renderView({
        entries: [entry],
        visibleColumns: ["message"],
        isMobile: false,
      });
      const td = getByTestId("log-message-cell");
      expect(td.textContent).not.toContain("on_ready()");
    });

    it("does not show the source inline on mobile when the app column is visible", () => {
      const entry = createLogEntry({ app_key: "my_app", func_name: "on_ready", message: "hello" });
      const { getByTestId } = renderView({
        entries: [entry],
        visibleColumns: ["app", "message"],
        isMobile: true,
      });
      const td = getByTestId("log-message-cell");
      expect(td.textContent).not.toContain("on_ready()");
    });
  });

  describe("handleSort — timestamp default direction", () => {
    it("overrides to desc when clicking timestamp while another column is active", async () => {
      const user = userEvent.setup();
      const onSort = vi.fn();
      const { getByTestId } = renderView({
        visibleColumns: ["level", "timestamp"],
        sort: { key: "level", dir: "desc" },
        onSort,
      });
      const btn = getByTestId("sort-timestamp").querySelector("button")!;
      await user.click(btn);
      expect(onSort).toHaveBeenCalledWith({ key: "timestamp", dir: "desc" });
    });

    it("allows normal asc/desc cycling when timestamp is already active", async () => {
      const user = userEvent.setup();
      const onSort = vi.fn();
      const { getByTestId } = renderView({
        visibleColumns: ["timestamp"],
        sort: DEFAULT_SORT,
        onSort,
      });
      const btn = getByTestId("sort-timestamp").querySelector("button")!;
      await user.click(btn);
      expect(onSort).toHaveBeenCalledWith({ key: "timestamp", dir: "asc" });
    });

    it("does not override direction for non-timestamp columns", async () => {
      const user = userEvent.setup();
      const onSort = vi.fn();
      const { getByTestId } = renderView({
        visibleColumns: ["level", "timestamp"],
        sort: DEFAULT_SORT,
        onSort,
      });
      const btn = getByTestId("sort-level").querySelector("button")!;
      await user.click(btn);
      expect(onSort).toHaveBeenCalledWith({ key: "level", dir: "asc" });
    });
  });
});
