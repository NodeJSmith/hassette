import { fireEvent, render } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import type { LogEntry } from "../../../api/endpoints";
import type { ColumnFilters } from "../table-types";
import { DEFAULT_SORT } from "./constants";
import type { ColumnId } from "./types";

// Stub sub-components so this test focuses solely on LogTableView's own logic.
vi.mock("./log-table-header", () => ({
  LogTableHeader: () => <thead data-testid="log-table-header" />,
}));

vi.mock("./log-table-row", () => ({
  LogTableRow: (props: { rowKey: string; isSelected: boolean; onClick: () => void }) => (
    <tr data-testid={`row-${props.rowKey}`} data-selected={String(props.isSelected)} onClick={props.onClick} />
  ),
}));

// The test-setup.ts stubs matchMedia to always return false (desktop).
// For the isMobile=true tests we import the real hook and spy on it instead.
vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: vi.fn(() => false),
  BREAKPOINT_MOBILE: "(max-width: 640px)",
}));

import { LogTableView } from "./log-table-view";

function makeEntry(seq: number): LogEntry {
  return {
    seq,
    timestamp: 1000 + seq,
    level: "INFO",
    logger_name: "test",
    func_name: "fn",
    lineno: 1,
    message: `msg-${seq}`,
    exc_info: null,
    app_key: "app",
    source_tier: "app",
  };
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
    it("renders a <colgroup> with one <col> per visible column", () => {
      const { getByTestId } = renderView({ visibleColumns: ["level", "timestamp", "app", "message"] });
      const table = getByTestId("log-table");
      const colgroup = table.querySelector("colgroup");
      expect(colgroup).not.toBeNull();
      const cols = colgroup!.querySelectorAll("col");
      expect(cols.length).toBe(4);
    });

    it("colgroup col count adjusts when fewer columns are provided", () => {
      const { getByTestId } = renderView({ visibleColumns: ["level", "message"] });
      const cols = getByTestId("log-table").querySelectorAll("colgroup col");
      expect(cols.length).toBe(2);
    });
  });

  describe("LogTableHeader", () => {
    it("renders the LogTableHeader stub inside the table", () => {
      const { getByTestId } = renderView();
      expect(getByTestId("log-table-header")).not.toBeNull();
    });
  });

  describe("tbody rows", () => {
    it("renders one row stub per entry", () => {
      const entries = [makeEntry(1), makeEntry(2), makeEntry(3)];
      const { getAllByTestId } = renderView({ entries });
      // Each stub gets data-testid="row-<key>"
      const rows = getAllByTestId(/^row-/);
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
      const row = getByTestId("row-1005-5");
      expect(row.getAttribute("data-selected")).toBe("true");
    });

    it("does not mark a row as selected when selectedKey does not match", () => {
      const entry = makeEntry(5);
      const { getByTestId } = renderView({ entries: [entry], selectedKey: "0-0" });
      expect(getByTestId("row-1005-5").getAttribute("data-selected")).toBe("false");
    });

    it("marks no rows as selected when selectedKey is null", () => {
      const entries = [makeEntry(1), makeEntry(2)];
      const { getAllByTestId } = renderView({ entries, selectedKey: null });
      for (const row of getAllByTestId(/^row-/)) {
        expect(row.getAttribute("data-selected")).toBe("false");
      }
    });
  });

  describe("onRowClick", () => {
    it("calls onRowClick with the entry when a row is clicked", () => {
      const entry = makeEntry(7);
      const onRowClick = vi.fn();
      const { getByTestId } = renderView({ entries: [entry], onRowClick });
      fireEvent.click(getByTestId("row-1007-7"));
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
});
