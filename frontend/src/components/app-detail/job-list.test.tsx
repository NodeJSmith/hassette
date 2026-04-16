import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, within } from "@testing-library/preact";
import { JobList } from "./job-list";
import type { JobData } from "../../api/endpoints";

// Mock wouter useSearch to control URL search params in tests
vi.mock("wouter", () => ({
  useSearch: vi.fn(() => ""),
}));

// Mock JobRow to isolate JobList behavior
vi.mock("./job-row", () => ({
  JobRow: ({ job, onGroupClick }: { job: JobData; onGroupClick?: (g: string) => void }) => (
    <div
      data-testid={`job-row-${job.job_id}`}
      data-group={job.group ?? ""}
      data-job-name={job.job_name}
    >
      {job.group && onGroupClick && (
        <button
          type="button"
          data-testid={`group-pill-${job.job_id}`}
          onClick={() => onGroupClick(job.group!)}
        >
          {job.group}
        </button>
      )}
    </div>
  ),
}));

const useSearchMod = await import("wouter");
const useSearch = useSearchMod.useSearch as unknown as ReturnType<typeof vi.fn>;

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

describe("JobList", () => {
  beforeEach(() => {
    useSearch.mockReturnValue("");
    vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("test_no_chip_bar_when_fewer_than_two_groups — single group renders no chip bar", () => {
    const jobs = [
      createJob({ job_id: 1, job_name: "job1", group: "morning" }),
      createJob({ job_id: 2, job_name: "job2", group: "morning" }),
    ];
    const { queryByTestId } = render(<JobList jobs={jobs} />);
    expect(queryByTestId("group-filter-bar")).toBeNull();
  });

  it("test_chip_bar_renders_when_two_or_more_groups — 2+ groups shows All + group chips", () => {
    const jobs = [
      createJob({ job_id: 1, job_name: "job1", group: "morning" }),
      createJob({ job_id: 2, job_name: "job2", group: "evening" }),
    ];
    const { getByTestId } = render(<JobList jobs={jobs} />);
    const filterBar = getByTestId("group-filter-bar");
    expect(filterBar).toBeDefined();
    expect(within(filterBar).getByText("All")).toBeDefined();
    expect(within(filterBar).getByText("morning")).toBeDefined();
    expect(within(filterBar).getByText("evening")).toBeDefined();
  });

  it("test_chip_click_filters_jobs — clicking a group chip hides non-matching jobs", () => {
    const jobs = [
      createJob({ job_id: 1, job_name: "morning_job", group: "morning" }),
      createJob({ job_id: 2, job_name: "evening_job", group: "evening" }),
    ];
    const { getByTestId, queryByTestId } = render(<JobList jobs={jobs} />);
    const filterBar = getByTestId("group-filter-bar");
    fireEvent.click(within(filterBar).getByText("morning"));
    expect(queryByTestId("job-row-1")).toBeDefined();
    expect(queryByTestId("job-row-2")).toBeNull();
  });

  it("test_all_chip_resets_filter — clicking All shows all jobs", () => {
    const jobs = [
      createJob({ job_id: 1, job_name: "morning_job", group: "morning" }),
      createJob({ job_id: 2, job_name: "evening_job", group: "evening" }),
    ];
    const { getByTestId, queryByTestId } = render(<JobList jobs={jobs} />);
    const filterBar = getByTestId("group-filter-bar");
    // First filter to morning
    fireEvent.click(within(filterBar).getByText("morning"));
    expect(queryByTestId("job-row-2")).toBeNull();
    // Then click All
    fireEvent.click(within(filterBar).getByText("All"));
    expect(queryByTestId("job-row-1")).toBeDefined();
    expect(queryByTestId("job-row-2")).toBeDefined();
  });

  it("test_filter_resets_on_jobs_prop_change — instance switch resets filter", () => {
    const jobsA = [
      createJob({ job_id: 1, job_name: "morning_job", group: "morning" }),
      createJob({ job_id: 2, job_name: "evening_job", group: "evening" }),
    ];
    const jobsB = [
      createJob({ job_id: 3, job_name: "night_job", group: "night" }),
      createJob({ job_id: 4, job_name: "dawn_job", group: "dawn" }),
    ];
    const { getByTestId, queryByTestId, rerender } = render(<JobList jobs={jobsA} />);
    const filterBar = getByTestId("group-filter-bar");
    // Filter to morning
    fireEvent.click(within(filterBar).getByText("morning"));
    expect(queryByTestId("job-row-2")).toBeNull();
    // Switch instances — rerender with new jobs
    rerender(<JobList jobs={jobsB} />);
    // Both new jobs should be visible (filter reset)
    expect(queryByTestId("job-row-3")).toBeDefined();
    expect(queryByTestId("job-row-4")).toBeDefined();
  });

  it("test_no_results_message_when_filter_matches_nothing — shows empty state message", () => {
    // Mock useSearch to return a group param that doesn't match any job
    useSearch.mockReturnValue("group=night");
    const jobs = [
      createJob({ job_id: 10, job_name: "morning_job", group: "morning" }),
      createJob({ job_id: 11, job_name: "evening_job", group: "evening" }),
    ];
    const { queryByTestId, getByTestId } = render(<JobList jobs={jobs} />);
    expect(queryByTestId("job-row-10")).toBeNull();
    expect(queryByTestId("job-row-11")).toBeNull();
    expect(getByTestId("no-filter-results")).toBeDefined();
    expect(getByTestId("no-filter-results").textContent).toBe("No jobs match this filter");
  });

  it("test_group_click_callback_sets_filter — onGroupClick from child JobRow sets group filter", () => {
    const jobs = [
      createJob({ job_id: 1, job_name: "morning_job", group: "morning" }),
      createJob({ job_id: 2, job_name: "evening_job", group: "evening" }),
    ];
    const { getByTestId, queryByTestId } = render(<JobList jobs={jobs} />);
    // Click the group pill button inside the mocked JobRow for job 1 (morning)
    fireEvent.click(getByTestId("group-pill-1"));
    // job-row-2 (evening) should be hidden, job-row-1 (morning) should be visible
    expect(queryByTestId("job-row-1")).toBeDefined();
    expect(queryByTestId("job-row-2")).toBeNull();
  });
});
