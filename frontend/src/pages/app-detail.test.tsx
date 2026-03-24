import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/preact";
import { signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { AppDetailPage } from "./app-detail";
import { AppStateContext } from "../state/context";
import { createAppState, type AppState } from "../state/create-app-state";
import type { AppInstance, AppManifest, ManifestListResponse } from "../api/endpoints";

// Stub wouter navigation
vi.mock("wouter", () => ({
  useLocation: () => ["/apps/test_app", vi.fn()],
}));

// Stub child components that are not under test
vi.mock("../components/app-detail/error-display", () => ({
  ErrorDisplay: () => <div data-testid="error-display" />,
}));
vi.mock("../components/apps/action-buttons", () => ({
  ActionButtons: () => <div data-testid="action-buttons" />,
}));
vi.mock("../components/app-detail/handler-list", () => ({
  HandlerList: () => <div data-testid="handler-list" />,
}));
vi.mock("../components/app-detail/health-strip", () => ({
  HealthStrip: () => <div data-testid="health-strip" />,
}));
vi.mock("../components/app-detail/job-list", () => ({
  JobList: () => <div data-testid="job-list" />,
}));
vi.mock("../components/shared/log-table", () => ({
  LogTable: () => <div data-testid="log-table" />,
}));
vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

// Mock useApi to return controlled signal values
vi.mock("../hooks/use-api", () => ({
  useApi: vi.fn(),
}));

const useApiMod = await import("../hooks/use-api");
const useApi = useApiMod.useApi as unknown as ReturnType<typeof vi.fn>;

function createInstance(overrides: Partial<AppInstance> = {}): AppInstance {
  return {
    app_key: "test_app",
    index: 0,
    instance_name: "inst_0",
    class_name: "TestApp",
    status: "running",
    error_message: null,
    error_traceback: null,
    owner_id: null,
    ...overrides,
  };
}

function createManifest(overrides: Partial<AppManifest> = {}): AppManifest {
  return {
    app_key: "test_app",
    class_name: "TestApp",
    display_name: "Test App",
    filename: "test_app.py",
    enabled: true,
    auto_loaded: true,
    status: "running",
    block_reason: null,
    instance_count: 1,
    instances: [createInstance()],
    error_message: null,
    error_traceback: null,
    ...overrides,
  };
}

function createManifestListResponse(manifest: AppManifest): ManifestListResponse {
  return {
    total: 1,
    running: 1,
    failed: 0,
    stopped: 0,
    disabled: 0,
    blocked: 0,
    manifests: [manifest],
    only_app: null,
  };
}

/** Build a fake UseApiResult where data is already resolved. */
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

  function setupUseApi(manifest: AppManifest) {
    // useApi is called 4 times in AppDetailPage: manifests, health, listeners, jobs
    useApi
      .mockReturnValueOnce(fakeApiResult(createManifestListResponse(manifest))) // manifests
      .mockReturnValueOnce(fakeApiResult(null)) // health
      .mockReturnValueOnce(fakeApiResult([])) // listeners
      .mockReturnValueOnce(fakeApiResult([])); // jobs
  }

  it("shows owner_id as PID when owner_id is present", () => {
    const manifest = createManifest({
      instances: [createInstance({ owner_id: "MyApp.office_button.0" })],
    });
    setupUseApi(manifest);

    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );

    const meta = getByTestId("instance-meta");
    expect(meta.textContent).toContain("PID MyApp.office_button.0");
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

    const meta = getByTestId("instance-meta");
    expect(meta.textContent).not.toContain("PID");
  });
});
