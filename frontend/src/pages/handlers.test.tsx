import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { HandlersPage } from "./handlers";
import { renderWithAppState } from "../test/render-helpers";
import { createListener, createJob } from "../test/factories";


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

/** Set up useScopedApi to return different data based on which fetcher is called. */
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
    setupApi();
  });

  it("renders with handlers tab active by default", () => {
    const { getByRole } = renderWithAppState(<HandlersPage />);
    const handlersTab = getByRole("tab", { name: /^handlers/i });
    expect(handlersTab.getAttribute("aria-selected")).toBe("true");
  });

  it("shows the page heading", () => {
    const { getByRole } = renderWithAppState(<HandlersPage />);
    expect(getByRole("heading", { name: /handlers/i })).toBeDefined();
  });

  it("switches to jobs tab when clicked", () => {
    const { getByRole, getByTestId } = renderWithAppState(<HandlersPage />);
    const jobsTab = getByRole("tab", { name: /^jobs/i });
    fireEvent.click(jobsTab);
    expect(jobsTab.getAttribute("aria-selected")).toBe("true");
    // handlers tab should no longer be active
    const handlersTab = getByRole("tab", { name: /^handlers/i });
    expect(handlersTab.getAttribute("aria-selected")).toBe("false");
    // jobs empty state renders (beforeEach provides empty jobs)
    expect(getByTestId("jobs-empty")).toBeDefined();
  });

  it("shows empty state when no handlers registered", () => {
    const { getByText } = renderWithAppState(<HandlersPage />);
    expect(getByText(/no handlers registered/i)).toBeDefined();
  });

  it("renders handler rows for each app-tier listener", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_change", source_tier: "app" }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/handler-row-/).length).toBe(2);
  });

  it("filters out framework-tier handlers by default", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
  });

  it("includes framework handlers when 'all' tier button is clicked", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
      ],
    });
    const { getAllByTestId, getByRole } = renderWithAppState(<HandlersPage />);
    const allBtn = getByRole("button", { name: /^all$/i });
    fireEvent.click(allBtn);
    expect(getAllByTestId(/handler-row-/).length).toBe(2);
  });

  it("filters handlers by selected app", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_change", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, getByTestId } = renderWithAppState(<HandlersPage />);
    const filterSelect = getByTestId("handlers-app-filter");
    fireEvent.change(filterSelect, { target: { value: "app_a" } });
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
  });

  it("renders job rows on jobs tab", () => {
    setupApi({
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" }),
        createJob({ job_id: 11, app_key: "app_b", job_name: "other_job", source_tier: "app" }),
      ],
    });
    const { getByRole, getAllByTestId } = renderWithAppState(<HandlersPage />);
    fireEvent.click(getByRole("tab", { name: /^jobs/i }));
    expect(getAllByTestId(/job-row-/).length).toBe(2);
  });

  it("shows empty state on jobs tab when no jobs", () => {
    const { getByRole, getByText } = renderWithAppState(<HandlersPage />);
    fireEvent.click(getByRole("tab", { name: /^jobs/i }));
    expect(getByText(/no jobs scheduled/i)).toBeDefined();
  });

  it("renders a search input for handlers", () => {
    const { getByPlaceholderText } = renderWithAppState(<HandlersPage />);
    expect(getByPlaceholderText("Search...")).toBeDefined();
  });

  it("filters handlers by search text in handler_method", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_motion_detected", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_temperature_change", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, getByPlaceholderText } = renderWithAppState(<HandlersPage />);
    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "motion" } });
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
  });

  it("filters handlers by search text in app_key", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "climate_app", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "alarm_app", handler_method: "on_event", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, getByPlaceholderText } = renderWithAppState(<HandlersPage />);
    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "climate" } });
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
  });

  it("search is case-insensitive for handlers", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "OnMotionDetected", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_temperature", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, getByPlaceholderText } = renderWithAppState(<HandlersPage />);
    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "onmotion" } });
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
  });

  it("filters jobs by search text in job_name on the jobs tab", () => {
    setupApi({
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
        createJob({ job_id: 11, app_key: "app_b", job_name: "hourly_ping", source_tier: "app" }),
      ],
    });
    const { getByRole, getAllByTestId, getByPlaceholderText } = renderWithAppState(<HandlersPage />);
    fireEvent.click(getByRole("tab", { name: /^jobs/i }));
    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "backup" } });
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });

  it("clears search when switching tabs", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_motion", source_tier: "app" }),
      ],
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
      ],
    });
    const { getByRole, getAllByTestId, getByPlaceholderText } = renderWithAppState(<HandlersPage />);

    // Filter handlers by search
    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "motion" } });
    expect(getAllByTestId(/handler-row-/).length).toBe(1);

    // Switch to jobs tab — search should clear, job row visible
    fireEvent.click(getByRole("tab", { name: /^jobs/i }));
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });
});
