import { render } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import type { LogEntry } from "../../../api/endpoints";

// CSS modules in this project use vite-css-modules which generates hashed class
// names even in vitest (e.g. "_wrapper_abc123").  Query with attribute substring
// selectors like [class*="wrapper"] rather than exact class name matches.

vi.mock("./log-detail-drawer", () => ({
  LogDetailDrawer: (props: { selectedKey: string | null }) =>
    props.selectedKey ? <aside data-testid="drawer" role="complementary" /> : null,
}));

import { LogTableWithDrawer } from "./log-table-with-drawer";
import type { LogDrawerProps } from "./use-log-table";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEntry(seq: number): LogEntry {
  return {
    seq,
    timestamp: 1000 + seq,
    level: "INFO",
    logger_name: "test",
    func_name: "fn",
    lineno: 1,
    message: `msg-${seq}`,
    exc_info: null,
    app_key: "app",
    source_tier: "app",
  };
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LogTableWithDrawer", () => {
  describe("wrapper element", () => {
    it("renders the grid wrapper element containing a 'wrapper' class token", () => {
      const { container } = renderWithDrawer(makeDrawerProps());
      expect(container.querySelector("[class*='wrapper']")).not.toBeNull();
    });
  });

  describe("tableArea", () => {
    it("renders children inside the tableArea element", () => {
      const { getByTestId, container } = renderWithDrawer(makeDrawerProps());
      const tableArea = container.querySelector("[class*='tableArea']");
      expect(tableArea).not.toBeNull();
      expect(tableArea!.contains(getByTestId("table-content"))).toBe(true);
    });

    it("renders arbitrary children content inside tableArea", () => {
      const { getByText, container } = renderWithDrawer(makeDrawerProps(), <span>hello from children</span>);
      const tableArea = container.querySelector("[class*='tableArea']");
      expect(tableArea).not.toBeNull();
      expect(tableArea!.textContent).toContain("hello from children");
      expect(getByText("hello from children")).not.toBeNull();
    });
  });

  describe("drawerOpen class", () => {
    it("applies drawerOpen class token to wrapper when selectedKey is not null", () => {
      const { container } = renderWithDrawer(makeDrawerProps({ selectedKey: "1001-1", entries: [makeEntry(1)] }));
      const wrapper = container.querySelector("[class*='wrapper']");
      expect(wrapper).not.toBeNull();
      expect(wrapper!.className).toMatch(/drawerOpen/);
    });

    it("does NOT apply drawerOpen class when selectedKey is null", () => {
      const { container } = renderWithDrawer(makeDrawerProps({ selectedKey: null }));
      const wrapper = container.querySelector("[class*='wrapper']");
      expect(wrapper).not.toBeNull();
      expect(wrapper!.className).not.toMatch(/drawerOpen/);
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
