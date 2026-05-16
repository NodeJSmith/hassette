import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { createLogEntry } from "../../../test/factories";
import type { ColumnId } from "./types";

vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: vi.fn(() => false),
  BREAKPOINT_MOBILE: 768,
}));

vi.mock("../../../hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string}>{children as never}</a>,
}));

import { LogTableRow } from "./log-table-row";
import { formatTimestamp } from "../../../utils/format";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderRow(props: Partial<Parameters<typeof LogTableRow>[0]> = {}) {
  const defaults = {
    entry: createLogEntry(),
    rowKey: "1-1700000000",
    visibleColumns: ["level", "timestamp", "app", "message"] as ColumnId[],
    isSelected: false,
    onClick: vi.fn(),
  };
  return render(
    <table><tbody><LogTableRow {...defaults} {...props} /></tbody></table>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LogTableRow", () => {
  describe("row element", () => {
    it("renders a <tr> with role='button' and tabIndex=0", () => {
      const { container } = renderRow();
      const tr = container.querySelector("tr");
      expect(tr).not.toBeNull();
      expect(tr!.getAttribute("role")).toBe("button");
      expect(tr!.getAttribute("tabindex")).toBe("0");
    });

    it("does not have aria-current when not selected", () => {
      const { container } = renderRow({ isSelected: false });
      const tr = container.querySelector("tr");
      expect(tr!.getAttribute("aria-current")).toBeNull();
    });

    it("has aria-current='true' when selected", () => {
      const { container } = renderRow({ isSelected: true });
      const tr = container.querySelector("tr");
      expect(tr!.getAttribute("aria-current")).toBe("true");
    });
  });

  describe("selected class", () => {
    it("applies 'selected' class token when isSelected=true", () => {
      const { container } = renderRow({ isSelected: true });
      const tr = container.querySelector("tr");
      expect(tr!.className).toMatch(/selected/);
    });

    it("does not apply 'selected' class when isSelected=false", () => {
      const { container } = renderRow({ isSelected: false });
      const tr = container.querySelector("tr");
      expect(tr!.className).not.toMatch(/selected/);
    });
  });

  describe("column visibility", () => {
    it("only renders <td> elements for columns in visibleColumns", () => {
      const { container } = renderRow({
        visibleColumns: ["level", "message"],
      });
      const tds = container.querySelectorAll("td");
      expect(tds.length).toBe(2);
    });

    it("renders all 8 columns when all are visible", () => {
      const { container } = renderRow({
        entry: createLogEntry({
          app_key: "my_app",
          instance_name: "inst_0",
          execution_id: "abcdef1234567890",
        }),
        visibleColumns: ["level", "timestamp", "app", "instance", "execution", "function", "module", "message"],
      });
      const tds = container.querySelectorAll("td");
      expect(tds.length).toBe(8);
    });

    it("renders no cells when visibleColumns is empty", () => {
      const { container } = renderRow({ visibleColumns: [] });
      const tds = container.querySelectorAll("td");
      expect(tds.length).toBe(0);
    });
  });

  describe("level column", () => {
    it("shows level text in the level cell on desktop", () => {
      const { container } = renderRow({
        entry: createLogEntry({ level: "WARNING" }),
        visibleColumns: ["level"],
      });
      expect(container.querySelector("td")!.textContent).toContain("WARNING");
    });
  });

  describe("timestamp column", () => {
    it("shows formatted timestamp (non-mobile) via formatTimestamp", () => {
      const ts = 1700000000;
      const { container } = renderRow({
        entry: createLogEntry({ timestamp: ts }),
        visibleColumns: ["timestamp"],
      });
      const expected = formatTimestamp(ts);
      expect(container.querySelector("td")!.textContent).toContain(expected);
    });
  });

  describe("app column", () => {
    it("renders an AppLink (anchor) when app_key is present", () => {
      const { container } = renderRow({
        entry: createLogEntry({ app_key: "my_app" }),
        visibleColumns: ["app"],
      });
      const anchor = container.querySelector("a");
      expect(anchor).not.toBeNull();
      expect(anchor!.getAttribute("href")).toBe("/apps/my_app");
    });

    it("renders an em-dash when app_key is null", () => {
      const { container } = renderRow({
        entry: createLogEntry({ app_key: null }),
        visibleColumns: ["app"],
      });
      expect(container.querySelector("a")).toBeNull();
      // mdash entity renders as the — character
      expect(container.querySelector("td")!.textContent).toContain("—");
    });
  });

  describe("message column", () => {
    it("shows the entry's message text", () => {
      const { container } = renderRow({
        entry: createLogEntry({ message: "hello world log" }),
        visibleColumns: ["message"],
      });
      expect(container.querySelector("td")!.textContent).toContain("hello world log");
    });
  });

  describe("instance column", () => {
    it("shows instance_name when column is visible and value is present", () => {
      const { container } = renderRow({
        entry: createLogEntry({ instance_name: "inst_2" }),
        visibleColumns: ["instance"],
      });
      expect(container.querySelector("td")!.textContent).toContain("inst_2");
    });

    it("shows an em-dash when instance_name is null", () => {
      const { container } = renderRow({
        entry: createLogEntry({ instance_name: null }),
        visibleColumns: ["instance"],
      });
      expect(container.querySelector("td")!.textContent).toContain("—");
    });
  });

  describe("execution column", () => {
    it("shows first 8 chars + ellipsis when execution_id is present", () => {
      const { container } = renderRow({
        entry: createLogEntry({ execution_id: "abcdef1234567890" }),
        visibleColumns: ["execution"],
      });
      const text = container.querySelector("td")!.textContent;
      expect(text).toContain("abcdef12");
      expect(text).toContain("…");
      expect(text).not.toContain("abcdef1234567890");
    });

    it("shows an em-dash when execution_id is null", () => {
      const { container } = renderRow({
        entry: createLogEntry({ execution_id: null }),
        visibleColumns: ["execution"],
      });
      expect(container.querySelector("td")!.textContent).toContain("—");
    });
  });

  describe("function column", () => {
    it("shows func_name followed by '()'", () => {
      const { container } = renderRow({
        entry: createLogEntry({ func_name: "on_ready" }),
        visibleColumns: ["function"],
      });
      expect(container.querySelector("td")!.textContent).toContain("on_ready()");
    });
  });

  describe("module column", () => {
    it("shows last segment of logger_name + ':' + lineno", () => {
      const { container } = renderRow({
        entry: createLogEntry({ logger_name: "hassette.apps.my_app", lineno: 42 }),
        visibleColumns: ["module"],
      });
      expect(container.querySelector("td")!.textContent).toContain("my_app:42");
    });

    it("uses the full logger_name as module segment when there are no dots", () => {
      const { container } = renderRow({
        entry: createLogEntry({ logger_name: "root", lineno: 7 }),
        visibleColumns: ["module"],
      });
      expect(container.querySelector("td")!.textContent).toContain("root:7");
    });
  });

  describe("click and keyboard interaction", () => {
    it("calls onClick when the row is clicked", () => {
      const onClick = vi.fn();
      const { container } = renderRow({ onClick });
      fireEvent.click(container.querySelector("tr")!);
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("calls onClick on Enter keypress", () => {
      const onClick = vi.fn();
      const { container } = renderRow({ onClick });
      fireEvent.keyDown(container.querySelector("tr")!, { key: "Enter" });
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("calls onClick on Space keypress", () => {
      const onClick = vi.fn();
      const { container } = renderRow({ onClick });
      fireEvent.keyDown(container.querySelector("tr")!, { key: " " });
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("does not call onClick for other keys", () => {
      const onClick = vi.fn();
      const { container } = renderRow({ onClick });
      fireEvent.keyDown(container.querySelector("tr")!, { key: "Tab" });
      expect(onClick).not.toHaveBeenCalled();
    });
  });
});
