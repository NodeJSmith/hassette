import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { AppDetailPage } from "./app-detail";
import { AppStateContext } from "../state/context";
import { createAppState, type AppState } from "../state/create-app-state";
import { createManifest, createInstance } from "../test/factories";
import type { AppManifest, JobData, ListenerData } from "../api/endpoints";

// Mutable search string for tests that need to control query params
let mockSearchString = "";
const mockNavigate = vi.fn();

// Stub wouter navigation
vi.mock("wouter", () => ({
  useLocation: () => ["/apps/test_app", mockNavigate],
  useSearch: () => mockSearchString,
  Link: ({ href, children, role, "aria-selected": ariaSelected, "aria-controls": ariaControls, id, class: cls, onKeyDown }: Record<string, unknown>) =>
    <a href={href as string} role={role as import("preact").JSX.AriaRole} aria-selected={ariaSelected as boolean} aria-controls={ariaControls as string} id={id as string} class={cls as string} onKeyDown={onKeyDown as never}>{children as never}</a>,
}));

// Stub child components not under test
vi.mock("../components/shared/error-banner", () => ({
  ErrorBanner: ({ "data-testid": testId }: { "data-testid"?: string }) =>
    <div data-testid={testId ?? "error-banner"} />,
}));
// Capture props from HandlersTab so tests can invoke callbacks and assert prop values
let capturedOnSwitchToCode: ((line?: number) => void) | undefined;
let capturedSelectedHandler: string | null | undefined;
vi.mock("../components/app-detail/handlers-tab", () => ({
  HandlersTab: ({ onSwitchToCode, selectedHandler }: { onSwitchToCode?: (line?: number) => void; selectedHandler?: string | null }) => {
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
    tableProps: { visibleColumns: [], sortConfig: { column: "timestamp", asc: false }, onSort: () => {}, columnFilters: {}, entries: [], selectedKey: null, onRowClick: () => {}, isMobile: false },
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
  LogTableWithDrawer: ({ children }: { children: preact.ComponentChildren }) => <div data-testid="log-table-drawer">{children}</div>,
}));
vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));
vi.mock("../components/shared/confirm-dialog", () => ({
  ConfirmDialog: () => <div data-testid="confirm-dialog" />,
}));

// Mock hooks
vi.mock("../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(),
}));

const mockCorrectUrl = vi.fn();
vi.mock("../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

const useScopedApiMod = await import("../hooks/use-scoped-api");
const useScopedApi = useScopedApiMod.useScopedApi as unknown as ReturnType<typeof vi.fn>;

function fakeScopedApiResult<T>(data: T | null) {
  return {
    data: signal(data),
    loading: signal(false),
    error: signal<string | null>(null),
    refetch: vi.fn(),
  };
}

function createWrapper(state: AppState) {
  return function Wrapper({ children }: { children: ComponentChildren }) {
    return <AppStateContext.Provider value={state}>{children}</AppStateContext.Provider>;
  };
}

describe("AppDetailPage", () => {
  let state: AppState;

  beforeEach(() => {
    state = createAppState();
    mockSearchString = "";
    mockNavigate.mockClear();
    capturedOnSwitchToCode = undefined;
    capturedSelectedHandler = undefined;
    vi.clearAllMocks();
  });

  function setupManifestAndApi(
    manifest: AppManifest,
    listeners: ListenerData[] = [],
    jobs: JobData[] = [],
  ) {
    // Manifests come from shared app state (synchronous)
    state.manifests.value = [manifest];
    state.manifestsLoading.value = false;
    // Listeners and jobs still come from useScopedApi
    useScopedApi
      .mockReturnValueOnce(fakeScopedApiResult(listeners))   // listeners
      .mockReturnValueOnce(fakeScopedApiResult(jobs));        // jobs
  }


  it("renders app_key in the header", () => {
    const manifest = createManifest({ app_key: "test_app", display_name: "Motion Sensor App" });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-title").textContent).toContain("test_app");
  });

  it("renders action buttons", () => {
    setupManifestAndApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("action-buttons")).toBeDefined();
  });

  it("renders overview tab by default (no params.tab provided)", () => {
    setupManifestAndApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    // OverviewTab is rendered by default
    expect(getByTestId("overview-tab")).toBeDefined();
  });

  it("renders tab strip with Handlers tab", () => {
    setupManifestAndApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /handlers/i })).toBeDefined();
  });

  it("renders tab strip with Code tab", () => {
    setupManifestAndApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /code/i })).toBeDefined();
  });

  it("renders tab strip with Logs tab", () => {
    setupManifestAndApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /logs/i })).toBeDefined();
  });

  it("renders tab strip with Config tab", () => {
    setupManifestAndApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /config/i })).toBeDefined();
  });

  it("Overview tab is selected by default", () => {
    setupManifestAndApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const overviewTab = getByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
  });

  it("renders handlers-tab content when Handlers tab is active", () => {
    setupManifestAndApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("handlers-tab")).toBeDefined();
  });

  it("renders error display for failed app with error_message", () => {
    const manifest = createManifest({
      status: "failed",
      error_message: "Module not found: light_controller",
      error_traceback: null,
    });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("error-display")).toBeDefined();
  });

  it("does not render error display when app has no error_message", () => {
    const manifest = createManifest({ error_message: null });
    setupManifestAndApi(manifest);
    const { queryByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(queryByTestId("error-display")).toBeNull();
  });

  it("renders filename in subtitle meta", () => {
    const manifest = createManifest({ app_key: "motion_sensor_app", filename: "apps/motion_sensor.py" });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "motion_sensor_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-subtitle-meta").textContent).toContain("apps/motion_sensor.py");
  });

  it("renders auto-loaded badge when auto_loaded is true", () => {
    const manifest = createManifest({ auto_loaded: true });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("auto-loaded-badge")).toBeDefined();
  });

  it("does not render auto-loaded badge when auto_loaded is false", () => {
    const manifest = createManifest({ auto_loaded: false });
    setupManifestAndApi(manifest);
    const { queryByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(queryByTestId("auto-loaded-badge")).toBeNull();
  });

  it("shows filename in subtitle meta", () => {
    const manifest = createManifest({
      app_key: "test_app",
      filename: "apps/test_app.py",
      class_name: "TestApp",
    });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-subtitle-meta").textContent).toContain("apps/test_app.py");
    expect(getByTestId("app-subtitle-meta").textContent).toContain("TestApp");
  });

  it("renders multi-instance parent overview when instance_count > 1 and no index param", () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("instance-grid")).toBeDefined();
  });

  it("renders instance grid cards with instance names", () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("instance-card-0")).toBeDefined();
    expect(getByTestId("instance-card-1")).toBeDefined();
  });

  it("renders instance count badge in parent overview header", () => {
    const manifest = createManifest({
      instance_count: 3,
      instances: [
        createInstance({ index: 0, instance_name: "a", status: "running" }),
        createInstance({ index: 1, instance_name: "b", status: "running" }),
        createInstance({ index: 2, instance_name: "c", status: "stopped" }),
      ],
    });
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("instance-count-badge").textContent).toContain("3");
  });

  it("renders instance switcher in detail header when on instance view with siblings", () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupManifestAndApi(manifest);
    // Instance 0 is specified via query param
    mockSearchString = "instance=0";
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("instance-switcher")).toBeDefined();
  });

  it("renders breadcrumb with parent link when viewing instance detail", () => {
    const manifest = createManifest({
      display_name: "Multi App",
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupManifestAndApi(manifest);
    mockSearchString = "instance=0";
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("breadcrumb-parent")).toBeDefined();
    expect(getByTestId("breadcrumb-parent").textContent).toContain("test_app");
  });

  // Tab routing via URL — tab is derived from params.tab prop (set by router)
  it("renders CodeTab when params.tab is 'code'", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "code" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("code-tab")).toBeDefined();
  });

  it("renders ConfigTab when params.tab is 'config'", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "config" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("config-tab")).toBeDefined();
  });

  it("renders log table content when params.tab is 'logs'", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "logs" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("log-table-drawer")).toBeDefined();
  });

  it("code tab has aria-selected=true when params.tab is 'code'", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app", tab: "code" }} />,
      { wrapper: createWrapper(state) },
    );
    const codeTab = getByRole("tab", { name: /code/i });
    expect(codeTab.getAttribute("aria-selected")).toBe("true");
  });

  it("overview tab is selected by default when no params.tab provided", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const overviewTab = getByRole("tab", { name: /overview/i });
    expect(overviewTab.getAttribute("aria-selected")).toBe("true");
  });

  it("overview tab appears first in the tab bar", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    const { getAllByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const tabs = getAllByRole("tab");
    expect(tabs[0].textContent).toMatch(/overview/i);
  });

  it("tab links point to the correct path with instance query param preserved", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    mockSearchString = "instance=1";
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const logsTab = getByRole("tab", { name: /logs/i });
    expect(logsTab.getAttribute("href")).toBe("/apps/test_app/logs?instance=1");
  });

  it("tab links omit instance query param when not set", () => {
    const manifest = createManifest();
    setupManifestAndApi(manifest);
    // no mockSearchString = no instance param
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const logsTab = getByRole("tab", { name: /logs/i });
    expect(logsTab.getAttribute("href")).toBe("/apps/test_app/logs");
  });

  it("instance switcher navigates to current tab path with instance query param", () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupManifestAndApi(manifest);
    mockSearchString = "instance=0";
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "logs" }} />,
      { wrapper: createWrapper(state) },
    );
    // Click instance 1 in the switcher
    const inst1Btn = getByTestId("switcher-instance-1");
    fireEvent.click(inst1Btn);
    // Should navigate to /apps/test_app/logs?instance=1
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/logs?instance=1");
  });

  it("multi-instance parent overview navigates using ?instance= query param", () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupManifestAndApi(manifest);
    // No instance param = parent overview
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    // Click an instance card
    const card0 = getByTestId("instance-card-0");
    fireEvent.click(card0);
    // Should navigate to /apps/test_app/overview?instance=0
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/overview?instance=0");
  });

  it("reads instance from ?instance= query param for multi-instance detail view", () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupManifestAndApi(manifest);
    mockSearchString = "instance=1";
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    // Instance switcher should be rendered (not parent overview)
    expect(getByTestId("instance-switcher")).toBeDefined();
    // The instance 1 button should be active
    const inst1Btn = getByTestId("switcher-instance-1");
    expect(inst1Btn.getAttribute("aria-selected")).toBe("true");
  });

  it("corrects out-of-range instance index to instance 0 via correctUrl", () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupManifestAndApi(manifest);
    mockSearchString = "instance=99";
    render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(mockCorrectUrl).toHaveBeenCalledWith(
      "/apps/test_app/handlers?instance=0",
    );
  });

  // T03: "view in code" navigates to /apps/:key/code?line=N instead of mutating signal
  it("onSwitchToCode navigates to code tab with ?line= param", () => {
    setupManifestAndApi(createManifest());
    render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers" }} />,
      { wrapper: createWrapper(state) },
    );
    // Invoke the callback captured from HandlersTab
    capturedOnSwitchToCode?.(42);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code?line=42");
  });

  it("onSwitchToCode navigates to code tab without ?line= when line is undefined", () => {
    setupManifestAndApi(createManifest());
    render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers" }} />,
      { wrapper: createWrapper(state) },
    );
    capturedOnSwitchToCode?.();
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code");
  });

  it("onSwitchToCode preserves ?instance= param when navigating to code tab", () => {
    setupManifestAndApi(createManifest());
    mockSearchString = "instance=1";
    render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers" }} />,
      { wrapper: createWrapper(state) },
    );
    capturedOnSwitchToCode?.(15);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/code?line=15&instance=1");
  });

  it("passes selectedHandler prop from params.handler to HandlersTab", () => {
    setupManifestAndApi(createManifest());
    render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers", handler: "h-42" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(capturedSelectedHandler).toBe("h-42");
  });

  it("passes null selectedHandler to HandlersTab when no handler param", () => {
    setupManifestAndApi(createManifest());
    render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers" }} />,
      { wrapper: createWrapper(state) },
    );
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
    setupManifestAndApi(manifest);
  }

  it("parent page renders tab strip with 4 tabs (no handlers)", () => {
    setupMultiInstanceParent();
    const { getAllByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const tabs = getAllByRole("tab");
    const labels = tabs.map((t) => t.textContent?.trim());
    expect(labels).toEqual(["overview", "code", "logs", "config"]);
  });

  it("parent page hides handlers tab", () => {
    setupMultiInstanceParent();
    const { queryByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(queryByRole("tab", { name: /handlers/i })).toBeNull();
  });

  it("parent page renders code tab content", () => {
    setupMultiInstanceParent();
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "code" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("code-tab")).toBeDefined();
  });

  it("parent page renders logs tab content", () => {
    setupMultiInstanceParent();
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "logs" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("log-table-drawer")).toBeDefined();
  });

  it("parent page renders config tab content", () => {
    setupMultiInstanceParent();
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", tab: "config" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("config-tab")).toBeDefined();
  });

  it("parent page does not render instance switcher", () => {
    setupMultiInstanceParent();
    const { queryByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(queryByTestId("instance-switcher")).toBeNull();
  });

  it("parent page redirects /handlers to /overview via correctUrl", () => {
    setupMultiInstanceParent();
    render(
      <AppDetailPage params={{ key: "test_app", tab: "handlers" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/overview");
  });

  it("parent page hides 'instance N' from subtitle meta", () => {
    setupMultiInstanceParent();
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-subtitle-meta").textContent).not.toContain("instance");
  });
});
