import { QueryClientProvider } from "@tanstack/preact-query";
import { fireEvent, render } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import type { ComponentChildren } from "preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AppManifest, JobData, ListenerData } from "../api/endpoints";
import { AppStateContext } from "../state/context";
import { type AppState, createAppState } from "../state/create-app-state";
import { createInstance, createManifest } from "../test/factories";
import { createTestQueryClient } from "../test/query-test-utils";
import { server } from "../test/server";
import { AppDetailPage } from "./app-detail";

// Mutable search string for tests that need to control query params
let mockSearchString = "";
const mockNavigate = vi.fn();

// Stub wouter navigation
vi.mock("wouter", () => ({
  useLocation: () => ["/apps/test_app", mockNavigate],
  useSearch: () => mockSearchString,
  Link: ({
    href,
    children,
    role,
    "aria-selected": ariaSelected,
    "aria-controls": ariaControls,
    id,
    class: cls,
    "data-testid": testId,
    onKeyDown,
  }: Record<string, unknown>) => (
    <a
      href={href as string}
      role={role as import("preact").JSX.AriaRole}
      aria-selected={ariaSelected as boolean}
      aria-controls={ariaControls as string}
      id={id as string}
      class={cls as string}
      data-testid={testId as string}
      onKeyDown={onKeyDown as never}
    >
      {children as never}
    </a>
  ),
}));

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
      sortConfig: { column: "timestamp", asc: false },
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

// Local wrapper (not renderWithAppState) because tests share a mutable AppState across
// beforeEach setup and individual tests — renderWithAppState creates a fresh state per call.
function createWrapper(state: AppState) {
  const queryClient = createTestQueryClient();
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AppStateContext.Provider value={state}>{children}</AppStateContext.Provider>
      </QueryClientProvider>
    );
  };
}

function setupApi(manifest: AppManifest, listeners: ListenerData[] = [], jobs: JobData[] = []) {
  server.use(
    http.get("/api/apps/manifests", () =>
      HttpResponse.json({
        total: 1,
        running: 1,
        failed: 0,
        stopped: 0,
        disabled: 0,
        blocked: 0,
        manifests: [manifest],
        only_app: null,
      }),
    ),
    http.get("/api/telemetry/app/:app_key/listeners", () => HttpResponse.json(listeners)),
    http.get("/api/telemetry/app/:app_key/jobs", () => HttpResponse.json(jobs)),
  );
}

describe("AppDetailPage", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    state.uptimeSeconds.value = 120;
    mockSearchString = "";
    mockNavigate.mockClear();
    capturedOnSwitchToCode = undefined;
    capturedSelectedHandler = undefined;
    vi.clearAllMocks();
  });

  it("renders app_key in the header", async () => {
    const manifest = createManifest({ app_key: "test_app", display_name: "Motion Sensor App" });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect((await findByTestId("app-title")).textContent).toContain("test_app");
  });

  it("renders action buttons", async () => {
    setupApi(createManifest());
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByTestId("action-buttons")).toBeDefined();
  });

  it("renders overview tab by default (no params.tab provided)", async () => {
    setupApi(createManifest());
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    // OverviewTab is rendered by default
    expect(await findByTestId("overview-tab")).toBeDefined();
  });

  it("renders tab strip with Handlers tab", async () => {
    setupApi(createManifest());
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByRole("tab", { name: /handlers/i })).toBeDefined();
  });

  it("renders tab strip with Code tab", async () => {
    setupApi(createManifest());
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByRole("tab", { name: /code/i })).toBeDefined();
  });

  it("renders tab strip with Logs tab", async () => {
    setupApi(createManifest());
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByRole("tab", { name: /logs/i })).toBeDefined();
  });

  it("renders tab strip with Config tab", async () => {
    setupApi(createManifest());
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByRole("tab", { name: /config/i })).toBeDefined();
  });

  it("Overview tab is selected by default", async () => {
    setupApi(createManifest());
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const overviewTab = await findByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
  });

  it("renders handlers-tab content when Handlers tab is active", async () => {
    setupApi(createManifest());
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "handlers" }} />, {
      wrapper: createWrapper(state),
    });
    expect(await findByTestId("handlers-tab")).toBeDefined();
  });

  it("renders error display for failed app with error_message", async () => {
    const manifest = createManifest({
      status: "failed",
      error_message: "Module not found: light_controller",
      error_traceback: null,
    });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByTestId("error-display")).toBeDefined();
  });

  it("does not render error display when app has no error_message", async () => {
    const manifest = createManifest({ error_message: null });
    setupApi(manifest);
    const { findByTestId, queryByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, {
      wrapper: createWrapper(state),
    });
    // Wait for data to load before asserting absence
    await findByTestId("app-title");
    expect(queryByTestId("error-display")).toBeNull();
  });

  it("renders filename in subtitle meta", async () => {
    const manifest = createManifest({ app_key: "motion_sensor_app", filename: "apps/motion_sensor.py" });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "motion_sensor_app" }} />, {
      wrapper: createWrapper(state),
    });
    expect((await findByTestId("app-subtitle-meta")).textContent).toContain("apps/motion_sensor.py");
  });

  it("renders auto-loaded badge when auto_loaded is true", async () => {
    const manifest = createManifest({ auto_loaded: true });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByTestId("auto-loaded-badge")).toBeDefined();
  });

  it("does not render auto-loaded badge when auto_loaded is false", async () => {
    const manifest = createManifest({ auto_loaded: false });
    setupApi(manifest);
    const { findByTestId, queryByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, {
      wrapper: createWrapper(state),
    });
    // Wait for data to load before asserting absence
    await findByTestId("app-title");
    expect(queryByTestId("auto-loaded-badge")).toBeNull();
  });

  it("shows filename in subtitle meta", async () => {
    const manifest = createManifest({
      app_key: "test_app",
      filename: "apps/test_app.py",
      class_name: "TestApp",
    });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const subtitleMeta = await findByTestId("app-subtitle-meta");
    expect(subtitleMeta.textContent).toContain("apps/test_app.py");
    expect(subtitleMeta.textContent).toContain("TestApp");
  });

  it("renders multi-instance parent overview when instance_count > 1 and no index param", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByTestId("instance-grid")).toBeDefined();
  });

  it("renders instance grid cards with instance names", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByTestId("instance-card-0")).toBeDefined();
    expect(await findByTestId("instance-card-1")).toBeDefined();
  });

  it("renders instance count badge in parent overview header", async () => {
    const manifest = createManifest({
      instance_count: 3,
      instances: [
        createInstance({ index: 0, instance_name: "a", status: "running" }),
        createInstance({ index: 1, instance_name: "b", status: "running" }),
        createInstance({ index: 2, instance_name: "c", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect((await findByTestId("instance-count-badge")).textContent).toContain("3");
  });

  it("renders instance switcher in detail header when on instance view with siblings", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    // Instance 0 is specified via query param
    mockSearchString = "instance=0";
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect(await findByTestId("instance-switcher")).toBeDefined();
  });

  it("renders breadcrumb with parent link when viewing instance detail", async () => {
    const manifest = createManifest({
      display_name: "Multi App",
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=0";
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const breadcrumb = await findByTestId("breadcrumb-parent");
    expect(breadcrumb).toBeDefined();
    expect(breadcrumb.textContent).toContain("test_app");
  });

  // Tab routing via URL — tab is derived from params.tab prop (set by router)
  it("renders CodeTab when params.tab is 'code'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "code" }} />, {
      wrapper: createWrapper(state),
    });
    expect(await findByTestId("code-tab")).toBeDefined();
  });

  it("renders ConfigTab when params.tab is 'config'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "config" }} />, {
      wrapper: createWrapper(state),
    });
    expect(await findByTestId("config-tab")).toBeDefined();
  });

  it("renders log table content when params.tab is 'logs'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "logs" }} />, {
      wrapper: createWrapper(state),
    });
    expect(await findByTestId("log-table-drawer")).toBeDefined();
  });

  it("code tab has aria-selected=true when params.tab is 'code'", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app", tab: "code" }} />, {
      wrapper: createWrapper(state),
    });
    const codeTab = await findByRole("tab", { name: /code/i });
    expect(codeTab.getAttribute("aria-selected")).toBe("true");
  });

  it("overview tab is selected by default when no params.tab provided", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const overviewTab = await findByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
  });

  it("overview tab appears first in the tab bar", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    const { findAllByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const tabs = await findAllByRole("tab");
    expect(tabs[0].textContent).toMatch(/overview/i);
  });

  it("tab links point to the correct path with instance query param preserved", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    mockSearchString = "instance=1";
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const logsTab = await findByRole("tab", { name: /logs/i });
    expect(logsTab.getAttribute("href")).toBe("/apps/test_app/logs?instance=1");
  });

  it("tab links omit instance query param when not set", async () => {
    const manifest = createManifest();
    setupApi(manifest);
    // no mockSearchString = no instance param
    const { findByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const logsTab = await findByRole("tab", { name: /logs/i });
    expect(logsTab.getAttribute("href")).toBe("/apps/test_app/logs");
  });

  it("instance switcher navigates to current tab path with instance query param", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=0";
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "logs" }} />, {
      wrapper: createWrapper(state),
    });
    // Click instance 1 in the switcher
    const inst1Btn = await findByTestId("switcher-instance-1");
    fireEvent.click(inst1Btn);
    // Should navigate to /apps/test_app/logs?instance=1
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/logs?instance=1");
  });

  it("multi-instance parent overview navigates using ?instance= query param", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    // No instance param = parent overview
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    // Click an instance card
    const card0 = await findByTestId("instance-card-0");
    fireEvent.click(card0);
    // Should navigate to /apps/test_app/overview?instance=0
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/overview?instance=0");
  });

  it("reads instance from ?instance= query param for multi-instance detail view", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=1";
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    // Instance switcher should be rendered (not parent overview)
    await findByTestId("instance-switcher");
    // The instance 1 button should be active
    const inst1Btn = await findByTestId("switcher-instance-1");
    expect(inst1Btn.getAttribute("aria-selected")).toBe("true");
  });

  it("corrects out-of-range instance index to instance 0 via correctUrl", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=99";
    render(<AppDetailPage params={{ key: "test_app", tab: "handlers" }} />, { wrapper: createWrapper(state) });
    // Wait for manifests to load, then check correctUrl was called
    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers?instance=0");
    });
  });

  // T03: "view in code" navigates to /apps/:key/code?line=N instead of mutating signal
  it("onSwitchToCode navigates to code tab with ?line= param", async () => {
    setupApi(createManifest());
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "handlers" }} />, {
      wrapper: createWrapper(state),
    });
    await findByTestId("handlers-tab");
    // Invoke the callback captured from HandlersTab
    capturedOnSwitchToCode?.(42);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code?line=42");
  });

  it("onSwitchToCode navigates to code tab without ?line= when line is undefined", async () => {
    setupApi(createManifest());
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "handlers" }} />, {
      wrapper: createWrapper(state),
    });
    await findByTestId("handlers-tab");
    capturedOnSwitchToCode?.();
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code");
  });

  it("onSwitchToCode preserves ?instance= param when navigating to code tab", async () => {
    setupApi(createManifest());
    mockSearchString = "instance=1";
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "handlers" }} />, {
      wrapper: createWrapper(state),
    });
    await findByTestId("handlers-tab");
    capturedOnSwitchToCode?.(15);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code?line=15&instance=1");
  });

  it("passes selectedHandler prop from params.handler to HandlersTab", async () => {
    setupApi(createManifest());
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "handlers", handler: "h-42" }} />, {
      wrapper: createWrapper(state),
    });
    await findByTestId("handlers-tab");
    expect(capturedSelectedHandler).toBe("h-42");
  });

  it("passes null selectedHandler to HandlersTab when no handler param", async () => {
    setupApi(createManifest());
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "handlers" }} />, {
      wrapper: createWrapper(state),
    });
    await findByTestId("handlers-tab");
    expect(capturedSelectedHandler).toBeNull();
  });

  // ── Multi-instance parent page tab tests ──

  function setupMultiInstanceParent() {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
  }

  it("parent page renders tab strip with 4 tabs (no handlers)", async () => {
    setupMultiInstanceParent();
    const { findAllByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    const tabs = await findAllByRole("tab");
    const labels = tabs.map((t) => t.textContent?.trim());
    expect(labels).toEqual(["overview", "code", "logs", "config"]);
  });

  it("parent page hides handlers tab", async () => {
    setupMultiInstanceParent();
    const { findByTestId, queryByRole } = render(<AppDetailPage params={{ key: "test_app" }} />, {
      wrapper: createWrapper(state),
    });
    await findByTestId("app-title");
    expect(queryByRole("tab", { name: /handlers/i })).toBeNull();
  });

  it("parent page renders code tab content", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "code" }} />, {
      wrapper: createWrapper(state),
    });
    expect(await findByTestId("code-tab")).toBeDefined();
  });

  it("parent page renders logs tab content", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "logs" }} />, {
      wrapper: createWrapper(state),
    });
    expect(await findByTestId("log-table-drawer")).toBeDefined();
  });

  it("parent page renders config tab content", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app", tab: "config" }} />, {
      wrapper: createWrapper(state),
    });
    expect(await findByTestId("config-tab")).toBeDefined();
  });

  it("parent page does not render instance switcher", async () => {
    setupMultiInstanceParent();
    const { findByTestId, queryByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, {
      wrapper: createWrapper(state),
    });
    await findByTestId("app-title");
    expect(queryByTestId("instance-switcher")).toBeNull();
  });

  it("parent page redirects /handlers to /overview via correctUrl", async () => {
    setupMultiInstanceParent();
    render(<AppDetailPage params={{ key: "test_app", tab: "handlers" }} />, { wrapper: createWrapper(state) });
    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/overview");
    });
  });

  it("parent page hides 'instance N' from subtitle meta", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = render(<AppDetailPage params={{ key: "test_app" }} />, { wrapper: createWrapper(state) });
    expect((await findByTestId("app-subtitle-meta")).textContent).not.toContain("instance");
  });
});
