import { fireEvent, render } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { createLogEntry } from "@/test/factories";

import type { ColumnId } from "./types";

vi.mock("@/hooks/use-media-query", () => ({
  useMediaQuery: vi.fn(() => false),
  BREAKPOINT_MOBILE: 768,
}));

vi.mock("@/hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

import { formatTimestamp } from "@/utils/format";

import { LogTableRow } from "./log-table-row";

function renderRow(props: Partial<Parameters<typeof LogTableRow>[0]> = {}) {
  const defaults = {
    entry: createLogEntry(),
    rowKey: "1-1700000000",
    visibleColumns: ["level", "timestamp", "app", "message"] as ColumnId[],
    isSelected: false,
    onClick: vi.fn(),
    tabIndex: 0 as const,
  };
  return render(
    <table>
      <tbody>
        <LogTableRow {...defaults} {...props} />
      </tbody>
    </table>,
  );
}

describe("LogTableRow", () => {
  describe("row element", () => {
    it("renders a <tr> without role='button' (proper table semantics)", () => {
      const { container } = renderRow();
      const tr = container.querySelector("tr");
      expect(tr).not.toBeNull();
      expect(tr!.getAttribute("role")).toBeNull();
    });

    it("does not have tabIndex on the row", () => {
      const { container } = renderRow({ tabIndex: 0 });
      const tr = container.querySelector("tr");
      expect(tr!.getAttribute("tabindex")).toBeNull();
    });

    it("does not have data-roving-item on the row", () => {
      const { container } = renderRow();
      const tr = container.querySelector("tr");
      expect(tr!.hasAttribute("data-roving-item")).toBe(false);
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
    it("only renders <td> elements for visible columns plus the detail cell", () => {
      const { container } = renderRow({
        visibleColumns: ["level", "message"],
      });
      const tds = container.querySelectorAll("td");
      expect(tds.length).toBe(3);
    });

    it("renders all 8 columns plus the detail cell when all are visible", () => {
      const { container } = renderRow({
        entry: createLogEntry({
          app_key: "my_app",
          instance_name: "inst_0",
          execution_id: "abcdef1234567890",
        }),
        visibleColumns: ["level", "timestamp", "app", "instance", "execution", "function", "module", "message"],
      });
      const tds = container.querySelectorAll("td");
      expect(tds.length).toBe(9);
    });

    it("renders only the detail cell when visibleColumns is empty", () => {
      const { container } = renderRow({ visibleColumns: [] });
      const tds = container.querySelectorAll("td");
      expect(tds.length).toBe(1);
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
    it("shows last 8 chars + leading ellipsis when execution_id is present", () => {
      const { container } = renderRow({
        entry: createLogEntry({ execution_id: "abcdef1234567890" }),
        visibleColumns: ["execution"],
      });
      const text = container.querySelector("td")!.textContent;
      expect(text).toContain("34567890");
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

    it("renders as a link when execution_kind and handler ID are present", () => {
      const { container } = renderRow({
        entry: createLogEntry({
          execution_id: "abcdef1234567890",
          app_key: "my_app",
          execution_kind: "handler",
          listener_id: 5,
          instance_index: 0,
        }),
        visibleColumns: ["execution"],
      });
      const link = container.querySelector("a");
      expect(link).not.toBeNull();
      expect(link!.getAttribute("href")).toContain("/apps/my_app/handlers/listener/5/exec/abcdef1234567890");
      expect(link!.textContent).toContain("34567890");
    });

    it("renders as a link for job execution_kind", () => {
      const { container } = renderRow({
        entry: createLogEntry({
          execution_id: "job-exec-id-12345",
          app_key: "my_app",
          execution_kind: "job",
          job_id: 3,
          instance_index: null,
        }),
        visibleColumns: ["execution"],
      });
      const link = container.querySelector("a");
      expect(link).not.toBeNull();
      expect(link!.getAttribute("href")).toContain("/apps/my_app/handlers/job/3/exec/job-exec-id-12345");
    });

    it("renders as plain text when execution_kind is null (no link)", () => {
      const { container } = renderRow({
        entry: createLogEntry({
          execution_id: "abcdef1234567890",
          app_key: "my_app",
          execution_kind: null,
          listener_id: null,
        }),
        visibleColumns: ["execution"],
      });
      expect(container.querySelector("a")).toBeNull();
      expect(container.querySelector("td")!.textContent).toContain("34567890");
    });

    it("click on execution link does not trigger row click", () => {
      const onClick = vi.fn();
      const { container } = renderRow({
        entry: createLogEntry({
          execution_id: "abcdef1234567890",
          app_key: "my_app",
          execution_kind: "handler",
          listener_id: 5,
          instance_index: 0,
        }),
        visibleColumns: ["execution"],
        onClick,
      });
      const link = container.querySelector("a")!;
      fireEvent.click(link);
      expect(onClick).not.toHaveBeenCalled();
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

  describe("detail button", () => {
    it("renders a detail button with data-roving-item and tabIndex", () => {
      const { container } = renderRow({ tabIndex: 0 });
      const btn = container.querySelector("button[aria-label='View log detail']");
      expect(btn).not.toBeNull();
      expect(btn!.getAttribute("tabindex")).toBe("0");
      expect(btn!.hasAttribute("data-roving-item")).toBe(true);
    });

    it("passes tabIndex=-1 to the detail button", () => {
      const { container } = renderRow({ tabIndex: -1 });
      const btn = container.querySelector("button[aria-label='View log detail']");
      expect(btn!.getAttribute("tabindex")).toBe("-1");
    });

    it("has aria-expanded=false when not selected", () => {
      const { container } = renderRow({ isSelected: false });
      const btn = container.querySelector("button[aria-label='View log detail']");
      expect(btn!.getAttribute("aria-expanded")).toBe("false");
    });

    it("has aria-expanded=true when selected", () => {
      const { container } = renderRow({ isSelected: true });
      const btn = container.querySelector("button[aria-label='View log detail']");
      expect(btn!.getAttribute("aria-expanded")).toBe("true");
    });

    it("calls onClick when the detail button is clicked", () => {
      const onClick = vi.fn();
      const { container } = renderRow({ onClick });
      fireEvent.click(container.querySelector("button[aria-label='View log detail']")!);
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("has aria-controls pointing to the drawer", () => {
      const { container } = renderRow();
      const btn = container.querySelector("button[aria-label='View log detail']");
      expect(btn!.getAttribute("aria-controls")).toBe("log-detail-drawer");
    });
  });

  describe("row click behavior", () => {
    it("calls onClick when a non-interactive area of the row is clicked", () => {
      const onClick = vi.fn();
      const { container } = renderRow({
        onClick,
        visibleColumns: ["message"],
      });
      const messageCell = container.querySelectorAll("td")[0];
      fireEvent.click(messageCell);
      expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("does not call onClick when a link inside the row is clicked", () => {
      const onClick = vi.fn();
      const { container } = renderRow({
        entry: createLogEntry({ app_key: "my_app" }),
        visibleColumns: ["app"],
        onClick,
      });
      const link = container.querySelector("a")!;
      fireEvent.click(link);
      expect(onClick).not.toHaveBeenCalled();
    });
  });
});
