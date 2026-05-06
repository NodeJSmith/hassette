import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { DashboardPage } from "./dashboard";
import { renderWithAppState } from "../test/render-helpers";
import { createKpis, createAppGridEntry, createHandlerError } from "../test/factories";

// Stub child components that have their own tests
vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

// Mock useScopedApi for data-fetching control
vi.mock("../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(),
}));

// Mock useDebouncedEffect to capture its callback for manual invocation
vi.mock("../hooks/use-debounced-effect", () => ({
  useDebouncedEffect: vi.fn(),
}));

// Mock useApi for the system status fetch
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

/** Standard three-call setup for DashboardPage (kpis, appGrid, errors). */
function setupScopedApi({
  kpisData = createKpis() as ReturnType<typeof createKpis> | null,
  appGridData = [] as ReturnType<typeof createAppGridEntry>[] | null,
  errorsData = [] as ReturnType<typeof createHandlerError>[] | null,
  kpisLoading = false,
  appGridLoading = false,
  kpisError = null as string | null,
  appGridError = null as string | null,
  errorsError = null as string | null,
} = {}) {
  useScopedApi
    .mockReturnValueOnce(fakeApiResult(kpisData, kpisLoading, kpisError))     // kpis
    .mockReturnValueOnce(fakeApiResult(appGridData, appGridLoading, appGridError)) // appGrid
    .mockReturnValueOnce(fakeApiResult(errorsData, false, errorsError));  // errors
}

function setupUseApi(bootIssues: unknown[] = [], services: unknown[] = [
  { name: "BusService", status: "running" },
  { name: "SchedulerService", status: "running" },
  { name: "WebsocketService", status: "running" },
  { name: "FileWatcherService", status: "running" },
]) {
  useApi.mockReturnValue(fakeApiResult({ status: "running", boot_issues: bootIssues, services }));
}

describe("DashboardPage — loading state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("shows spinner while kpis are loading", () => {
    setupScopedApi({ kpisLoading: true, kpisData: null });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("shows spinner while app grid is loading", () => {
    setupScopedApi({ appGridLoading: true, appGridData: null });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });
});

describe("DashboardPage — greeting header", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("renders a greeting h1 with good morning/afternoon/evening", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { getByRole } = renderWithAppState(<DashboardPage />);
    const heading = getByRole("heading", { level: 1 });
    expect(heading.textContent).toMatch(/good (morning|afternoon|evening)\./i);
  });

  it("renders metadata line with app count and run rate", () => {
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "app_a", status: "running" }),
        createAppGridEntry({ app_key: "app_b", status: "running" }),
      ],
      kpisData: createKpis({ total_invocations: 50, total_executions: 10, runs_per_hour: 60 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const meta = getByTestId("dashboard-metadata");
    expect(meta.textContent).toMatch(/2 apps/);
  });

  it("renders healthy subtitle when all apps healthy", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const subtitle = getByTestId("dashboard-subtitle");
    expect(subtitle.textContent).toMatch(/healthy|nothing needs your attention/i);
  });

  it("renders quiet subtitle when apps loaded but no activity", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 0, total_executions: 0 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const subtitle = getByTestId("dashboard-subtitle");
    expect(subtitle.textContent).toMatch(/nothing has happened in a while/i);
  });

  it("renders multi-error subtitle when multiple apps failing", () => {
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "app_a", status: "failed" }),
        createAppGridEntry({ app_key: "app_b", status: "failed" }),
      ],
      kpisData: createKpis({ total_errors: 3 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const subtitle = getByTestId("dashboard-subtitle");
    expect(subtitle.textContent).toMatch(/failing/i);
  });
});

describe("DashboardPage — three summary cards", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("renders three-card grid", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("summary-cards")).toBeDefined();
  });

  it("renders your-apps card with app list", () => {
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "app_one", display_name: "App One", status: "running", total_invocations: 5 }),
      ],
      kpisData: createKpis({ total_invocations: 5 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const card = getByTestId("your-apps-card");
    expect(card.textContent).toContain("your apps");
    expect(card.textContent).toContain("app_one");
  });

  it("renders activity card", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 100, total_executions: 68 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("activity-card")).toBeDefined();
    expect(getByTestId("activity-card").textContent).toContain("activity");
  });

  it("renders system card with service statuses", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const card = getByTestId("system-card");
    expect(card.textContent).toContain("system");
    expect(card.textContent).toContain("bus");
  });

  it("activity card shows quiet state when no runs", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 0, total_executions: 0 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const card = getByTestId("activity-card");
    expect(card.textContent).toMatch(/0 runs.*hour|quiet/i);
  });

  it("your-apps card shows see-all link", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const card = getByTestId("your-apps-card");
    const link = card.querySelector("a");
    expect(link?.getAttribute("href")).toBe("/apps");
  });
});

describe("DashboardPage — hero card variants", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("shows first-install hero when no apps are loaded", () => {
    setupScopedApi({ appGridData: [], kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("hero-card-first-install")).toBeDefined();
  });

  it("first-install shows code snippet", () => {
    setupScopedApi({ appGridData: [], kpisData: createKpis() });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const hero = getByTestId("hero-card-first-install");
    expect(hero.textContent).toMatch(/HelloApp|hassette\.toml|from hassette/i);
  });

  it("shows no hero card when all apps running, no errors", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ app_key: "app_a", status: "running" })],
      errorsData: [],
      kpisData: createKpis({ error_rate: 0, total_invocations: 100 }),
    });
    const { queryByTestId } = renderWithAppState(<DashboardPage />);
    expect(queryByTestId("hero-card-single-failure")).toBeNull();
    expect(queryByTestId("hero-card-multiple-failures")).toBeNull();
    expect(queryByTestId("hero-card-first-install")).toBeNull();
  });

  it("shows single-failure hero when exactly one app has failed", () => {
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "app_a", status: "failed" }),
        createAppGridEntry({ app_key: "app_b", status: "running" }),
      ],
      errorsData: [createHandlerError({ app_key: "app_a" })],
      kpisData: createKpis({ total_errors: 1 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("hero-card-single-failure")).toBeDefined();
  });

  it("single-failure hero shows failing app name", () => {
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "my_broken_app", display_name: "My Broken App", status: "failed" }),
        createAppGridEntry({ app_key: "ok_app", status: "running" }),
      ],
      errorsData: [createHandlerError({ app_key: "my_broken_app", error_type: "AttributeError", handler_method: "notify" })],
      kpisData: createKpis({ total_errors: 1 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const hero = getByTestId("hero-card-single-failure");
    expect(hero.textContent).toContain("My Broken App");
  });

  it("shows multiple-failures hero when 2+ apps have failed", () => {
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "app_a", status: "failed" }),
        createAppGridEntry({ app_key: "app_b", status: "failed" }),
        createAppGridEntry({ app_key: "app_c", status: "running" }),
      ],
      errorsData: [
        createHandlerError({ app_key: "app_a" }),
        createHandlerError({ app_key: "app_b", listener_id: 2 }),
      ],
      kpisData: createKpis({ total_errors: 3 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("hero-card-multiple-failures")).toBeDefined();
  });

  it("multiple-failures hero shows failure count", () => {
    setupScopedApi({
      appGridData: [
        createAppGridEntry({ app_key: "app_a", status: "failed" }),
        createAppGridEntry({ app_key: "app_b", status: "failed" }),
        createAppGridEntry({ app_key: "app_c", status: "failed" }),
      ],
      errorsData: [],
      kpisData: createKpis({ total_errors: 5 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const hero = getByTestId("hero-card-multiple-failures");
    expect(hero.textContent).toMatch(/3 apps? (fail|are failing)/i);
  });
});

describe("DashboardPage — framework error banner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("renders framework error banner when boot issues exist", () => {
    setupUseApi([{ severity: "err", label: "config validation", detail: "some detail" }]);
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("framework-error-banner")).toBeDefined();
  });

  it("does not render framework error banner when no boot issues", () => {
    setupUseApi([]);
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { queryByTestId } = renderWithAppState(<DashboardPage />);
    expect(queryByTestId("framework-error-banner")).toBeNull();
  });

  it("shows error count and top issue detail in banner", () => {
    setupUseApi([
      { severity: "err", label: "config validation", detail: "buggy_app: no class_name" },
      { severity: "warn", label: "deprecated decorator", detail: "@on_event deprecated" },
    ]);
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const banner = getByTestId("framework-error-banner");
    expect(banner.textContent).toMatch(/1 error/i);
    expect(banner.textContent).toContain("config validation");
  });
});

describe("DashboardPage — recent errors as table", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("renders recent errors table when errors exist", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10, total_errors: 1 }),
      errorsData: [createHandlerError({ app_key: "my_app", error_type: "ValueError", handler_method: "on_event" })],
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("recent-errors-table")).toBeDefined();
  });

  it("renders error table columns: TIME, APP, LOCATION, EXCEPTION, AGE", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10, total_errors: 1 }),
      errorsData: [createHandlerError()],
    });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    const table = getByTestId("recent-errors-table");
    expect(table.textContent).toMatch(/time/i);
    expect(table.textContent).toMatch(/app/i);
    expect(table.textContent).toMatch(/exception/i);
    expect(table.textContent).toMatch(/age/i);
  });

  it("renders tier filter toggle (All/Apps/Framework)", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10, total_errors: 1 }),
      errorsData: [createHandlerError()],
    });
    const { getByText } = renderWithAppState(<DashboardPage />);
    expect(getByText("All")).toBeDefined();
    expect(getByText("Apps")).toBeDefined();
    expect(getByText("Framework")).toBeDefined();
  });

  it("does not render errors table when no errors", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10 }),
      errorsData: [],
    });
    const { queryByTestId } = renderWithAppState(<DashboardPage />);
    expect(queryByTestId("recent-errors-table")).toBeNull();
  });

  it("'All' is the active tier filter by default when errors exist", () => {
    setupScopedApi({
      appGridData: [createAppGridEntry({ status: "running" })],
      kpisData: createKpis({ total_invocations: 10, total_errors: 1 }),
      errorsData: [createHandlerError()],
    });
    const { container } = renderWithAppState(<DashboardPage />);
    const allBtn = Array.from(container.querySelectorAll(".ht-tier-toggle__btn")).find(
      (el) => el.textContent === "All",
    );
    expect(allBtn?.className).toContain("ht-tier-toggle__btn--active");
  });

  it("clicking Apps tier filter changes active filter", () => {
    let callCount = 0;
    useScopedApi.mockImplementation(() => {
      callCount++;
      const pos = ((callCount - 1) % 3);
      if (pos === 0) return fakeApiResult(createKpis({ total_invocations: 10, total_errors: 1 }));
      if (pos === 1) return fakeApiResult([createAppGridEntry()]);
      return fakeApiResult([createHandlerError()]);
    });
    const { container, getByText } = renderWithAppState(<DashboardPage />);
    fireEvent.click(getByText("Apps"));
    const allBtns = container.querySelectorAll(".ht-tier-toggle__btn");
    const activeBtn = Array.from(allBtns).find((el) => el.className.includes("--active"));
    expect(activeBtn?.textContent).toBe("Apps");
  });
});

describe("DashboardPage — KPI / AppGrid error states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("shows KPI error message when kpis fetch fails", () => {
    setupScopedApi({ kpisError: "KPI fetch failed" });
    const { getByText } = renderWithAppState(<DashboardPage />);
    expect(getByText(/Failed to load KPIs: KPI fetch failed/)).toBeDefined();
  });

  it("shows AppGrid error message when app grid fetch fails", () => {
    setupScopedApi({ appGridError: "App grid failed" });
    const { getByText } = renderWithAppState(<DashboardPage />);
    expect(getByText(/Failed to load app grid: App grid failed/)).toBeDefined();
  });
});

describe("DashboardPage — telemetry degraded banner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupUseApi();
  });

  it("shows telemetry degraded banner when telemetryDegraded is true", () => {
    setupScopedApi();
    const { getByTestId } = renderWithAppState(<DashboardPage />, {
      stateOverrides: { telemetryDegraded: signal(true), droppedOverflow: signal(5) },
    });
    expect(getByTestId("telemetry-degraded-banner")).toBeDefined();
  });

  it("does not show telemetry degraded banner when telemetryDegraded is false", () => {
    setupScopedApi();
    const { queryByTestId } = renderWithAppState(<DashboardPage />, {
      stateOverrides: { telemetryDegraded: signal(false), droppedOverflow: signal(0) },
    });
    expect(queryByTestId("telemetry-degraded-banner")).toBeNull();
  });
});

describe("DashboardPage — debounced refetch on appStatus change", () => {
  it("calls useDebouncedEffect with a callback that invokes refetch", async () => {
    useScopedApi.mockReset();
    useDebouncedEffect.mockReset();

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
      const pos = ((callCount - 1) % 3);
      if (pos === 0) return { data: signal(createKpis()), loading: signal(false), error: signal(null), refetch: kpisRefetch };
      if (pos === 1) return { data: signal([]), loading: signal(false), error: signal(null), refetch: appGridRefetch };
      return { data: signal([]), loading: signal(false), error: signal(null), refetch: errorsRefetch };
    });

    setupUseApi();
    renderWithAppState(<DashboardPage />);

    expect(capturedCallback).not.toBeNull();
    expect(useDebouncedEffect).toHaveBeenCalled();

    capturedCallback!();

    expect(kpisRefetch).toHaveBeenCalled();
    expect(appGridRefetch).toHaveBeenCalled();
    expect(errorsRefetch).toHaveBeenCalled();
  });

  it("useDebouncedEffect is called with 500ms delay and 2000ms maxWait", () => {
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
});
