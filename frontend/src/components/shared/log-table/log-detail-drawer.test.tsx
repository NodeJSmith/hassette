import { act, fireEvent, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LogEntry } from "@/api/endpoints";
import { createLogEntry } from "@/test/factories";
import { createWouterMock } from "@/test/mock-wouter";

import { COPY_CONFIRM_MS } from "./constants";
import { LogDetailDrawer } from "./log-detail-drawer";
import { rowKey } from "./types";

vi.mock("@/hooks/use-media-query", () => ({
  useMediaQuery: () => false,
  BREAKPOINT_MOBILE: 768,
  BREAKPOINT_TABLET: 1024,
}));

vi.mock("wouter", () => createWouterMock());

function makeEntry(overrides: Partial<LogEntry> = {}) {
  return createLogEntry({
    app_key: "my_app",
    func_name: "on_ready",
    lineno: 42,
    message: "test message",
    ...overrides,
  });
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
    // These four tests exercise a document-level `mousedown` listener in isolation.
    // fireEvent.mouseDown is kept deliberately here (not migrated to userEvent.click):
    // the "Close detail panel" button also has its own onClick={onClose} handler, so a real
    // userEvent.click() would fire onClose via the button's own click handling regardless of
    // the outside-click listener under test, making "does NOT call onClose when clicking
    // inside the drawer" untestable in isolation.
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
    it("closes on Escape", async () => {
      const user = userEvent.setup();
      const { onClose, queryByTestId } = renderDrawer();
      const drawer = queryByTestId("log-detail-drawer")!;
      drawer.focus();
      await user.keyboard("{Escape}");
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("rendering", () => {
    it("renders nothing when selectedKey is null", () => {
      const { queryByTestId } = render(
        <LogDetailDrawer selectedKey={null} entries={[]} onClose={vi.fn()} onNavigate={vi.fn()} />,
      );
      expect(queryByTestId("log-detail-drawer")).toBeNull();
    });

    it("renders drawer with entry details when selectedKey matches", () => {
      const { queryByTestId } = renderDrawer();
      const drawer = queryByTestId("log-detail-drawer");
      expect(drawer).not.toBeNull();
      expect(drawer!.textContent).toContain("on_ready()");
      expect(drawer!.textContent).toContain("my_app");
      expect(drawer!.textContent).toContain("test message");
    });

    it("shows exception section when exc_info is present", () => {
      const entry = makeEntry({ exc_info: "Traceback (most recent call last):\nValueError: bad" });
      const { queryByTestId } = renderDrawer({ entries: [entry] });
      const drawer = queryByTestId("log-detail-drawer")!;
      expect(drawer.textContent).toContain("exception");
      expect(drawer.textContent).toContain("Traceback");
    });

    it("shows message and exception before metadata", () => {
      const entry = makeEntry({ exc_info: "Traceback (most recent call last):\nValueError: bad" });
      const { queryByTestId } = renderDrawer({ entries: [entry] });
      const text = queryByTestId("log-detail-drawer")!.textContent ?? "";

      expect(text.indexOf("message")).toBeLessThan(text.indexOf("exception"));
      expect(text.indexOf("exception")).toBeLessThan(text.indexOf("App"));
      expect(text.indexOf("test message")).toBeLessThan(text.indexOf("on_ready()"));
    });

    it("does not show exception section when exc_info is null", () => {
      const { queryByTestId } = renderDrawer();
      const drawer = queryByTestId("log-detail-drawer")!;
      expect(drawer.textContent).not.toContain("exception");
    });
  });

  describe("navigation", () => {
    it("navigates between entries with arrow buttons", async () => {
      const user = userEvent.setup();
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

      await user.click(getByLabelText("Next entry"));
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[1]));
    });

    it("navigatePrev does nothing when at the first entry (index 0)", async () => {
      const user = userEvent.setup();
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      const { getByLabelText } = renderDrawer({
        entries,
        selectedKey: rowKey(entries[0]),
        onNavigate,
      });

      await user.click(getByLabelText("Previous entry"));
      expect(onNavigate).not.toHaveBeenCalled();
    });

    it("navigateNext does nothing when at the last entry", async () => {
      const user = userEvent.setup();
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      const { getByLabelText } = renderDrawer({
        entries,
        selectedKey: rowKey(entries[1]),
        onNavigate,
      });

      await user.click(getByLabelText("Next entry"));
      expect(onNavigate).not.toHaveBeenCalled();
    });
  });

  describe("keyboard navigation", () => {
    it("ArrowLeft navigates to the previous entry", async () => {
      const user = userEvent.setup();
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[1]),
        onNavigate,
      });

      await user.keyboard("{ArrowLeft}");
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[0]));
    });

    it("ArrowUp navigates to the previous entry", async () => {
      const user = userEvent.setup();
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[1]),
        onNavigate,
      });

      await user.keyboard("{ArrowUp}");
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[0]));
    });

    it("ArrowRight navigates to the next entry", async () => {
      const user = userEvent.setup();
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[0]),
        onNavigate,
      });

      await user.keyboard("{ArrowRight}");
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[1]));
    });

    it("ArrowDown navigates to the next entry", async () => {
      const user = userEvent.setup();
      const entries = [makeEntry({ seq: 1, message: "first" }), makeEntry({ seq: 2, message: "second" })];
      const onNavigate = vi.fn();
      renderDrawer({
        entries,
        selectedKey: rowKey(entries[0]),
        onNavigate,
      });

      await user.keyboard("{ArrowDown}");
      expect(onNavigate).toHaveBeenCalledWith(rowKey(entries[1]));
    });

    it("Escape closes the drawer via keyboard", async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      renderDrawer({ onClose });
      await user.keyboard("{Escape}");
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("filtered-out state", () => {
    it("shows 'no longer visible' message when selectedKey does not match any entry", () => {
      const entries = [makeEntry({ seq: 1 })];
      const { queryByTestId } = renderDrawer({
        entries,
        selectedKey: "9999-9999",
      });
      const drawer = queryByTestId("log-detail-drawer")!;
      expect(drawer).not.toBeNull();
      expect(drawer.textContent).toContain("no longer visible");
    });
  });

  describe("CopyButton", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it("copies text to clipboard when clicked", async () => {
      // userEvent.setup() unconditionally installs its own Clipboard API stub on
      // navigator.clipboard (a getter-only accessor), so it must run before we spy on
      // writeText -- spying on the stub's own method, rather than replacing the whole
      // clipboard object, avoids fighting that installation.
      const user = userEvent.setup();
      const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
      const entry = makeEntry({ message: "copy this text" });
      const { getByLabelText } = renderDrawer({ entries: [entry] });

      await user.click(getByLabelText("Copy message"));
      expect(writeText).toHaveBeenCalledWith("copy this text");
    });

    it("shows '✓' immediately after copy and reverts after COPY_CONFIRM_MS", async () => {
      // shouldAdvanceTime lets the fake clock tick forward in near-real-time on its own,
      // which userEvent's internal event dispatch needs to settle -- without it, click()
      // hangs indefinitely waiting on scheduling work that a plain vi.useFakeTimers()
      // never advances.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const user = userEvent.setup({ delay: null });
      vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
      const entry = makeEntry({ message: "copy me" });
      const { getByLabelText } = renderDrawer({ entries: [entry] });

      const copyBtn = getByLabelText("Copy message");
      expect(copyBtn.textContent).toBe("⧉");

      // Click and flush the microtask queue so the resolved Promise runs
      await user.click(copyBtn);
      await act(async () => {
        await Promise.resolve();
      });

      expect(copyBtn.textContent).toBe("✓");

      await act(async () => {
        vi.advanceTimersByTime(COPY_CONFIRM_MS);
      });

      expect(copyBtn.textContent).toBe("⧉");
    });
  });
});
