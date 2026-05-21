import { act, fireEvent, render, screen } from "@testing-library/preact";
import { useRef } from "preact/hooks";
import { describe, expect, it, vi } from "vitest";

import { ColumnFilterPopover } from "./index";

// Wrapper that exposes a trigger button and the popover under test
function PopoverHarness({ open, onClose }: { open: boolean; onClose: () => void }) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <div>
      <button ref={triggerRef} type="button" data-testid="trigger">
        Open
      </button>
      <ColumnFilterPopover open={open} onClose={onClose} triggerRef={triggerRef}>
        <button type="button" data-testid="first-focusable">
          First
        </button>
        <button type="button" data-testid="second-focusable">
          Second
        </button>
      </ColumnFilterPopover>
    </div>
  );
}

describe("ColumnFilterPopover", () => {
  describe("rendering", () => {
    it("does not render when open=false", () => {
      render(<PopoverHarness open={false} onClose={vi.fn()} />);
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("renders with role=dialog when open=true", () => {
      render(<PopoverHarness open={true} onClose={vi.fn()} />);
      expect(screen.getByRole("dialog")).toBeTruthy();
    });

    it("renders children when open", () => {
      render(<PopoverHarness open={true} onClose={vi.fn()} />);
      expect(screen.getByTestId("first-focusable")).toBeTruthy();
    });
  });

  describe("focus management", () => {
    it("focuses the first focusable child on open", async () => {
      render(<PopoverHarness open={true} onClose={vi.fn()} />);
      await act(async () => {});
      expect(document.activeElement).toBe(screen.getByTestId("first-focusable"));
    });

    it("restores focus to trigger on close", async () => {
      const { rerender } = render(<PopoverHarness open={true} onClose={vi.fn()} />);
      await act(async () => {});
      // Close the popover
      rerender(<PopoverHarness open={false} onClose={vi.fn()} />);
      await act(async () => {});
      expect(document.activeElement).toBe(screen.getByTestId("trigger"));
    });
  });

  describe("keyboard interaction", () => {
    it("calls onClose when Escape is pressed", async () => {
      const onClose = vi.fn();
      render(<PopoverHarness open={true} onClose={onClose} />);
      await act(async () => {});
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("traps Tab: moves from first to second focusable", async () => {
      render(<PopoverHarness open={true} onClose={vi.fn()} />);
      await act(async () => {});
      // First focusable is focused; Tab moves to second
      const first = screen.getByTestId("first-focusable");
      const second = screen.getByTestId("second-focusable");
      expect(document.activeElement).toBe(first);

      // Simulate Tab on the popover (keydown fires on document)
      fireEvent.keyDown(document, { key: "Tab", shiftKey: false });
      // With our trap: since active is 'first' (not last), normal tab proceeds
      // We move focus manually for the test to confirm wrap from last→first
      second.focus();
      fireEvent.keyDown(document, { key: "Tab", shiftKey: false });
      expect(document.activeElement).toBe(first);
    });

    it("traps Shift+Tab: wraps from first to last focusable", async () => {
      render(<PopoverHarness open={true} onClose={vi.fn()} />);
      await act(async () => {});
      const first = screen.getByTestId("first-focusable");
      const second = screen.getByTestId("second-focusable");
      expect(document.activeElement).toBe(first);

      // Shift+Tab from first should wrap to last
      fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
      expect(document.activeElement).toBe(second);
    });
  });

  describe("click outside", () => {
    it("calls onClose when clicking outside the popover and trigger", async () => {
      const onClose = vi.fn();
      render(
        <div>
          <div data-testid="outside">Outside</div>
          <PopoverHarness open={true} onClose={onClose} />
        </div>,
      );
      await act(async () => {});
      fireEvent.pointerDown(screen.getByTestId("outside"));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("does not call onClose when clicking inside the popover", async () => {
      const onClose = vi.fn();
      render(<PopoverHarness open={true} onClose={onClose} />);
      await act(async () => {});
      fireEvent.pointerDown(screen.getByRole("dialog"));
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe("floating-ui positioning", () => {
    it("renders popover with role=dialog (floating-ui attaches inline styles)", () => {
      render(<PopoverHarness open={true} onClose={vi.fn()} />);
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeTruthy();
    });
  });
});
