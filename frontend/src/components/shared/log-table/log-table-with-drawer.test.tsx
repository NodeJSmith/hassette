import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createLogEntry } from "@/test/factories";

import { LogTableWithDrawer } from "./log-table-with-drawer";
import { rowKey } from "./types";
import type { LogDrawerProps } from "./use-log-table";

vi.mock("./log-detail-drawer", () => ({
  LogDetailDrawer: (props: { selectedKey: string | null }) =>
    props.selectedKey ? <aside data-testid="drawer" role="complementary" /> : null,
}));

const WRAPPER_TEST_ID = "log-table-with-drawer";
const TABLE_AREA_TEST_ID = "log-table-drawer-table-area";
const TABLE_CONTENT_TEST_ID = "table-content";
const DRAWER_TEST_ID = "drawer";
const DRAWER_OPEN_GRID_CLASS = "grid-cols-[1fr_var(--size-drawer)]";
const BASE_TIMESTAMP_MS = 1000;

function makeEntry(seq: number) {
  return createLogEntry({
    seq,
    timestamp: BASE_TIMESTAMP_MS + seq,
    message: `msg-${seq}`,
    app_key: "app",
    source_tier: "app",
  });
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

function renderWithDrawer(drawerProps: LogDrawerProps, children = <div data-testid={TABLE_CONTENT_TEST_ID} />) {
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
      expect(tableArea.contains(getByTestId(TABLE_CONTENT_TEST_ID))).toBe(true);
    });

    it("renders arbitrary children content inside tableArea", () => {
      const childText = "hello from children";
      const { getByText, getByTestId } = renderWithDrawer(makeDrawerProps(), <span>{childText}</span>);
      const tableArea = getByTestId(TABLE_AREA_TEST_ID);
      expect(tableArea.textContent).toContain(childText);
      expect(getByText(childText)).not.toBeNull();
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
