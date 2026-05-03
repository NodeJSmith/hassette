import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/preact";
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
vi.mock("../components/app-detail/health-strip", () => ({
  HealthStrip: () => <div data-testid="health-strip" />,
}));
vi.mock("../components/app-detail/handlers-tab", () => ({
  HandlersTab: () => <div data-testid="handlers-tab" />,
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
      .mockReturnValueOnce(fakeApiResult(null))        // health
      .mockReturnValueOnce(fakeApiResult(listeners))   // listeners
      .mockReturnValueOnce(fakeApiResult(jobs));        // jobs
  }

  it("renders app display name in the header", () => {
    const manifest = createManifest({ display_name: "Motion Sensor App" });
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-title").textContent).toContain("Motion Sensor App");
  });

  it("renders action buttons", () => {
    setupUseApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("action-buttons")).toBeDefined();
  });

  it("renders health strip", () => {
    setupUseApi(createManifest());
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("health-strip")).toBeDefined();
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

  it("renders app_key in mono below the title", () => {
    const manifest = createManifest({ app_key: "motion_sensor_app" });
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "motion_sensor_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("app-key-mono").textContent).toContain("motion_sensor_app");
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

  it("shows owner_id as PID when owner_id is present", () => {
    const manifest = createManifest({
      instances: [createInstance({ owner_id: "MyApp.office_button.0" })],
    });
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("instance-meta").textContent).toContain("PID MyApp.office_button.0");
  });

  it("omits PID portion when owner_id is null", () => {
    const manifest = createManifest({
      instances: [createInstance({ owner_id: null })],
    });
    setupUseApi(manifest);
    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );
    expect(getByTestId("instance-meta").textContent).not.toContain("PID");
  });
});
