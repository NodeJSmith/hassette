import { signal } from "@preact/signals";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createManifest } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import type { AppDetailTab } from "../utils/app-routes";
import { AppDetailPage } from "./app-detail";
import { setupApi } from "./app-detail.test-helpers";

// Mutable search string for tests that need to control query params
let mockSearchString = "";
const mockNavigate = vi.fn();

// Stub wouter navigation
vi.mock("wouter", () =>
  createWouterMock({
    useLocation: () => ["/apps/test_app", mockNavigate],
    useSearch: () => mockSearchString,
  }),
);

// Stub child components not under test
vi.mock("../components/shared/error-banner", () => ({
  ErrorBanner: ({ "data-testid": testId }: { "data-testid"?: string }) => (
    <div data-testid={testId ?? "error-banner"} />
  ),
}));
// Capture props from HandlersTab so tests can invoke callbacks and assert prop values
let capturedOnSwitchToCode: ((line?: number) => void) | undefined;
let capturedSelectedHandler: string | null | undefined;
vi.mock("../components/app-detail/handlers-tab", () => ({
  HandlersTab: ({
    onSwitchToCode,
    selectedHandler,
  }: {
    onSwitchToCode?: (line?: number) => void;
    selectedHandler?: string | null;
  }) => {
    capturedOnSwitchToCode = onSwitchToCode;
    capturedSelectedHandler = selectedHandler;
    return <div data-testid="handlers-tab" />;
  },
}));
vi.mock("../components/app-detail/code-tab", () => ({
  CodeTab: () => <div data-testid="code-tab" />,
}));
vi.mock("../components/app-detail/config-tab", () => ({
  ConfigTab: () => <div data-testid="config-tab" />,
}));
vi.mock("../components/app-detail/overview-tab", () => ({
  OverviewTab: () => <div data-testid="overview-tab" />,
}));
vi.mock("../components/shared/log-table", () => ({
  useLogTable: () => ({
    tableProps: {
      visibleColumns: [],
      sort: { key: "timestamp", dir: "desc" },
      onSort: () => {},
      columnFilters: {},
      entries: [],
      selectedKey: null,
      onRowClick: () => {},
      isMobile: false,
    },
    drawerProps: { selectedKey: null, entries: [], onClose: () => {}, onNavigate: () => {} },
    columnFilters: {},
    countLabel: "0 entries",
    hasActiveFilter: false,
    resetFilters: () => {},
    livePaused: false,
    resetSort: () => {},
    columnPickerProps: { selectedColumns: [], viewportHidden: new Set(), onToggle: () => {}, onReset: () => {} },
    isMobile: false,
    isEmpty: true,
    isLoading: false,
  }),
  LogTableView: () => <div data-testid="log-table" />,
  LogTableWithDrawer: ({ children }: { children: preact.ComponentChildren }) => (
    <div data-testid="log-table-drawer">{children}</div>
  ),
}));
vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));
vi.mock("../components/shared/confirm-dialog", () => ({
  ConfirmDialog: () => <div data-testid="confirm-dialog" />,
}));

const mockCorrectUrl = vi.fn();
vi.mock("../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

function renderPage(params: { key: string; tab?: AppDetailTab; handler?: string }) {
  return renderWithAppState(<AppDetailPage params={params} />, { stateOverrides: { uptimeSeconds: signal(120) } });
}

describe("AppDetailPage tabs", () => {
  beforeEach(() => {
    mockSearchString = "";
    mockNavigate.mockClear();
    capturedOnSwitchToCode = undefined;
    capturedSelectedHandler = undefined;
    vi.clearAllMocks();
  });

  it("renders overview tab by default (no params.tab provided)", async () => {
    setupApi(createManifest());
    const { findByTestId } = renderPage({ key: "test_app" });
    // OverviewTab is rendered by default
    expect(await findByTestId("overview-tab")).toBeDefined();
  });

  it("renders tab strip with Handlers tab", async () => {
    setupApi(createManifest());
    const { findByRole } = renderPage({ key: "test_app" });
    expect(await findByRole("tab", { name: /handlers/i })).toBeDefined();
  });

  it("renders tab strip with Code tab", async () => {
    setupApi(createManifest());
    const { findByRole } = renderPage({ key: "test_app" });
    expect(await findByRole("tab", { name: /code/i })).toBeDefined();
  });

  it("renders tab strip with Logs tab", async () => {
    setupApi(createManifest());
    const { findByRole } = renderPage({ key: "test_app" });
    expect(await findByRole("tab", { name: /logs/i })).toBeDefined();
  });

  it("renders tab strip with Config tab", async () => {
    setupApi(createManifest());
    const { findByRole } = renderPage({ key: "test_app" });
    expect(await findByRole("tab", { name: /config/i })).toBeDefined();
  });

  it("Overview tab is selected by default", async () => {
    setupApi(createManifest());
    const { findByRole } = renderPage({ key: "test_app" });
    const overviewTab = await findByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
  });

  it("renders handlers-tab content when Handlers tab is active", async () => {
    setupApi(createManifest());
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers" });
    expect(await findByTestId("handlers-tab")).toBeDefined();
  });

  // Tab routing via URL — tab is derived from params.tab prop (set by router)
  it("renders CodeTab when params.tab is 'code'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app", tab: "code" });
    expect(await findByTestId("code-tab")).toBeDefined();
  });

  it("renders ConfigTab when params.tab is 'config'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app", tab: "config" });
    expect(await findByTestId("config-tab")).toBeDefined();
  });

  it("renders log table content when params.tab is 'logs'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app", tab: "logs" });
    expect(await findByTestId("log-table-drawer")).toBeDefined();
  });

  it("code tab has aria-selected=true when params.tab is 'code'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByRole } = renderPage({ key: "test_app", tab: "code" });
    const codeTab = await findByRole("tab", { name: /code/i });
    expect(codeTab.getAttribute("aria-selected")).toBe("true");
  });

  it("overview tab is selected by default when no params.tab provided", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByRole } = renderPage({ key: "test_app" });
    const overviewTab = await findByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
  });

  it("overview tab appears first in the tab bar", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findAllByRole } = renderPage({ key: "test_app" });
    const tabs = await findAllByRole("tab");
    expect(tabs[0].textContent).toMatch(/overview/i);
  });

  it("tab links point to the correct path with instance query param preserved", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    mockSearchString = "instance=1";
    const { findByRole } = renderPage({ key: "test_app" });
    const logsTab = await findByRole("tab", { name: /logs/i });
    expect(logsTab.getAttribute("href")).toBe("/apps/test_app/logs?instance=1");
  });

  it("tab links omit instance query param when not set", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    // no mockSearchString = no instance param
    const { findByRole } = renderPage({ key: "test_app" });
    const logsTab = await findByRole("tab", { name: /logs/i });
    expect(logsTab.getAttribute("href")).toBe("/apps/test_app/logs");
  });

  // T03: "view in code" navigates to /apps/:key/code?line=N instead of mutating signal
  it("onSwitchToCode navigates to code tab with ?line= param", async () => {
    setupApi(createManifest());
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers" });
    await findByTestId("handlers-tab");
    // Invoke the callback captured from HandlersTab
    capturedOnSwitchToCode?.(42);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code?line=42");
  });

  it("onSwitchToCode navigates to code tab without ?line= when line is undefined", async () => {
    setupApi(createManifest());
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers" });
    await findByTestId("handlers-tab");
    capturedOnSwitchToCode?.();
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code");
  });

  it("onSwitchToCode preserves ?instance= param when navigating to code tab", async () => {
    setupApi(createManifest());
    mockSearchString = "instance=1";
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers" });
    await findByTestId("handlers-tab");
    capturedOnSwitchToCode?.(15);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code?line=15&instance=1");
  });

  it("onSwitchToCode drops invalid instance params", async () => {
    setupApi(createManifest());
    mockSearchString = "instance=-1";
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers" });
    await findByTestId("handlers-tab");
    capturedOnSwitchToCode?.(15);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code?line=15");
  });

  it("passes selectedHandler prop from params.handler to HandlersTab", async () => {
    setupApi(createManifest());
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers", handler: "listener/42" });
    await findByTestId("handlers-tab");
    expect(capturedSelectedHandler).toBe("listener/42");
  });

  it("passes null selectedHandler to HandlersTab when no handler param", async () => {
    setupApi(createManifest());
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers" });
    await findByTestId("handlers-tab");
    expect(capturedSelectedHandler).toBeNull();
  });
});
