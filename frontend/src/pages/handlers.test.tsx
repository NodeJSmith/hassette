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
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
      ],
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" }),
      ],
    });
    const { getAllByTestId } = renderWithAppState(<HandlersPage />);
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
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
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });

  it("shows all tiers when 'All' button is clicked", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
      ],
    });
    const { getAllByTestId, getByRole } = renderWithAppState(<HandlersPage />);
    fireEvent.click(getByRole("button", { name: /^all$/i }));
    expect(getAllByTestId(/handler-row-/).length).toBe(2);
  });

  it("filters by selected app", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_change", source_tier: "app" }),
      ],
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, getByTestId } = renderWithAppState(<HandlersPage />);
    fireEvent.change(getByTestId("handlers-app-filter"), { target: { value: "app_a" } });
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });

  it("renders a search input", () => {
    const { getByPlaceholderText } = renderWithAppState(<HandlersPage />);
    expect(getByPlaceholderText("Search...")).toBeDefined();
  });

  it("search filters by handler name", () => {
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

  it("search filters by app_key", () => {
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

  it("search is case-insensitive", () => {
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

  it("search filters jobs by job_name", () => {
    setupApi({
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
        createJob({ job_id: 11, app_key: "app_b", job_name: "hourly_ping", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, getByPlaceholderText } = renderWithAppState(<HandlersPage />);
    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "backup" } });
    expect(getAllByTestId(/job-row-/).length).toBe(1);
  });

  it("search filters across both handlers and jobs simultaneously", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
      ],
      jobs: [
        createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
        createJob({ job_id: 11, app_key: "app_b", job_name: "hourly_ping", source_tier: "app" }),
      ],
    });
    const { getAllByTestId, getByPlaceholderText, queryAllByTestId } = renderWithAppState(<HandlersPage />);
    fireEvent.input(getByPlaceholderText("Search..."), { target: { value: "app_a" } });
    expect(getAllByTestId(/handler-row-/).length).toBe(1);
    expect(getAllByTestId(/job-row-/).length).toBe(1);
    expect(queryAllByTestId(/job-row-j-11/).length).toBe(0);
  });
});
