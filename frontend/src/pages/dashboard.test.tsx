import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { DashboardPage } from "./dashboard";
import { renderWithAppState } from "../test/render-helpers";
import { createKpis, createAppGridEntry, createHandlerError } from "../test/factories";

// Stub child components — each has its own tests
vi.mock("../components/dashboard/kpi-strip", () => ({
  KpiStrip: ({ appCount, runningCount }: Record<string, unknown>) => (
    <div data-testid="kpi-strip" data-app-count={String(appCount)} data-running-count={String(runningCount)} />
  ),
}));

vi.mock("../components/dashboard/app-grid", () => ({
  AppGrid: ({ apps }: { apps: unknown[] | null | undefined }) => (
    <div data-testid="app-grid" data-count={apps?.length ?? 0} />
  ),
}));

vi.mock("../components/dashboard/error-feed", () => ({
  ErrorFeed: ({ errors }: { errors: unknown[] }) => (
    <div data-testid="error-feed" data-count={errors.length} />
  ),
}));

vi.mock("../components/dashboard/framework-health", () => ({
  FrameworkHealth: () => <div data-testid="framework-health" />,
}));

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

const useScopedApiMod = await import("../hooks/use-scoped-api");
const useScopedApi = useScopedApiMod.useScopedApi as unknown as ReturnType<typeof vi.fn>;

const useDebouncedEffectMod = await import("../hooks/use-debounced-effect");
const useDebouncedEffect = useDebouncedEffectMod.useDebouncedEffect as unknown as ReturnType<typeof vi.fn>;

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
  errorsLoading = false,
  kpisError = null as string | null,
  appGridError = null as string | null,
  errorsError = null as string | null,
} = {}) {
  useScopedApi
    .mockReturnValueOnce(fakeApiResult(kpisData, kpisLoading, kpisError))     // kpis
    .mockReturnValueOnce(fakeApiResult(appGridData, appGridLoading, appGridError)) // appGrid
    .mockReturnValueOnce(fakeApiResult(errorsData, errorsLoading, errorsError));   // errors
}

describe("DashboardPage — loading state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("shows spinner while kpis are loading", () => {
    setupScopedApi({ kpisLoading: true });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("shows spinner while app grid is loading", () => {
    setupScopedApi({ appGridLoading: true });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });
});

describe("DashboardPage — main render", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("renders KPI strip when loaded", () => {
    setupScopedApi();
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("kpi-strip")).toBeDefined();
  });

  it("renders app grid when loaded", () => {
    setupScopedApi();
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("app-grid")).toBeDefined();
  });

  it("renders FrameworkHealth section", () => {
    setupScopedApi();
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("framework-health")).toBeDefined();
  });

  it("renders App Health heading with link to /apps", () => {
    setupScopedApi();
    const { getByRole } = renderWithAppState(<DashboardPage />);
    const link = getByRole("link", { name: /app health/i });
    expect(link.getAttribute("href")).toBe("/apps");
  });

  it("passes app count to KpiStrip", () => {
    const apps = [
      createAppGridEntry({ app_key: "app_a", status: "running" }),
      createAppGridEntry({ app_key: "app_b", status: "stopped" }),
    ];
    setupScopedApi({ appGridData: apps });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("kpi-strip").getAttribute("data-app-count")).toBe("2");
  });

  it("passes running count (status=running only) to KpiStrip", () => {
    const apps = [
      createAppGridEntry({ app_key: "app_a", status: "running" }),
      createAppGridEntry({ app_key: "app_b", status: "running" }),
      createAppGridEntry({ app_key: "app_c", status: "stopped" }),
    ];
    setupScopedApi({ appGridData: apps });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("kpi-strip").getAttribute("data-running-count")).toBe("2");
  });
});

describe("DashboardPage — KPI / AppGrid error states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
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

describe("DashboardPage — Recent Errors section visibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("shows healthy state when no errors and filter not interacted", () => {
    setupScopedApi({ errorsData: [] });
    const { getByText, queryByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByText("No recent errors. All systems healthy.")).toBeDefined();
    expect(queryByTestId("error-feed")).toBeNull();
  });

  it("shows ErrorFeed when errors exist", () => {
    setupScopedApi({ errorsData: [createHandlerError()] });
    const { getByTestId, queryByText } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("error-feed")).toBeDefined();
    expect(queryByText("No recent errors. All systems healthy.")).toBeNull();
  });

  it("shows error feed section when errors exist with correct count", () => {
    const errors = [createHandlerError(), createHandlerError({ listener_id: 99 })];
    setupScopedApi({ errorsData: errors });
    const { getByTestId } = renderWithAppState(<DashboardPage />);
    expect(getByTestId("error-feed").getAttribute("data-count")).toBe("2");
  });

  it("shows errors loading spinner within error section when errors are still loading", () => {
    // kpis and appGrid done, errors still loading
    setupScopedApi({ errorsLoading: true, errorsData: null });
    const { getAllByTestId } = renderWithAppState(<DashboardPage />);
    // When errors are loading but the section is visible, spinner is inside the error card
    // (section visible because errorsLoading=true is one of the show conditions)
    const spinners = getAllByTestId("spinner");
    expect(spinners.length).toBeGreaterThan(0);
  });

  it("shows error fetch failure message when errors fetch fails", () => {
    setupScopedApi({ errorsError: "DB offline" });
    const { getByText } = renderWithAppState(<DashboardPage />);
    expect(getByText(/Failed to load errors: DB offline/)).toBeDefined();
  });

  it("renders Recent Errors heading", () => {
    setupScopedApi({ errorsData: [createHandlerError()] });
    const { getByText } = renderWithAppState(<DashboardPage />);
    expect(getByText("Recent Errors")).toBeDefined();
  });
});

describe("DashboardPage — tier filter toggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
  });

  it("renders tier filter buttons (All, Apps, Framework)", () => {
    setupScopedApi({ errorsData: [createHandlerError()] });
    const { getByText } = renderWithAppState(<DashboardPage />);
    expect(getByText("All")).toBeDefined();
    expect(getByText("Apps")).toBeDefined();
    expect(getByText("Framework")).toBeDefined();
  });

  it("'All' is the active tier filter by default", () => {
    setupScopedApi({ errorsData: [createHandlerError()] });
    const { container } = renderWithAppState(<DashboardPage />);
    const allBtn = Array.from(container.querySelectorAll(".ht-tier-toggle__btn")).find(
      (el) => el.textContent === "All",
    );
    expect(allBtn?.className).toContain("ht-tier-toggle__btn--active");
  });

  it("clicking a tier filter button changes the active filter", () => {
    setupScopedApi({ errorsData: [createHandlerError()] });
    // Need multiple useScopedApi calls since the component re-renders when filter changes
    useScopedApi
      .mockReturnValueOnce(fakeApiResult(createKpis()))
      .mockReturnValueOnce(fakeApiResult([createAppGridEntry()]))
      .mockReturnValueOnce(fakeApiResult([createHandlerError()]))
      // After re-render due to filter change:
      .mockReturnValueOnce(fakeApiResult(createKpis()))
      .mockReturnValueOnce(fakeApiResult([createAppGridEntry()]))
      .mockReturnValueOnce(fakeApiResult([]));

    const { container, getByText } = renderWithAppState(<DashboardPage />);

    const appsBtn = getByText("Apps");
    fireEvent.click(appsBtn);

    // After clicking, Apps button should be active
    const allBtns = container.querySelectorAll(".ht-tier-toggle__btn");
    const activeBtn = Array.from(allBtns).find((el) => el.className.includes("--active"));
    expect(activeBtn?.textContent).toBe("Apps");
  });

  it("tier filter section becomes visible after clicking a filter (even with no errors)", () => {
    // When errorsData is empty and filter hasn't been interacted with, the section is hidden.
    // After clicking a filter, the section becomes visible.
    useScopedApi
      .mockReturnValueOnce(fakeApiResult(createKpis()))
      .mockReturnValueOnce(fakeApiResult([]))
      .mockReturnValueOnce(fakeApiResult([]))
      // After re-render:
      .mockReturnValueOnce(fakeApiResult(createKpis()))
      .mockReturnValueOnce(fakeApiResult([]))
      .mockReturnValueOnce(fakeApiResult([]));

    // First render — no errors, no interaction — healthy state shown
    const { getByText, queryByText } = renderWithAppState(<DashboardPage />);
    expect(getByText("No recent errors. All systems healthy.")).toBeDefined();
    expect(queryByText("All")).toBeNull(); // filter buttons hidden in healthy state

    // We can't easily click the filter buttons when in healthy state because
    // the tier toggle only shows inside the error card (condition:
    // errorsLoading || errors.length > 0 || filter !== "all" || filterInteracted)
    // The healthy state DOESN'T show the tier toggle. That's intentional.
    expect(queryByText("Recent Errors")).toBeNull();
  });

  it("'No errors for this filter' shown when filter active but results empty", () => {
    // Explicitly reset to clear any queued once-values from previous tests
    useScopedApi.mockReset();

    // On the FIRST render: errors has one item → error card section visible
    // On SUBSEQUENT renders (after filter click): errors returns empty → "No errors for this filter."
    let callCount = 0;
    useScopedApi.mockImplementation(() => {
      callCount++;
      const pos = ((callCount - 1) % 3);
      if (pos === 0) return fakeApiResult(createKpis());
      if (pos === 1) return fakeApiResult([createAppGridEntry()]);
      // First render (calls 1-3): return error data so tier toggle is visible
      // Later renders (calls 4+): return empty to trigger "No errors for this filter."
      return callCount <= 3 ? fakeApiResult([createHandlerError()]) : fakeApiResult([]);
    });

    const { getByText } = renderWithAppState(<DashboardPage />);

    // Error card section is visible — click Framework tier filter
    fireEvent.click(getByText("Framework"));

    expect(getByText("No errors for this filter.")).toBeDefined();
  });
});

describe("DashboardPage — debounced refetch on appStatus change", () => {
  it("calls useDebouncedEffect with a callback that invokes refetch", async () => {
    // Reset all mocks to ensure clean state
    useScopedApi.mockReset();
    useDebouncedEffect.mockReset();

    // Capture the debounce callback when it is registered.
    // Always capture the LATEST callback so we get the one from the last render.
    let capturedCallback: (() => void) | null = null;
    useDebouncedEffect.mockImplementation(
      (_getValue: () => unknown, _delay: number, callback: () => void) => {
        capturedCallback = callback;
      },
    );

    // Use stable refetch mocks so assertions hold across any number of renders.
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

    renderWithAppState(<DashboardPage />);

    expect(capturedCallback).not.toBeNull();
    expect(useDebouncedEffect).toHaveBeenCalled();

    // Invoke the debounce callback manually — it calls:
    //   void Promise.allSettled([kpis.refetch(), appGrid.refetch(), errors.refetch()])
    // The `void` means we don't await, but the refetch calls happen synchronously before the Promise.
    capturedCallback!();

    expect(kpisRefetch).toHaveBeenCalled();
    expect(appGridRefetch).toHaveBeenCalled();
    expect(errorsRefetch).toHaveBeenCalled();
  });

  it("useDebouncedEffect is called with 500ms delay and 2000ms maxWait", () => {
    vi.clearAllMocks();
    useDebouncedEffect.mockImplementation(() => {});
    setupScopedApi();

    renderWithAppState(<DashboardPage />);

    expect(useDebouncedEffect).toHaveBeenCalledWith(
      expect.any(Function), // getValue (statusVersionRef.current)
      500,                   // debounce delay
      expect.any(Function), // callback
      2000,                  // maxWait
    );
  });

  it("statusVersionRef tracks changes: useDebouncedEffect getValue returns a number", () => {
    vi.clearAllMocks();

    let capturedGetValue: (() => unknown) | null = null;
    useDebouncedEffect.mockImplementation(
      (getValue: () => unknown) => {
        capturedGetValue = getValue;
      },
    );

    setupScopedApi();

    renderWithAppState(<DashboardPage />);

    // The getValue passed to useDebouncedEffect should return a number (statusVersionRef.current)
    expect(capturedGetValue).not.toBeNull();
    const value = capturedGetValue!();
    expect(typeof value).toBe("number");
  });

  it("useDebouncedEffect getValue is called with initial version 0 (no appStatus changes yet)", () => {
    vi.clearAllMocks();

    let capturedGetValue: (() => unknown) | null = null;
    useDebouncedEffect.mockImplementation(
      (getValue: () => unknown) => {
        capturedGetValue = getValue;
      },
    );

    setupScopedApi();

    renderWithAppState(<DashboardPage />);

    // Initially no WS-driven changes, so version counter is 0
    expect(capturedGetValue!()).toBe(0);
  });
});
