import { describe, expect, it, vi, beforeEach } from "vitest";
import { signal } from "@preact/signals";
import { DashboardPage } from "./dashboard";
import { renderWithAppState } from "../test/render-helpers";
import { createKpis, createAppGridEntry, createHandlerError, createManifestList, createManifest } from "../test/factories";

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

vi.mock("../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(),
}));

vi.mock("../hooks/use-debounced-effect", () => ({
  useDebouncedEffect: vi.fn(),
}));

vi.mock("../hooks/use-api", () => ({
  useApi: vi.fn(),
}));

const useScopedApiMod = await import("../hooks/use-scoped-api");
const useScopedApi = useScopedApiMod.useScopedApi as unknown as ReturnType<typeof vi.fn>;

const useDebouncedEffectMod = await import("../hooks/use-debounced-effect");
const useDebouncedEffect = useDebouncedEffectMod.useDebouncedEffect as unknown as ReturnType<typeof vi.fn>;

const useApiMod = await import("../hooks/use-api");
const useApi = useApiMod.useApi as unknown as ReturnType<typeof vi.fn>;

function fakeApiResult<T>(data: T | null, loading = false, error: string | null = null) {
  return {
    data: signal(data),
    loading: signal(loading),
    error: signal(error),
    refetch: vi.fn().mockResolvedValue(undefined),
  };
}

function setupScopedApi({
  kpisData = createKpis() as ReturnType<typeof createKpis> | null,
  appGridData = [] as ReturnType<typeof createAppGridEntry>[] | null,
  errorsData = [] as ReturnType<typeof createHandlerError>[] | null,
  kpisLoading = false,
  appGridLoading = false,
} = {}) {
  useScopedApi
    .mockReturnValueOnce(fakeApiResult(kpisData, kpisLoading))
    .mockReturnValueOnce(fakeApiResult(appGridData, appGridLoading))
    .mockReturnValueOnce(fakeApiResult(errorsData));
}

function setupUseApi({
  bootIssues = [] as unknown[],
  services = [
    { name: "BusService", status: "running" },
    { name: "SchedulerService", status: "running" },
    { name: "WebsocketService", status: "running" },
    { name: "FileWatcherService", status: "running" },
  ],
  manifests = createManifestList(),
} = {}) {
  let callCount = 0;
  useApi.mockImplementation(() => {
    callCount++;
    if (callCount % 2 === 1) return fakeApiResult(manifests);
    return fakeApiResult({ status: "running", boot_issues: bootIssues, services });
  });
}

describe("DashboardPage — loading state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("shows spinner while kpis and manifests are loading", () => {
    setupScopedApi({ kpisLoading: true, kpisData: null, appGridData: null });
    useApi.mockReset();
    useApi.mockReturnValue(fakeApiResult(null, true));
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });
});

describe("DashboardPage — stats strip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("renders unified stats strip with handler count and success rate", () => {
    setupUseApi();
    setupScopedApi({
      kpisData: createKpis({ total_handlers: 10, total_jobs: 5, error_rate: 2.5 }),
      appGridData: [createAppGridEntry({ status: "running" })],
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const strip = getByTestId("overview-stats-strip");
    expect(strip.textContent).toContain("15");
    expect(strip.textContent).toContain("97.5");
    expect(strip.textContent).toContain("handlers");
    expect(strip.textContent).toContain("success");
  });

  it("shows app count and service count", () => {
    setupUseApi({
      manifests: createManifestList({
        manifests: [
          createManifest({ app_key: "app_a" }),
          createManifest({ app_key: "app_b" }),
        ],
      }),
    });
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "app_a" }),
        createAppGridEntry({ app_key: "app_b" }),
      ],
      kpisData: createKpis(),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const strip = getByTestId("overview-stats-strip");
    expect(strip.textContent).toContain("2");
    expect(strip.textContent).toContain("apps");
    expect(strip.textContent).toContain("services");
  });

  it("shows unhealthy service ratio when services degraded", () => {
    setupUseApi({
      services: [
        { name: "BusService", status: "running" },
        { name: "SchedulerService", status: "failed" },
      ],
    });
    setupScopedApi({ kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const strip = getByTestId("overview-stats-strip");
    expect(strip.textContent).toContain("1/2");
  });

  it("shows dropped events count", () => {
    setupUseApi();
    setupScopedApi({ kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />, {
      stateOverrides: { droppedOverflow: signal(3), droppedExhausted: signal(2) },
    });
    const strip = getByTestId("overview-stats-strip");
    expect(strip.textContent).toContain("5");
    expect(strip.textContent).toContain("dropped");
  });
});

describe("DashboardPage — alerts bar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("renders alerts bar when boot issues exist", () => {
    setupUseApi({
      bootIssues: [
        { severity: "err", label: "config error", detail: "missing key" },
        { severity: "warn", label: "deprecation", detail: "old syntax" },
      ],
    });
    setupScopedApi({ kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const alerts = getByTestId("overview-alerts-bar");
    expect(alerts.textContent).toContain("1 boot error");
    expect(alerts.textContent).toContain("1 boot warning");
  });

  it("renders alerts bar when degraded services exist", () => {
    setupUseApi({
      services: [
        { name: "BusService", status: "running" },
        { name: "SchedulerService", status: "failed" },
        { name: "WebsocketService", status: "starting" },
      ],
    });
    setupScopedApi({ kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const alerts = getByTestId("overview-alerts-bar");
    expect(alerts.textContent).toContain("2 degraded services");
  });

  it("does not render alerts bar when everything is healthy", () => {
    setupUseApi();
    setupScopedApi({ kpisData: createKpis() });
    const { queryByTestId } = renderWithAppState(<DashboardPage />);
    expect(queryByTestId("overview-alerts-bar")).toBeNull();
  });
});

describe("DashboardPage — app health table", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("renders app table with app names", () => {
    setupUseApi({
      manifests: createManifestList({
        manifests: [
          createManifest({ app_key: "kitchen_lights" }),
          createManifest({ app_key: "motion_detector" }),
        ],
      }),
    });
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "kitchen_lights", status: "running" }),
        createAppGridEntry({ app_key: "motion_detector", status: "running" }),
      ],
      kpisData: createKpis(),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const table = getByTestId("overview-app-table");
    expect(table.textContent).toContain("kitchen_lights");
    expect(table.textContent).toContain("motion_detector");
  });

  it("shows empty state when no apps loaded", () => {
    setupUseApi({ manifests: createManifestList({ manifests: [] }) });
    setupScopedApi({ appGridData: [], kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const table = getByTestId("overview-app-table");
    expect(table.textContent).toContain("no apps loaded");
    expect(table.textContent).toContain("get started");
  });

  it("links to all-apps page", () => {
    setupUseApi();
    setupScopedApi({ kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const table = getByTestId("overview-app-table");
    const link = table.querySelector("a[href='/apps']");
    expect(link).not.toBeNull();
  });

  it("sorts failed apps first", () => {
    setupUseApi({
      manifests: createManifestList({
        manifests: [
          createManifest({ app_key: "ok_app", status: "running" }),
          createManifest({ app_key: "bad_app", status: "failed" }),
        ],
      }),
    });
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "ok_app", status: "running" }),
        createAppGridEntry({ app_key: "bad_app", status: "failed" }),
      ],
      kpisData: createKpis(),
    });
    const { container } = renderWithAppState(<DashboardPage />);
    const rows = container.querySelectorAll("tr[data-testid^='overview-app-']");
    expect(rows[0]?.getAttribute("data-testid")).toBe("overview-app-bad_app");
    expect(rows[1]?.getAttribute("data-testid")).toBe("overview-app-ok_app");
  });
});

describe("DashboardPage — recent errors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("renders recent errors when errors exist", () => {
    setupScopedApi({
      kpisData: createKpis(),
      errorsData: [createHandlerError({ app_key: "my_app", error_type: "ValueError" })],
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const errors = getByTestId("overview-recent-errors");
    expect(errors.textContent).toContain("my_app");
    expect(errors.textContent).toContain("ValueError");
  });

  it("does not render errors section when no errors", () => {
    setupScopedApi({ kpisData: createKpis(), errorsData: [] });
    const { queryByTestId } = renderWithAppState(<DashboardPage />);
    expect(queryByTestId("overview-recent-errors")).toBeNull();
  });

  it("caps visible errors at 5", () => {
    const errors = Array.from({ length: 10 }, (_, i) =>
      createHandlerError({ app_key: `app_${i}`, listener_id: i + 1 }),
    );
    setupScopedApi({ kpisData: createKpis(), errorsData: errors });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const rows = getByTestId("overview-recent-errors").querySelectorAll("tbody tr");
    expect(rows.length).toBe(5);
  });

  it("links to logs page", () => {
    setupScopedApi({
      kpisData: createKpis(),
      errorsData: [createHandlerError()],
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const link = getByTestId("overview-recent-errors").querySelector("a[href='/logs']");
    expect(link).not.toBeNull();
  });
});

describe("DashboardPage — telemetry degraded banner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("shows telemetry degraded banner when telemetryDegraded is true", () => {
    setupScopedApi({ kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />, {
      stateOverrides: { telemetryDegraded: signal(true), droppedOverflow: signal(5) },
    });
    expect(getByTestId("telemetry-degraded-banner")).toBeDefined();
  });

  it("does not show telemetry degraded banner when telemetryDegraded is false", () => {
    setupScopedApi({ kpisData: createKpis() });
    const { queryByTestId } = renderWithAppState(<DashboardPage />, {
      stateOverrides: { telemetryDegraded: signal(false) },
    });
    expect(queryByTestId("telemetry-degraded-banner")).toBeNull();
  });
});

describe("DashboardPage — debounced refetch", () => {
  it("calls useDebouncedEffect with 500ms delay and 2000ms maxWait", () => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
    setupScopedApi();
    renderWithAppState(<DashboardPage />);
    expect(useDebouncedEffect).toHaveBeenCalledWith(
      expect.any(Function),
      500,
      expect.any(Function),
      2000,
    );
  });

  it("refetch callback calls all three refetch functions", () => {
    vi.clearAllMocks();
    let capturedCallback: (() => void) | null = null;
    useDebouncedEffect.mockImplementation(
      (_getValue: () => unknown, _delay: number, callback: () => void) => {
        capturedCallback = callback;
      },
    );

    const kpisRefetch = vi.fn().mockResolvedValue(undefined);
    const appGridRefetch = vi.fn().mockResolvedValue(undefined);
    const errorsRefetch = vi.fn().mockResolvedValue(undefined);
    let callCount = 0;
    useScopedApi.mockImplementation(() => {
      callCount++;
      const pos = (callCount - 1) % 3;
      if (pos === 0) return { data: signal(createKpis()), loading: signal(false), error: signal(null), refetch: kpisRefetch };
      if (pos === 1) return { data: signal([]), loading: signal(false), error: signal(null), refetch: appGridRefetch };
      return { data: signal([]), loading: signal(false), error: signal(null), refetch: errorsRefetch };
    });

    setupUseApi();
    renderWithAppState(<DashboardPage />);
    expect(capturedCallback).not.toBeNull();

    capturedCallback!();
    expect(kpisRefetch).toHaveBeenCalled();
    expect(appGridRefetch).toHaveBeenCalled();
    expect(errorsRefetch).toHaveBeenCalled();
  });
});
