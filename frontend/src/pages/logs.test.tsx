import { signal } from "@preact/signals";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithAppState } from "../test/render-helpers";
import { LogsPage } from "./logs";

const mockSearchSignal = signal("");
const mockNavigate = vi.fn((url: string) => {
  const qIdx = url.indexOf("?");
  mockSearchSignal.value = qIdx >= 0 ? url.slice(qIdx + 1) : "";
});

vi.mock("wouter", () => ({
  useSearch: () => mockSearchSignal.value,
  useLocation: () => ["/logs", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

vi.mock("../components/shared/log-table", () => ({
  useLogTable: () => ({
    tableProps: {
      visibleColumns: [],
      sort: { key: "timestamp", dir: "desc" },
      onSort: vi.fn(),
      columnFilters: {},
      entries: [],
      selectedKey: null,
      onRowClick: vi.fn(),
      isMobile: false,
    },
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
  LogTableWithDrawer: ({ children }: { children: preact.ComponentChildren }) => (
    <div data-testid="log-table-with-drawer">{children}</div>
  ),
}));

beforeEach(() => {
  mockSearchSignal.value = "";
  mockNavigate.mockReset();
  mockNavigate.mockImplementation((url: string) => {
    const qIdx = url.indexOf("?");
    mockSearchSignal.value = qIdx >= 0 ? url.slice(qIdx + 1) : "";
  });
});

describe("LogsPage", () => {
  it("renders logs page with card container", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />);
    expect(getByTestId("logs-page")).toBeDefined();
    expect(getByTestId("logs-card")).toBeDefined();
  });

  it("renders page heading", () => {
    const { container } = renderWithAppState(<LogsPage />);
    expect(container.querySelector("h1.ht-display")?.textContent).toBe("logs");
  });

  it("renders search input", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />);
    const searchInput = getByTestId("logs-search");
    expect(searchInput).toBeDefined();
    expect(searchInput.getAttribute("aria-label")).toBe("Search logs");
  });

  it("renders LogTableWithDrawer inside the card", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />);
    expect(getByTestId("log-table-with-drawer")).toBeDefined();
  });

  it("renders footer slot in card", () => {
    const { getByTestId } = renderWithAppState(<LogsPage />);
    const card = getByTestId("logs-card");
    expect(card.querySelector("[data-footer-slot]")).not.toBeNull();
  });
});
