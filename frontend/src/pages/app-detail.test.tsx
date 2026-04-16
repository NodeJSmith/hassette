import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/preact";
import { signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { AppDetailPage } from "./app-detail";
import { AppStateContext } from "../state/context";
import { createAppState, type AppState } from "../state/create-app-state";
import type { AppInstance, AppManifest, ManifestListResponse, JobData } from "../api/endpoints";

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

// Mock useApi and useScopedApi to return controlled signal values
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

  function createJob(overrides: Partial<JobData> = {}): JobData {
    return {
      job_id: 1,
      app_key: "test_app",
      instance_index: 0,
      job_name: "my_job",
      handler_method: "my_app.my_job",
      trigger_type: "every",
      trigger_label: "Every 5 minutes",
      trigger_detail: null,
      args_json: "[]",
      kwargs_json: "{}",
      source_location: "",
      registration_source: null,
      source_tier: "app",
      total_executions: 0,
      successful: 0,
      failed: 0,
      last_executed_at: null,
      total_duration_ms: 0,
      avg_duration_ms: 0,
      group: null,
      next_run: null,
      fire_at: null,
      jitter: null,
      cancelled: false,
      ...overrides,
    };
  }

  function setupUseApi(manifest: AppManifest, jobsData: JobData[] = []) {
    // useApi is called once for manifests; useScopedApi is called 3 times for health, listeners, jobs
    useApi
      .mockReturnValueOnce(fakeApiResult(createManifestListResponse(manifest)));
    useScopedApi
      .mockReturnValueOnce(fakeApiResult(null)) // health
      .mockReturnValueOnce(fakeApiResult([])) // listeners
      .mockReturnValueOnce(fakeApiResult(jobsData)); // jobs
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

  it("jobs heading shows N registered count", () => {
    const manifest = createManifest();
    const jobs = [
      createJob({ job_id: 1, next_run: 1700010000 }),
      createJob({ job_id: 2, next_run: null }),
      createJob({ job_id: 3, next_run: 1700020000 }),
    ];
    setupUseApi(manifest, jobs);

    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );

    const heading = getByTestId("jobs-heading");
    expect(heading.textContent).toContain("3 registered");
    expect(heading.textContent).not.toContain("active");
  });

  it("jobs heading secondary count shows currently scheduled jobs (next_run non-null)", () => {
    const manifest = createManifest();
    const jobs = [
      createJob({ job_id: 1, next_run: 1700010000 }),
      createJob({ job_id: 2, next_run: null }),
      createJob({ job_id: 3, next_run: 1700020000 }),
    ];
    setupUseApi(manifest, jobs);

    const { getByTestId } = render(
      <AppDetailPage params={{ key: "test_app" }} />,
      { wrapper: createWrapper(state) },
    );

    const scheduledCount = getByTestId("jobs-scheduled-count");
    expect(scheduledCount.textContent).toContain("2 currently scheduled");
  });
});
