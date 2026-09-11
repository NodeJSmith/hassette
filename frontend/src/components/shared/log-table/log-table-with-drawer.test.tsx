import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createLogEntry } from "@/test/factories";

import { LogTableWithDrawer } from "./log-table-with-drawer";
import { rowKey } from "./types";
import type { LogDrawerProps } from "./use-log-table";

// vi.hoisted so the id is available inside the hoisted vi.mock factory below as well as
// in the assertions further down, keeping the stub's test id and the queries for it in sync.
const { DRAWER_TEST_ID } = vi.hoisted(() => ({ DRAWER_TEST_ID: "drawer" }));

vi.mock("./log-detail-drawer", () => ({
  LogDetailDrawer: (props: { selectedKey: string | null }) =>
    props.selectedKey ? <aside data-testid={DRAWER_TEST_ID} role="complementary" /> : null,
}));

const WRAPPER_TEST_ID = "log-table-with-drawer";
const TABLE_AREA_TEST_ID = "log-table-drawer-table-area";
const DRAWER_OPEN_GRID_CLASS = "grid-cols-[1fr_var(--size-drawer)]";

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

function makeSelectedDrawerProps(): LogDrawerProps {
  const entry = makeEntry(1);
  return makeDrawerProps({ selectedKey: rowKey(entry), entries: [entry] });
}

function renderWithDrawer(drawerProps: LogDrawerProps, children = <div data-testid="table-content" />) {
  return render(<LogTableWithDrawer drawerProps={drawerProps}>{children}</LogTableWithDrawer>);
}

describe("LogTableWithDrawer", () => {
  describe("wrapper element", () => {
    it("renders the grid wrapper element", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps());
      expect(getByTestId(WRAPPER_TEST_ID)).not.toBeNull();
    });
  });

  describe("tableArea", () => {
    it("renders children inside the tableArea element", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps());
      const tableArea = getByTestId(TABLE_AREA_TEST_ID);
      expect(tableArea.contains(getByTestId("table-content"))).toBe(true);
    });

    it("renders arbitrary children content inside tableArea", () => {
      const { getByText, getByTestId } = renderWithDrawer(makeDrawerProps(), <span>hello from children</span>);
      const tableArea = getByTestId(TABLE_AREA_TEST_ID);
      expect(tableArea.textContent).toContain("hello from children");
      expect(getByText("hello from children")).not.toBeNull();
    });
  });

  describe("open layout state", () => {
    it("switches to a two-column grid when selectedKey is not null", () => {
      const { getByTestId } = renderWithDrawer(makeSelectedDrawerProps());
      expect(getByTestId(WRAPPER_TEST_ID).className).toContain(DRAWER_OPEN_GRID_CLASS);
    });

    it("does not switch to the drawer-open grid when selectedKey is null", () => {
      const { getByTestId } = renderWithDrawer(makeDrawerProps({ selectedKey: null }));
      expect(getByTestId(WRAPPER_TEST_ID).className).not.toContain(DRAWER_OPEN_GRID_CLASS);
    });
  });

  describe("LogDetailDrawer", () => {
    it("renders the drawer when selectedKey is not null", () => {
      const { getByTestId } = renderWithDrawer(makeSelectedDrawerProps());
      expect(getByTestId(DRAWER_TEST_ID)).not.toBeNull();
    });

    it("does not render the drawer when selectedKey is null", () => {
      const { queryByTestId } = renderWithDrawer(makeDrawerProps({ selectedKey: null }));
      expect(queryByTestId(DRAWER_TEST_ID)).toBeNull();
    });
  });
});
