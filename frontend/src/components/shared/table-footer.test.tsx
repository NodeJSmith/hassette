import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/preact";
import { TableFooter } from "./table-footer";
import type { ColumnFilters } from "./table-types";

// useMediaQuery reads window.matchMedia; jsdom returns false by default (desktop).
// We mock it to simulate mobile when needed.
function mockMobile(isMobile: boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
    matches: isMobile,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("TableFooter", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  describe("count display", () => {
    it("renders the count prop", () => {
      render(<TableFooter count="10 apps" />);
      expect(screen.getByText("10 apps")).toBeTruthy();
    });

    it("renders complex count children", () => {
      render(
        <TableFooter count={<span data-testid="count-node">19 handlers</span>} />,
      );
      expect(screen.getByTestId("count-node")).toBeTruthy();
    });
  });

  describe("extras slot", () => {
    it("renders extras when provided", () => {
      render(
        <TableFooter
          count="5 items"
          extras={<button type="button" data-testid="extra-btn">Extra</button>}
        />,
      );
      expect(screen.getByTestId("extra-btn")).toBeTruthy();
    });

    it("does not render extras slot when omitted", () => {
      render(<TableFooter count="5 items" />);
      expect(screen.queryByTestId("extra-btn")).toBeNull();
    });
  });

  describe("mobile filter panel", () => {
    it("does not show the mobile filter button on desktop", () => {
      mockMobile(false);
      const filters: ColumnFilters = {
        status: {
          active: false,
          label: "Status",
          content: <div>status options</div>,
        },
      };
      render(<TableFooter count="5 apps" columnFilters={filters} />);
      expect(screen.queryByRole("button", { name: /open filters/i })).toBeNull();
    });

    it("shows the mobile filter button on mobile when columnFilters provided", () => {
      mockMobile(true);
      const filters: ColumnFilters = {
        status: {
          active: false,
          label: "Status",
          content: <div>status options</div>,
        },
      };
      render(<TableFooter count="5 apps" columnFilters={filters} />);
      expect(screen.getByRole("button", { name: /open filters/i })).toBeTruthy();
    });

    it("opens the mobile filter panel when filter button is clicked", async () => {
      mockMobile(true);
      const filters: ColumnFilters = {
        status: {
          active: false,
          label: "Status",
          content: <div data-testid="status-content">status options</div>,
        },
      };
      render(<TableFooter count="5 apps" columnFilters={filters} />);
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /open filters/i }));
      });
      expect(screen.getByTestId("status-content")).toBeTruthy();
    });

    it("renders column filter label in mobile panel", async () => {
      mockMobile(true);
      const filters: ColumnFilters = {
        status: {
          active: false,
          label: "Status",
          content: <div>status options</div>,
        },
      };
      render(<TableFooter count="5 apps" columnFilters={filters} />);
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /open filters/i }));
      });
      expect(screen.getByText("Status")).toBeTruthy();
    });

    it("shows active dot on filter button when any filter is active", () => {
      mockMobile(true);
      const filters: ColumnFilters = {
        status: {
          active: true,
          label: "Status",
          content: <div>status options</div>,
        },
      };
      render(<TableFooter count="5 apps" columnFilters={filters} />);
      expect(screen.getByTestId("filter-icon-dot")).toBeTruthy();
    });

    it("shows reset button in mobile panel when onResetFilters provided and a filter is active", async () => {
      mockMobile(true);
      const onReset = vi.fn();
      const filters: ColumnFilters = {
        status: { active: true, label: "Status", content: <div>opts</div> },
      };
      render(
        <TableFooter
          count="5 apps"
          columnFilters={filters}
          onResetFilters={onReset}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /open filters/i }));
      });
      const resetBtn = screen.getByRole("button", { name: /reset/i });
      fireEvent.click(resetBtn);
      expect(onReset).toHaveBeenCalledTimes(1);
    });

    it("renders multiple filter groups from columnFilters", async () => {
      mockMobile(true);
      const filters: ColumnFilters = {
        status: {
          active: false,
          label: "Status",
          content: <div data-testid="status-content">status</div>,
        },
        kind: {
          active: false,
          label: "Kind",
          content: <div data-testid="kind-content">kind</div>,
        },
      };
      render(<TableFooter count="5 apps" columnFilters={filters} />);
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /open filters/i }));
      });
      expect(screen.getByTestId("status-content")).toBeTruthy();
      expect(screen.getByTestId("kind-content")).toBeTruthy();
    });
  });
});
