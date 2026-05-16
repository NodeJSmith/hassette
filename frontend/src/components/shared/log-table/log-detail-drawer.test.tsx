import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import type { LogEntry } from "../../../api/endpoints";
import { LogDetailDrawer } from "./log-detail-drawer";
import { rowKey } from "./types";

vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: () => false,
  BREAKPOINT_MOBILE: 768,
  BREAKPOINT_TABLET: 1024,
}));

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) =>
    <a href={href as string} class={cls as string}>{children as never}</a>,
}));

function makeEntry(overrides: Partial<LogEntry> = {}): LogEntry {
  return {
    seq: 1,
    timestamp: 1000,
    level: "INFO",
    logger_name: "hassette.apps.test",
    func_name: "on_ready",
    lineno: 42,
    message: "test message",
    exc_info: null,
    app_key: "my_app",
    execution_id: null,
    instance_name: null,
    instance_index: null,
    source_tier: "app",
    ...overrides,
  } as LogEntry;
}

function renderDrawer(overrides: { entries?: LogEntry[]; selectedKey?: string | null; onClose?: () => void; onNavigate?: () => void } = {}) {
  const entry = makeEntry();
  const entries = overrides.entries ?? [entry];
  const key = overrides.selectedKey !== undefined ? overrides.selectedKey : rowKey(entries[0]);
  const onClose = overrides.onClose ?? vi.fn();
  const onNavigate = overrides.onNavigate ?? vi.fn();

  return {
    onClose,
    ...render(
      <div>
        <div data-testid="outside-area">
          <table><tbody><tr data-testid="table-row"><td>row</td></tr></tbody></table>
        </div>
        <LogDetailDrawer selectedKey={key} entries={entries} onClose={onClose} onNavigate={onNavigate} />
      </div>,
    ),
  };
}

describe("LogDetailDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("click outside to close", () => {
    it("calls onClose when clicking outside the drawer and outside tbody", () => {
      const { onClose, getByTestId } = renderDrawer();
      fireEvent.mouseDown(getByTestId("outside-area"));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("does NOT call onClose when clicking inside the drawer", () => {
      const { onClose, getByLabelText } = renderDrawer();
      fireEvent.mouseDown(getByLabelText("Close detail panel"));
      expect(onClose).not.toHaveBeenCalled();
    });

    it("does NOT call onClose when clicking a table row (tbody)", () => {
      const { onClose, getByTestId } = renderDrawer();
      fireEvent.mouseDown(getByTestId("table-row"));
      expect(onClose).not.toHaveBeenCalled();
    });

    it("does not register click-outside listener when drawer is closed", () => {
      const onClose = vi.fn();
      const { getByTestId } = render(
        <div>
          <div data-testid="outside-area" />
          <LogDetailDrawer selectedKey={null} entries={[]} onClose={onClose} onNavigate={vi.fn()} />
        </div>,
      );
      fireEvent.mouseDown(getByTestId("outside-area"));
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe("keyboard", () => {
    it("closes on Escape", () => {
      const { onClose, queryByRole } = renderDrawer();
      const drawer = queryByRole("complementary")!;
      fireEvent.keyDown(drawer, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("rendering", () => {
    it("renders nothing when selectedKey is null", () => {
      const { queryByRole } = render(
        <LogDetailDrawer selectedKey={null} entries={[]} onClose={vi.fn()} onNavigate={vi.fn()} />,
      );
      expect(queryByRole("complementary")).toBeNull();
    });

    it("renders drawer with entry details when selectedKey matches", () => {
      const { queryByRole } = renderDrawer();
      const drawer = queryByRole("complementary");
      expect(drawer).not.toBeNull();
      expect(drawer!.textContent).toContain("on_ready()");
      expect(drawer!.textContent).toContain("my_app");
      expect(drawer!.textContent).toContain("test message");
    });

    it("shows exception section when exc_info is present", () => {
      const entry = makeEntry({ exc_info: "Traceback (most recent call last):\nValueError: bad" });
      const { queryByRole } = renderDrawer({ entries: [entry] });
      const drawer = queryByRole("complementary")!;
      expect(drawer.textContent).toContain("exception");
      expect(drawer.textContent).toContain("Traceback");
    });

    it("does not show exception section when exc_info is null", () => {
      const { queryByRole } = renderDrawer();
      const drawer = queryByRole("complementary")!;
      expect(drawer.textContent).not.toContain("exception");
    });
  });

  describe("navigation", () => {
    it("navigates between entries with arrow buttons", () => {
      const entries = [
        makeEntry({ seq: 1, timestamp: 2000, message: "second" }),
        makeEntry({ seq: 2, timestamp: 1000, message: "first" }),
      ];
      const onNavigate = vi.fn();
      const { getByLabelText } = renderDrawer({
        entries,
        selectedKey: rowKey(entries[0]),
        onNavigate,
      });

      fireEvent.click(getByLabelText("Next entry"));
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[1]));
    });
  });
});
