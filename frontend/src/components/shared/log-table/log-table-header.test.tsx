import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import type { ColumnId, SortConfig, SortColumn } from "./types";
import type { ColumnFilters } from "../table-types";

vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: vi.fn(() => false),
  BREAKPOINT_MOBILE: 768,
}));

// Stub SortHeader so tests focus on LogTableHeader's own rendering logic.
// Emit enough attributes to let tests distinguish sort vs filter vs plain.
vi.mock("../sort-header", () => ({
  SortHeader: (props: {
    children: preact.ComponentChildren;
    onClick?: () => void;
    filterContent?: preact.ComponentChildren;
    hasActiveFilter?: boolean;
    active?: boolean;
    direction?: "asc" | "desc";
    ariaLabel?: string;
    "data-testid"?: string;
  }) => (
    <th
      data-testid={props["data-testid"]}
      aria-label={props.ariaLabel}
      data-sort-active={props.onClick !== undefined ? String(props.active ?? false) : undefined}
      data-sort-direction={props.onClick !== undefined ? props.direction : undefined}
      data-has-filter={props.filterContent !== undefined ? String(!!props.hasActiveFilter) : undefined}
    >
      {props.children}
    </th>
  ),
}));

import { LogTableHeader } from "./log-table-header";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderHeader(props: Partial<Parameters<typeof LogTableHeader>[0]> = {}) {
  const defaults = {
    visibleColumns: ["level", "timestamp", "app", "message"] as ColumnId[],
    sortConfig: { column: "timestamp" as SortColumn, asc: false },
    onSort: vi.fn(),
    columnFilters: {} as ColumnFilters,
  };
  return render(<table><LogTableHeader {...defaults} {...props} /></table>);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LogTableHeader", () => {
  describe("thead structure", () => {
    it("renders a <thead> element", () => {
      const { container } = renderHeader();
      expect(container.querySelector("thead")).not.toBeNull();
    });

    it("renders one <th> per visible column", () => {
      const { container } = renderHeader({
        visibleColumns: ["level", "timestamp", "app", "message"],
      });
      const ths = container.querySelectorAll("th");
      expect(ths.length).toBe(4);
    });

    it("renders two <th> elements when only two columns are visible", () => {
      const { container } = renderHeader({ visibleColumns: ["level", "message"] });
      expect(container.querySelectorAll("th").length).toBe(2);
    });

    it("renders all 8 <th> elements when all columns are visible", () => {
      const { container } = renderHeader({
        visibleColumns: ["level", "timestamp", "app", "instance", "execution", "function", "module", "message"],
      });
      expect(container.querySelectorAll("th").length).toBe(8);
    });
  });

  describe("column rendering — only visible columns", () => {
    it("does not render a header for columns absent from visibleColumns", () => {
      const { container } = renderHeader({ visibleColumns: ["level", "message"] });
      const ths = Array.from(container.querySelectorAll("th"));
      const labels = ths.map((th) => th.getAttribute("aria-label"));
      expect(labels).not.toContain("Timestamp");
      expect(labels).not.toContain("Application");
    });

    it("renders headers for exactly the supplied visibleColumns in order", () => {
      const { container } = renderHeader({
        visibleColumns: ["timestamp", "level"],
      });
      const ths = Array.from(container.querySelectorAll("th"));
      // COLUMN_MAP["timestamp"].ariaLabel = "Timestamp", COLUMN_MAP["level"].ariaLabel = "Log level"
      expect(ths[0].getAttribute("aria-label")).toBe("Timestamp");
      expect(ths[1].getAttribute("aria-label")).toBe("Log level");
    });
  });

  describe("sortable columns", () => {
    it("passes a sort button indicator (data-sort-active) for the 'level' column (has sortKey)", () => {
      const { container } = renderHeader({ visibleColumns: ["level"] });
      const th = container.querySelector("[data-testid='sort-level']");
      expect(th).not.toBeNull();
      expect(th!.getAttribute("data-sort-active")).not.toBeNull();
    });

    it("passes a sort button indicator (data-sort-active) for the 'timestamp' column (has sortKey)", () => {
      const { container } = renderHeader({ visibleColumns: ["timestamp"] });
      const th = container.querySelector("[data-testid='sort-timestamp']");
      expect(th).not.toBeNull();
      expect(th!.getAttribute("data-sort-active")).not.toBeNull();
    });

    it("does not pass a sort button indicator for 'instance' column (no sortKey)", () => {
      const { container } = renderHeader({ visibleColumns: ["instance"] });
      // instance has no sortKey so no data-testid="sort-*"
      const sortTh = container.querySelector("[data-testid^='sort-']");
      expect(sortTh).toBeNull();
    });

    it("does not pass a sort button indicator for 'module' column (no sortKey)", () => {
      const { container } = renderHeader({ visibleColumns: ["module"] });
      const sortTh = container.querySelector("[data-testid^='sort-']");
      expect(sortTh).toBeNull();
    });
  });

  describe("active sort direction", () => {
    it("marks the active sort column with data-sort-active='true'", () => {
      const sortConfig: SortConfig = { column: "timestamp", asc: false };
      const { container } = renderHeader({
        visibleColumns: ["level", "timestamp"],
        sortConfig,
      });
      const tsTh = container.querySelector("[data-testid='sort-timestamp']");
      expect(tsTh!.getAttribute("data-sort-active")).toBe("true");
    });

    it("marks the inactive sort column with data-sort-active='false'", () => {
      const sortConfig: SortConfig = { column: "timestamp", asc: false };
      const { container } = renderHeader({
        visibleColumns: ["level", "timestamp"],
        sortConfig,
      });
      const lvlTh = container.querySelector("[data-testid='sort-level']");
      expect(lvlTh!.getAttribute("data-sort-active")).toBe("false");
    });

    it("passes direction='desc' to the active column when asc=false", () => {
      const sortConfig: SortConfig = { column: "timestamp", asc: false };
      const { container } = renderHeader({
        visibleColumns: ["timestamp"],
        sortConfig,
      });
      const th = container.querySelector("[data-testid='sort-timestamp']");
      expect(th!.getAttribute("data-sort-direction")).toBe("desc");
    });

    it("passes direction='asc' to the active column when asc=true", () => {
      const sortConfig: SortConfig = { column: "level", asc: true };
      const { container } = renderHeader({
        visibleColumns: ["level"],
        sortConfig,
      });
      const th = container.querySelector("[data-testid='sort-level']");
      expect(th!.getAttribute("data-sort-direction")).toBe("asc");
    });

    it("passes direction='asc' to inactive sortable columns regardless of sortConfig", () => {
      const sortConfig: SortConfig = { column: "timestamp", asc: false };
      const { container } = renderHeader({
        visibleColumns: ["level", "timestamp"],
        sortConfig,
      });
      const lvlTh = container.querySelector("[data-testid='sort-level']");
      expect(lvlTh!.getAttribute("data-sort-direction")).toBe("asc");
    });
  });

  describe("filter columns", () => {
    it("renders a filter indicator (data-has-filter) when columnFilters has an entry for a column", () => {
      const columnFilters: ColumnFilters = {
        level: { active: false, label: "Level", content: <span>filter UI</span> },
      };
      const { container } = renderHeader({
        visibleColumns: ["level"],
        columnFilters,
      });
      const th = container.querySelector("th");
      expect(th!.getAttribute("data-has-filter")).not.toBeNull();
    });

    it("marks data-has-filter='true' when the filter is active", () => {
      const columnFilters: ColumnFilters = {
        level: { active: true, label: "Level", content: <span>filter UI</span> },
      };
      const { container } = renderHeader({
        visibleColumns: ["level"],
        columnFilters,
      });
      const th = container.querySelector("th");
      expect(th!.getAttribute("data-has-filter")).toBe("true");
    });

    it("marks data-has-filter='false' when the filter is inactive", () => {
      const columnFilters: ColumnFilters = {
        level: { active: false, label: "Level", content: <span>filter UI</span> },
      };
      const { container } = renderHeader({
        visibleColumns: ["level"],
        columnFilters,
      });
      const th = container.querySelector("th");
      expect(th!.getAttribute("data-has-filter")).toBe("false");
    });

    it("does not render a filter indicator for columns absent from columnFilters", () => {
      const { container } = renderHeader({
        visibleColumns: ["timestamp"],
        columnFilters: {},
      });
      const th = container.querySelector("th");
      expect(th!.getAttribute("data-has-filter")).toBeNull();
    });

    it("renders a filter-col testid for a filter-only column (no sortKey, has filter)", () => {
      const columnFilters: ColumnFilters = {
        // 'instance' has no sortKey
        instance: { active: false, label: "Instance", content: <span>filter UI</span> },
      };
      const { container } = renderHeader({
        visibleColumns: ["instance"],
        columnFilters,
      });
      const th = container.querySelector("[data-testid='filter-instance-col']");
      expect(th).not.toBeNull();
    });
  });

  describe("column label text", () => {
    it("renders the COLUMN_MAP label as text content of each header", () => {
      const { container } = renderHeader({ visibleColumns: ["message"] });
      expect(container.querySelector("th")!.textContent).toContain("Message");
    });

    it("renders 'Level' for the level column", () => {
      const { container } = renderHeader({ visibleColumns: ["level"] });
      expect(container.querySelector("th")!.textContent).toContain("Level");
    });
  });
});
