import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { HandlersPage } from "./handlers";
import { renderWithAppState } from "../test/render-helpers";
import { createListener, createJob } from "../test/factories";
import { getAllListeners, getAllJobs } from "../api/endpoints";

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

vi.mock("../hooks/use-api", () => ({
  useApi: vi.fn(),
}));

const useApiMod = await import("../hooks/use-api");
const useApi = useApiMod.useApi as unknown as ReturnType<typeof vi.fn>;

function fakeApiResult<T>(data: T | null, loading = false, error: string | null = null) {
  return {
    data: signal(data),
    loading: signal(loading),
    error: signal(error),
    refetch: vi.fn(),
  };
}

/** Set up useApi to return different data based on which fetcher is called. */
function setupApi({
  listeners = [] as ReturnType<typeof createListener>[],
  jobs = [] as ReturnType<typeof createJob>[],
  loading = false,
} = {}) {
  useApi.mockImplementation((fetcher: () => unknown) => {
    if (fetcher === getAllListeners) return fakeApiResult(listeners, loading);
    if (fetcher === getAllJobs) return fakeApiResult(jobs, loading);
    return fakeApiResult(null);
  });
}

describe("HandlersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi();
  });

  it("renders with handlers tab active by default", () => {
    const { getByRole } = renderWithAppState(<HandlersPage />);
    const handlersTab = getByRole("button", { name: /^handlers/i });
    expect(handlersTab.getAttribute("aria-pressed")).toBe("true");
  });

  it("shows the page heading", () => {
    const { getByRole } = renderWithAppState(<HandlersPage />);
    expect(getByRole("heading", { name: /handlers/i })).toBeDefined();
  });

  it("switches to jobs tab when clicked", () => {
    const { getByRole, getByTestId } = renderWithAppState(<HandlersPage />);
    const jobsTab = getByRole("button", { name: /^jobs/i });
    fireEvent.click(jobsTab);
    expect(jobsTab.getAttribute("aria-pressed")).toBe("true");
    // handlers tab should no longer be active
    const handlersTab = getByRole("button", { name: /^handlers/i });
    expect(handlersTab.getAttribute("aria-pressed")).toBe("false");
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

  it("includes framework handlers when tier toggle is enabled", () => {
    setupApi({
      listeners: [
        createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
      ],
    });
    const { getAllByTestId, getByRole } = renderWithAppState(<HandlersPage />);
    const toggle = getByRole("checkbox", { name: /include framework/i });
    fireEvent.click(toggle);
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
    fireEvent.click(getByRole("button", { name: /^jobs/i }));
    expect(getAllByTestId(/job-row-/).length).toBe(2);
  });

  it("shows empty state on jobs tab when no jobs", () => {
    const { getByRole, getByText } = renderWithAppState(<HandlersPage />);
    fireEvent.click(getByRole("button", { name: /^jobs/i }));
    expect(getByText(/no jobs scheduled/i)).toBeDefined();
  });
});
