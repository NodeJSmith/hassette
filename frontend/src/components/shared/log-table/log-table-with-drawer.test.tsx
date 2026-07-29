import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createLogEntry } from "@/test/factories";

vi.mock("./log-detail-drawer", () => ({
  LogDetailDrawer: (props: { selectedKey: string | null }) =>
    props.selectedKey ? <aside data-testid="drawer" role="complementary" /> : null,
}));

import { LogTableWithDrawer } from "./log-table-with-drawer";
import type { LogDrawerProps } from "./use-log-table";

function makeEntry(seq: number) {
  return createLogEntry({ seq, timestamp: 1000 + seq, message: `msg-${seq}`, app_key: "app", source_tier: "app" });
}

function makeDrawerProps(overrides: Partial<LogDrawerProps> = {}): LogDrawerProps {
  return {
    selectedKey: null,
    entries: [],
    onClose: vi.fn(),
    onNavigate: vi.fn(),
    ...overrides,
  };
}

function renderWithDrawer(drawerProps: LogDrawerProps, children = <div data-testid="table-content" />) {
  return render(<LogTableWithDrawer drawerProps={drawerProps}>{children}</LogTableWithDrawer>);
}

describe("LogTableWithDrawer", () => {
  describe("wrapper element", () => {
    it("renders the grid wrapper element", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps());
      expect(getByTestId("log-table-with-drawer")).not.toBeNull();
    });
  });

  describe("tableArea", () => {
    it("renders children inside the tableArea element", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps());
      const tableArea = getByTestId("log-table-drawer-table-area");
      expect(tableArea!.contains(getByTestId("table-content"))).toBe(true);
    });

    it("renders arbitrary children content inside tableArea", () => {
      const { getByText, getByTestId } = renderWithDrawer(makeDrawerProps(), <span>hello from children</span>);
      const tableArea = getByTestId("log-table-drawer-table-area");
      expect(tableArea!.textContent).toContain("hello from children");
      expect(getByText("hello from children")).not.toBeNull();
    });
  });

  describe("open layout state", () => {
    it("switches to a two-column grid when selectedKey is not null", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps({ selectedKey: "1001-1", entries: [makeEntry(1)] }));
      expect(getByTestId("log-table-with-drawer").className).toContain("grid-cols-[1fr_var(--size-drawer)]");
    });

    it("does not switch to the drawer-open grid when selectedKey is null", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps({ selectedKey: null }));
      expect(getByTestId("log-table-with-drawer").className).not.toContain("grid-cols-[1fr_var(--size-drawer)]");
    });
  });

  describe("LogDetailDrawer", () => {
    it("renders the drawer when selectedKey is not null", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps({ selectedKey: "1001-1", entries: [makeEntry(1)] }));
      expect(getByTestId("drawer")).not.toBeNull();
    });

    it("does not render the drawer when selectedKey is null", () => {
      const { queryByTestId } = renderWithDrawer(makeDrawerProps({ selectedKey: null }));
      expect(queryByTestId("drawer")).toBeNull();
    });
  });
});
