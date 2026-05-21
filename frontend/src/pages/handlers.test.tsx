import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJob, createListener } from "../test/factories";
import { renderWithAppState } from "../test/render-helpers";
import { HandlersPage } from "./handlers";

// Mutable search string for tests that need to control query params
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/handlers", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

vi.mock("../hooks/use-scoped-api", () => ({
  useScopedApi: vi.fn(),
}));

const useScopedApiMod = await import("../hooks/use-scoped-api");
const useScopedApi = useScopedApiMod.useScopedApi as unknown as ReturnType<typeof vi.fn>;

function fakeApiResult<T>(data: T | null, loading = false, error: string | null = null) {
  return {
    data: signal(data),
    loading: signal(loading),
    error: signal(error),
    refetch: vi.fn(),
  };
}

function setupApi({
  listeners = [] as ReturnType<typeof createListener>[],
  jobs = [] as ReturnType<typeof createJob>[],
  loading = false,
} = {}) {
  const listenersResult = fakeApiResult(listeners, loading);
  const jobsResult = fakeApiResult(jobs, loading);
  useScopedApi.mockImplementation((fetcher: (since: number) => Promise<unknown>) => {
    const probe = fetcher.toString();
    if (probe.includes("getAllJobs")) return jobsResult;
    return listenersResult;
  });
}

describe("HandlersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
    setupApi();
  });

  it("shows the page heading", () => {
    const { getByRole } = renderWithAppState(<HandlersPage />);
    expect(getByRole("heading", { name: /handlers/i })).toBeDefined();
  });

  it("shows empty state when no handlers or jobs", () => {
    const { getByText } = renderWithAppState(<HandlersPage />);
    expect(getByText(/no handlers found/i)).toBeDefined();
  });

  it("renders both handler and job rows in a single table", () => {
    setupApi({
      listeners: [createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" })],
      jobs: [createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" })],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });

  it("filters out framework-tier items by default", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
      ],
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" }),
        createJob({ job_id: 11, app_key: "fw_app", job_name: "fw_job", source_tier: "framework" }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });

  it("filters by selected app when ?app=app_a is in URL", () => {
    mockSearch = "app=app_a";
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_change", source_tier: "app" }),
      ],
      jobs: [createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" })],
    });
    const { getAllByTestId, queryAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
    expect(queryAllByTestId("listener-row-h-2")).toHaveLength(0);
  });

  it("renders a search input above the table", () => {
    const { getByTestId } = renderWithAppState(<HandlersPage />);
    const search = getByTestId("handlers-search");
    expect(search).toBeDefined();
    // Search should be inside the search slot (data-search-bar attribute)
    const searchBar = search.closest("[data-search-bar]");
    expect(searchBar).not.toBeNull();
  });

  it("search filters by handler name when ?search= is in URL", () => {
    mockSearch = "search=motion";
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_motion_detected", source_tier: "app" }),
        createListener({
          listener_id: 2,
          app_key: "app_b",
          handler_method: "on_temperature_change",
          source_tier: "app",
        }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
  });

  it("search filters by app_key when ?search= is in URL", () => {
    mockSearch = "search=climate";
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "climate_app", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "alarm_app", handler_method: "on_event", source_tier: "app" }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
  });

  it("search is case-insensitive when ?search= is in URL", () => {
    mockSearch = "search=onmotion";
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "OnMotionDetected", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_temperature", source_tier: "app" }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
  });

  it("search filters jobs by job_name when ?search= is in URL", () => {
    mockSearch = "search=backup";
    setupApi({
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
        createJob({ job_id: 11, app_key: "app_b", job_name: "hourly_ping", source_tier: "app" }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });

  it("search filters across both handlers and jobs simultaneously when ?search= is in URL", () => {
    mockSearch = "search=app_a";
    setupApi({
      listeners: [createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" })],
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
        createJob({ job_id: 11, app_key: "app_b", job_name: "hourly_ping", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, queryAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
    expect(queryAllByTestId(/job-row-j-11/).length).toBe(0);
  });

  it("renders a footer with handler and job counts", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_a", handler_method: "on_change", source_tier: "app" }),
      ],
      jobs: [createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" })],
    });
    const { getByText } = renderWithAppState(<HandlersPage />);
    expect(getByText(/2 handlers/i)).toBeDefined();
    expect(getByText(/1 job/i)).toBeDefined();
  });

  it("renders an app column filter button (funnel icon) on the app column header", () => {
    setupApi({
      listeners: [createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" })],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    const filterBtns = getAllByTestId("filter-btn");
    expect(filterBtns.length).toBe(1);
  });
});

describe("HandlersPage — query param state (FR#5, AC#6)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
      ],
      jobs: [createJob({ job_id: 10, app_key: "app_b", job_name: "my_job", source_tier: "app" })],
    });
  });

  it("reads search from URL query param — ?search=event filters results", () => {
    // "on_event" is the app-tier handler; default tier=app, so search "event" should return it
    mockSearch = "search=event";
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
  });

  it("reads app filter from URL query param — ?app=app_a filters to that app", () => {
    mockSearch = "app=app_a";
    const { getAllByTestId, queryAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/listener-row-/).length).toBe(1);
    // app_b job should be excluded
    expect(queryAllByTestId(/job-row-/).length).toBe(0);
  });

  it("changing sort calls qp.set with replace (no new history entry — AC#6)", () => {
    setupApi({
      listeners: [createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" })],
    });
    const { getByRole } = renderWithAppState(<HandlersPage />);
    // SortHeader renders a <th><button> — click the button, not the th
    fireEvent.click(getByRole("button", { name: /^name/i }));
    expect(mockNavigate).toHaveBeenCalledWith(expect.stringContaining("sort=name"), { replace: true });
  });

  it("handler deep-links use /apps/:key/handlers/:id format in desktop table", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 42, app_key: "motion_lights", handler_method: "on_motion", source_tier: "app" }),
      ],
    });
    const { getByRole } = renderWithAppState(<HandlersPage />);
    const link = getByRole("link", { name: /on_motion/i });
    expect((link as HTMLAnchorElement).href).toContain("/apps/motion_lights/handlers/h-42");
  });
});
