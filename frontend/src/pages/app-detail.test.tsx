import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { AppDetailPage } from "./app-detail";
import { AppStateContext } from "../state/context";
import { createAppState, type AppState } from "../state/create-app-state";
import { createManifest, createInstance, createManifestList } from "../test/factories";
import type { AppManifest, ManifestListResponse, JobData, ListenerData } from "../api/endpoints";

// Stub wouter navigation
vi.mock("wouter", () => ({
  useLocation: () => ["/apps/test_app", vi.fn()],
  useSearch: () => "",
}));

// Stub child components not under test
vi.mock("../components/app-detail/error-display", () => ({
  ErrorDisplay: () => <div data-testid="error-display" />,
}));
vi.mock("../components/app-detail/handlers-tab", () => ({
  HandlersTab: () => <div data-testid="handlers-tab" />,
}));
vi.mock("../components/app-detail/code-tab", () => ({
  CodeTab: () => <div data-testid="code-tab" />,
}));
vi.mock("../components/app-detail/config-tab", () => ({
  ConfigTab: () => <div data-testid="config-tab" />,
}));
vi.mock("../components/shared/log-table", () => ({
  LogTable: () => <div data-testid="log-table" />,
}));
vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));
vi.mock("../components/shared/confirm-dialog", () => ({
  ConfirmDialog: () => <div data-testid="confirm-dialog" />,
}));

// Mock hooks
vi.mock("../hooks/use-api", () => ({
  useApi: vi.fn(),
}));
vi.mock("../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(),
}));

const useApiMod = await import("../hooks/use-api");
const useApi = useApiMod.useApi as unknown as ReturnType<typeof vi.fn>;
const useScopedApiMod = await import("../hooks/use-scoped-api");
const useScopedApi = useScopedApiMod.useScopedApi as unknown as ReturnType<typeof vi.fn>;

function createManifestListResponse(manifest: AppManifest): ManifestListResponse {
  return createManifestList({ manifests: [manifest] });
}

function fakeApiResult<T>(data: T | null) {
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
    vi.clearAllMocks();
  });

  function setupUseApi(
    manifest: AppManifest,
    listeners: ListenerData[] = [],
    jobs: JobData[] = [],
  ) {
    useApi.mockReturnValueOnce(fakeApiResult(createManifestListResponse(manifest)));
    useScopedApi
      .mockReturnValueOnce(fakeApiResult(listeners))   // listeners
      .mockReturnValueOnce(fakeApiResult(jobs));        // jobs
  }

  /** Like setupUseApi but uses persistent mockReturnValue so re-renders after interactions don't exhaust the mock. */
  function setupUseApiPersistent(
    manifest: AppManifest,
    listeners: ListenerData[] = [],
    jobs: JobData[] = [],
  ) {
    useApi.mockReturnValue(fakeApiResult(createManifestListResponse(manifest)));
    useScopedApi.mockReturnValue(fakeApiResult(listeners));
    // Override first two calls to get listeners/jobs in correct order
    useScopedApi
      .mockReturnValueOnce(fakeApiResult(listeners))   // listeners
      .mockReturnValueOnce(fakeApiResult(jobs))         // jobs
      .mockReturnValue(fakeApiResult(null));            // subsequent re-renders
  }

  it("renders app_key in the header", () => {
    const manifest = createManifest({ app_key: "test_app", display_name: "Motion Sensor App" });
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-title").textContent).toContain("test_app");
  });

  it("renders action buttons", () => {
    setupUseApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("action-buttons")).toBeDefined();
  });

  it("renders handlers tab by default (health strip is inside HandlersTab)", () => {
    setupUseApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    // HandlersTab (which contains the health strip) is rendered by default
    expect(getByTestId("handlers-tab")).toBeDefined();
  });

  it("renders tab strip with Handlers tab", () => {
    setupUseApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /handlers/i })).toBeDefined();
  });

  it("renders tab strip with Code tab", () => {
    setupUseApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /code/i })).toBeDefined();
  });

  it("renders tab strip with Logs tab", () => {
    setupUseApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /logs/i })).toBeDefined();
  });

  it("renders tab strip with Config tab", () => {
    setupUseApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByRole("tab", { name: /config/i })).toBeDefined();
  });

  it("Handlers tab is selected by default", () => {
    setupUseApi(createManifest());
    const { getByRole } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const handlersTab = getByRole("tab", { name: /handlers/i });
    expect(handlersTab.getAttribute("aria-selected")).toBe("true");
  });

  it("renders handlers-tab content when Handlers tab is active", () => {
    setupUseApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
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
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("error-display")).toBeDefined();
  });

  it("does not render error display when app has no error_message", () => {
    const manifest = createManifest({ error_message: null });
    setupUseApi(manifest);
    const { queryByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(queryByTestId("error-display")).toBeNull();
  });

  it("renders filename in subtitle meta", () => {
    const manifest = createManifest({ app_key: "motion_sensor_app", filename: "apps/motion_sensor.py" });
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "motion_sensor_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-subtitle-meta").textContent).toContain("apps/motion_sensor.py");
  });

  it("renders auto-loaded badge when auto_loaded is true", () => {
    const manifest = createManifest({ auto_loaded: true });
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("auto-loaded-badge")).toBeDefined();
  });

  it("does not render auto-loaded badge when auto_loaded is false", () => {
    const manifest = createManifest({ auto_loaded: false });
    setupUseApi(manifest);
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
    setupUseApi(manifest);
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
    setupUseApi(manifest);
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
    setupUseApi(manifest);
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
    setupUseApi(manifest);
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
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", index: "0" }} />,
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
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app", index: "0" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("breadcrumb-parent")).toBeDefined();
    expect(getByTestId("breadcrumb-parent").textContent).toContain("test_app");
  });

  it("renders CodeTab when Code tab is clicked", () => {
    const manifest = createManifest();
    setupUseApiPersistent(manifest);
    const { getByRole, getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const codeTab = getByRole("tab", { name: /code/i });
    fireEvent.click(codeTab);
    expect(getByTestId("code-tab")).toBeDefined();
  });

  it("renders ConfigTab when Config tab is clicked", () => {
    const manifest = createManifest();
    setupUseApiPersistent(manifest);
    const { getByRole, getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    const configTab = getByRole("tab", { name: /config/i });
    fireEvent.click(configTab);
    expect(getByTestId("config-tab")).toBeDefined();
  });
});
