import { act, fireEvent, render } from "@testing-library/preact";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "../../../api/endpoints";
import { LogDetailDrawer } from "./log-detail-drawer";
import { rowKey } from "./types";

vi.mock("../../../hooks/use-media-query", () => ({
  useMediaQuery: () => false,
  BREAKPOINT_MOBILE: 768,
  BREAKPOINT_TABLET: 1024,
}));

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
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

function renderDrawer(
  overrides: { entries?: LogEntry[]; selectedKey?: string | null; onClose?: () => void; onNavigate?: () => void } = {},
) {
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
          <table>
            <tbody>
              <tr data-testid="table-row">
                <td>row</td>
              </tr>
            </tbody>
          </table>
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

    it("navigatePrev does nothing when at the first entry (index 0)", () => {
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      const { getByLabelText } = renderDrawer({
        entries,
        selectedKey: rowKey(entries[0]),
        onNavigate,
      });

      fireEvent.click(getByLabelText("Previous entry"));
      expect(onNavigate).not.toHaveBeenCalled();
    });

    it("navigateNext does nothing when at the last entry", () => {
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      const { getByLabelText } = renderDrawer({
        entries,
        selectedKey: rowKey(entries[1]),
        onNavigate,
      });

      fireEvent.click(getByLabelText("Next entry"));
      expect(onNavigate).not.toHaveBeenCalled();
    });
  });

  describe("keyboard navigation", () => {
    it("ArrowLeft navigates to the previous entry", () => {
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[1]),
        onNavigate,
      });

      fireEvent.keyDown(document, { key: "ArrowLeft" });
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[0]));
    });

    it("ArrowUp navigates to the previous entry", () => {
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[1]),
        onNavigate,
      });

      fireEvent.keyDown(document, { key: "ArrowUp" });
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[0]));
    });

    it("ArrowRight navigates to the next entry", () => {
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[0]),
        onNavigate,
      });

      fireEvent.keyDown(document, { key: "ArrowRight" });
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[1]));
    });

    it("ArrowDown navigates to the next entry", () => {
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[0]),
        onNavigate,
      });

      fireEvent.keyDown(document, { key: "ArrowDown" });
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[1]));
    });

    it("Escape closes the drawer via keyboard", () => {
      const onClose = vi.fn();
      renderDrawer({ onClose });
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("filtered-out state", () => {
    it("shows 'no longer visible' message when selectedKey does not match any entry", () => {
      const entries = [makeEntry({ seq: 1 })];
      const { queryByRole } = renderDrawer({
        entries,
        selectedKey: "9999-9999",
      });
      const drawer = queryByRole("complementary")!;
      expect(drawer).not.toBeNull();
      expect(drawer.textContent).toContain("no longer visible");
    });
  });

  describe("CopyButton", () => {
    beforeEach(() => {
      Object.assign(navigator, {
        clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
      });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("copies text to clipboard when clicked", async () => {
      const entry = makeEntry({ message: "copy this text" });
      const { getByLabelText } = renderDrawer({ entries: [entry] });

      fireEvent.click(getByLabelText("Copy message"));
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("copy this text");
    });

    it("shows '✓' immediately after copy and reverts after COPY_CONFIRM_MS", async () => {
      vi.useFakeTimers();
      const entry = makeEntry({ message: "copy me" });
      const { getByLabelText } = renderDrawer({ entries: [entry] });

      const copyBtn = getByLabelText("Copy message");
      expect(copyBtn.textContent).toBe("⧉");

      // Click and flush the microtask queue so the resolved Promise runs
      fireEvent.click(copyBtn);
      await act(async () => {
        await Promise.resolve();
      });

      expect(copyBtn.textContent).toBe("✓");

      // Advance past COPY_CONFIRM_MS (1500 ms)
      await act(async () => {
        vi.advanceTimersByTime(1500);
      });

      expect(copyBtn.textContent).toBe("⧉");
    });
  });
});
