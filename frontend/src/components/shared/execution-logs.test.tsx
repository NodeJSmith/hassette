import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { ExecutionLogs } from "./execution-logs";

vi.mock("./log-table", () => ({
  useLogTable: () => ({
    tableProps: { visibleColumns: [], sortConfig: { column: "timestamp", asc: false }, onSort: vi.fn(), columnFilters: {}, entries: [], selectedKey: null, onRowClick: vi.fn(), isMobile: false },
    drawerProps: { selectedKey: null, entries: [], onClose: vi.fn(), onNavigate: vi.fn() },
    columnFilters: {},
    countLabel: "0 entries",
    hasActiveFilter: false,
    resetFilters: vi.fn(),
    livePaused: false,
    resetSort: vi.fn(),
    columnPickerProps: { selectedColumns: [], viewportHidden: new Set(), onToggle: vi.fn(), onReset: vi.fn() },
    isMobile: false,
    isEmpty: true,
    isLoading: false,
  }),
  LogTableView: () => <div data-testid="log-table-view" />,
  LogTableWithDrawer: ({ children }: { children: preact.ComponentChildren }) => <div data-testid="log-table-with-drawer">{children}</div>,
}));

describe("ExecutionLogs", () => {
  it("renders execution-logs-section wrapper", () => {
    const { getByTestId } = render(<ExecutionLogs executionId="test-id" />);
    expect(getByTestId("execution-logs-section")).toBeDefined();
  });

  it("renders view-all-logs link with correct href", () => {
    const { getByTestId } = render(<ExecutionLogs executionId="abc-123" />);
    const link = getByTestId("view-all-logs-link") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/logs?execution_id=abc-123");
  });

  it("renders LogTableWithDrawer wrapper", () => {
    const { getByTestId } = render(<ExecutionLogs executionId="test-id" />);
    expect(getByTestId("log-table-with-drawer")).toBeDefined();
  });

  it("shows empty state when log table is empty", () => {
    const { getByText } = render(<ExecutionLogs executionId="test-id" />);
    expect(getByText("no logs for this execution")).toBeDefined();
  });
});
