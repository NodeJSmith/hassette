import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { JobRow } from "./job-row";
import type { JobData } from "../../api/endpoints";

vi.mock("../../hooks/use-relative-time", () => ({
  useRelativeTime: (ts: number | null) => (ts !== null ? "in 3m" : ""),
}));

vi.mock("../../hooks/use-scoped-api", () => ({
  useScopedApi: () => ({
    data: { value: null },
    loading: { value: false },
    refetch: vi.fn(),
  }),
}));

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

describe("JobRow", () => {
  it("renders trigger_label as primary subtitle", () => {
    const { getByText } = render(<JobRow job={createJob({ trigger_label: "Every 5 minutes" })} />);
    expect(getByText("Every 5 minutes")).toBeDefined();
  });

  it("renders trigger_detail as secondary dimmed span when non-null", () => {
    const { container } = render(
      <JobRow job={createJob({ trigger_label: "Every 5 minutes", trigger_detail: "offset: 30s" })} />,
    );
    const dimmedSpan = container.querySelector(".ht-text-muted");
    expect(dimmedSpan?.textContent).toContain("offset: 30s");
  });

  it("falls back to trigger_type when trigger_label is empty string", () => {
    const { getByText } = render(
      <JobRow job={createJob({ trigger_label: "", trigger_type: "cron" })} />,
    );
    expect(getByText("cron")).toBeDefined();
  });

  it("renders group pill when group is set", () => {
    const { getByText } = render(
      <JobRow job={createJob({ group: "morning" })} />,
    );
    const pill = getByText("morning");
    expect(pill).toBeDefined();
    expect(pill.className).toContain("ht-badge");
  });

  it("calls onGroupClick with group name when pill is clicked", () => {
    const onGroupClick = vi.fn();
    const { getByText } = render(
      <JobRow job={createJob({ group: "morning" })} onGroupClick={onGroupClick} />,
    );
    fireEvent.click(getByText("morning"));
    expect(onGroupClick).toHaveBeenCalledWith("morning");
  });

  it("renders jitter tag when jitter is set", () => {
    const { getByText } = render(
      <JobRow job={createJob({ jitter: 15 })} />,
    );
    expect(getByText("±15s")).toBeDefined();
  });

  it("renders cancelled badge when cancelled is true", () => {
    const { container } = render(
      <JobRow job={createJob({ cancelled: true })} />,
    );
    // Row should have muted/struck-through treatment or a cancelled badge
    const cancelledEl = container.querySelector(".ht-badge--cancelled, [data-testid='cancelled-badge'], .is-cancelled");
    const mutedEl = container.querySelector(".ht-text-muted");
    // At least one cancelled treatment should be visible
    expect(cancelledEl !== null || mutedEl !== null).toBe(true);
    // Verify "Cancelled" text appears
    expect(container.textContent).toContain("Cancelled");
  });

  it("shows next_run relative time in expanded detail when next_run is set", () => {
    const job = createJob({ next_run: 1700010000, total_executions: 5 });
    const { container, getByRole } = render(<JobRow job={job} />);
    const button = getByRole("button");
    fireEvent.click(button);
    const detail = container.querySelector(".ht-item-detail");
    expect(detail?.textContent).toContain("Next:");
    expect(detail?.textContent).toContain("in 3m");
  });

  it("hides next_run line when next_run is null", () => {
    const job = createJob({ next_run: null, total_executions: 5 });
    const { container, getByRole } = render(<JobRow job={job} />);
    const button = getByRole("button");
    fireEvent.click(button);
    const detail = container.querySelector(".ht-item-detail");
    expect(detail?.textContent).not.toContain("Next:");
  });

  it("shows jitter alongside next_run in expanded detail", () => {
    const job = createJob({ next_run: 1700010000, jitter: 15, total_executions: 5 });
    const { container, getByRole } = render(<JobRow job={job} />);
    const button = getByRole("button");
    fireEvent.click(button);
    const detail = container.querySelector(".ht-item-detail");
    expect(detail?.textContent).toContain("Next:");
    expect(detail?.textContent).toContain("in 3m");
    expect(detail?.textContent).toContain("±15s jitter");
  });
});
