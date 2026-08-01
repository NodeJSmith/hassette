import { act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAppStore } from "../../state/store";
import { createJob } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { server } from "../../test/server";
import { renderHandlersTab } from "./handlers-tab.test-helpers";

vi.mock("sonner", async (importOriginal) => {
  const actual = await importOriginal<typeof import("sonner")>();
  return {
    ...actual,
    toast: { ...actual.toast, success: vi.fn(), error: vi.fn() },
  };
});

// Mock child components that make API calls
vi.mock("../shared/execution-table", () => ({
  ExecutionTable: ({ tableId, kind, records }: { tableId: string; kind: string; records: unknown[] }) => (
    <div data-testid={tableId} data-kind={kind} data-count={records.length}>
      {kind === "handler" ? "Invocations panel" : "Executions panel"}
    </div>
  ),
}));

vi.mock("./execution-detail", () => ({
  ExecutionDetailFetcher: (props: { executionId: string }) => (
    <div data-testid="execution-detail-fetcher">{props.executionId}</div>
  ),
}));

const mockNavigate = vi.fn();
const mockCorrectUrl = vi.fn();

vi.mock("wouter", () => createWouterMock({ useLocation: () => ["/apps/test_app/handlers", mockNavigate] }));

vi.mock("../../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

describe("HandlersTab job detail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows job detail pane when selectedHandler='job/20'", () => {
    const { getByTestId } = renderHandlersTab([], [createJob({ job_id: 20 })], "job/20");
    expect(getByTestId("job-detail-20")).toBeDefined();
  });

  it("renders schedule chips for job in detail pane", async () => {
    const job = createJob({
      job_id: 8,
      trigger_label: "every 30s",
      trigger_type: "Every",
    });
    const { getByTestId, getAllByText } = renderHandlersTab([], [job], "job/8");
    await waitFor(() => {
      expect(getByTestId("job-detail-8")).toBeDefined();
    });
    // "every 30s" appears in both the row description and the schedule chip
    expect(getAllByText("every 30s").length).toBeGreaterThanOrEqual(1);
  });

  it("job detail: shows combined trigger label and detail in subtitle", async () => {
    const job = createJob({
      job_id: 9,
      trigger_label: "every",
      trigger_detail: "300s",
      trigger_type: "interval",
    });
    const { getByTestId, getAllByText } = renderHandlersTab([], [job], "job/9");
    await waitFor(() => {
      expect(getByTestId("job-detail-9")).toBeDefined();
    });
    // Master row no longer renders a description line (see design/context.md two-line row layout);
    // "every 5m" now only appears in the detail pane's schedule chip.
    expect(getAllByText("every 5m").length).toBeGreaterThanOrEqual(1);
  });

  it("job detail: shows only detail when trigger_label is empty", async () => {
    const job = createJob({
      job_id: 10,
      trigger_label: "",
      trigger_detail: "300s",
      trigger_type: "interval",
    });
    const { getByTestId, getAllByText } = renderHandlersTab([], [job], "job/10");
    await waitFor(() => {
      expect(getByTestId("job-detail-10")).toBeDefined();
    });
    expect(getAllByText("5m").length).toBeGreaterThanOrEqual(1);
  });

  it("job detail: shows error banner when job has errors", async () => {
    const user = userEvent.setup();
    const job = createJob({
      job_id: 30,
      failed: 1,
      last_error_type: "RuntimeError",
      last_error_message: "something failed",
      last_error_traceback: "Traceback (most recent call last):\nRuntimeError: something failed",
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/30");
    await waitFor(() => getByTestId("job-detail-30"));
    const banner = getByTestId("job-error-banner");
    expect(banner.textContent).toContain("RuntimeError");
    expect(banner.textContent).toContain("something failed");
    // Toggle and check traceback
    const toggle = banner.querySelector("[data-testid='traceback-toggle']");
    expect(toggle).not.toBeNull();
    await user.click(toggle!);
    expect(banner.textContent).toContain("Traceback (most recent call last)");
  });

  it("job stats row: renders err rate cell", async () => {
    const job = createJob({
      job_id: 31,
      total_executions: 10,
      successful: 7,
      failed: 2,
      timed_out: 1,
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/31");
    await waitFor(() => getByTestId("job-stats-row"));
    const statsRow = getByTestId("job-stats-row");
    expect(statsRow.textContent).toContain("Err %");
    expect(statsRow.textContent).toContain("20%");
  });

  it("job stats row: visually separates failed and timed_out as distinct cells", async () => {
    const job = createJob({
      job_id: 32,
      failed: 2,
      timed_out: 1,
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/32");
    await waitFor(() => getByTestId("job-stats-row"));
    const statsRow = getByTestId("job-stats-row");
    // Both labels must be present as distinct cells
    expect(statsRow.textContent).toContain("Failed");
    expect(statsRow.textContent).toContain("Timed Out");
    // Failed uses err color class, Timed Out uses warn color class
    const errValue = statsRow.querySelector("[data-tone='err']");
    const warnValue = statsRow.querySelector("[data-tone='warn']");
    expect(errValue).not.toBeNull();
    expect(warnValue).not.toBeNull();
    expect(errValue?.textContent).toBe("2");
    expect(warnValue?.textContent).toBe("1");
  });

  it("job detail: renders schedule chips when jitter and group are set", async () => {
    const job = createJob({
      job_id: 40,
      jitter: 5,
      group: "my-group",
      trigger_type: "Every",
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/40");
    await waitFor(() => getByTestId("job-detail-40"));
    const chips = getByTestId("schedule-chips");
    expect(chips.textContent).toContain("±5s jitter");
    expect(chips.textContent).toContain("group: my-group");
  });

  it("job detail: shows next-run text in stats when next_run is set", async () => {
    const job = createJob({
      job_id: 42,
      next_run: Date.now() / 1000 + 300,
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/42");
    await waitFor(() => getByTestId("job-detail-42"));
    const statsRow = getByTestId("job-stats-row");
    expect(statsRow.textContent).toContain("Next");
    expect(statsRow.textContent).toContain("next");
  });

  it("job detail: shows fire-at text in stats when fire_at is set but next_run is null", async () => {
    const job = createJob({
      job_id: 43,
      next_run: null,
      fire_at: Date.now() / 1000 + 60,
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/43");
    await waitFor(() => getByTestId("job-detail-43"));
    const statsRow = getByTestId("job-stats-row");
    expect(statsRow.textContent).toContain("Next");
    expect(statsRow.textContent).toContain("fire at");
  });

  it("job detail: shows failing badge when job has errors", async () => {
    const job = createJob({
      job_id: 44,
      failed: 1,
      last_error_type: "RuntimeError",
      last_error_message: "boom",
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/44");
    await waitFor(() => getByTestId("job-detail-44"));
    expect(getByTestId("handler-status-pill").textContent).toBe("failing");
  });

  it("job detail: shows mode chip for every job", async () => {
    const job = createJob({ job_id: 50, mode: "queued" });
    const { getByTestId } = renderHandlersTab([], [job], "job/50");
    await waitFor(() => getByTestId("job-detail-50"));
    const modeChip = getByTestId("handler-mode-chip");
    expect(modeChip.textContent).toBe("mode: queued");
    expect(modeChip.getAttribute("data-variant")).toBe("muted");
  });

  it("job stats row: does not show Suppressed or Dropped when counts are zero", async () => {
    const job = createJob({ job_id: 51, suppressed_count: 0, dropped_count: 0 });
    const { getByTestId, queryByText } = renderHandlersTab([], [job], "job/51");
    await waitFor(() => getByTestId("job-stats-row"));
    expect(queryByText("Suppressed")).toBeNull();
    expect(queryByText("Dropped")).toBeNull();
  });

  it("job stats row: shows Suppressed when suppressed_count > 0", async () => {
    const job = createJob({ job_id: 52, mode: "single", suppressed_count: 3, dropped_count: 0 });
    const { getByTestId, queryByText } = renderHandlersTab([], [job], "job/52");
    await waitFor(() => getByTestId("job-stats-row"));
    const statsRow = getByTestId("job-stats-row");
    expect(statsRow.textContent).toContain("Suppressed");
    expect(statsRow.textContent).toContain("3");
    expect(queryByText("Dropped")).toBeNull();
    // Suppressed is expected single-mode behavior: muted, not a warning
    const muteValue = statsRow.querySelector("[data-tone='mute']");
    expect(muteValue?.textContent).toBe("3");
  });

  it("job stats row: shows Dropped when dropped_count > 0", async () => {
    const job = createJob({ job_id: 53, mode: "queued", suppressed_count: 0, dropped_count: 2 });
    const { getByTestId, queryByText } = renderHandlersTab([], [job], "job/53");
    await waitFor(() => getByTestId("job-stats-row"));
    const statsRow = getByTestId("job-stats-row");
    expect(statsRow.textContent).toContain("Dropped");
    expect(statsRow.textContent).toContain("2");
    expect(queryByText("Suppressed")).toBeNull();
    // Dropped is data loss: warns
    const warnValue = statsRow.querySelector("[data-tone='warn']");
    expect(warnValue?.textContent).toBe("2");
  });

  it("job stats row: shows Skipped when skipped > 0", async () => {
    const job = createJob({ job_id: 54, skipped: 4 });
    const { getByTestId } = renderHandlersTab([], [job], "job/54");
    await waitFor(() => getByTestId("job-stats-row"));
    const statsRow = getByTestId("job-stats-row");
    expect(statsRow.textContent).toContain("Skipped");
    expect(statsRow.textContent).toContain("4");
    const muteValue = statsRow.querySelector("[data-tone='mute']");
    expect(muteValue?.textContent).toBe("4");
  });

  it("job stats row: does not show Skipped when count is zero", async () => {
    const job = createJob({ job_id: 55, skipped: 0 });
    const { getByTestId, queryByText } = renderHandlersTab([], [job], "job/55");
    await waitFor(() => getByTestId("job-stats-row"));
    expect(queryByText("Skipped")).toBeNull();
  });

  it("job detail: shows human_description as predicate description when present", async () => {
    const job = createJob({
      job_id: 56,
      predicate_description: "<lambda>",
      human_description: "binary_sensor.home_occupied is on",
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/56");
    await waitFor(() => getByTestId("job-detail-56"));
    expect(getByTestId("job-predicate-description").textContent).toBe("binary_sensor.home_occupied is on");
  });

  it("job detail: falls back to predicate_description when human_description is null", async () => {
    const job = createJob({
      job_id: 57,
      predicate_description: "<lambda>",
      human_description: null,
    });
    const { getByTestId } = renderHandlersTab([], [job], "job/57");
    await waitFor(() => getByTestId("job-detail-57"));
    expect(getByTestId("job-predicate-description").textContent).toBe("<lambda>");
  });

  it("job detail: does not show predicate description when both fields are null", async () => {
    const job = createJob({ job_id: 58, predicate_description: null, human_description: null });
    const { getByTestId, queryByTestId } = renderHandlersTab([], [job], "job/58");
    await waitFor(() => getByTestId("job-detail-58"));
    expect(queryByTestId("job-predicate-description")).toBeNull();
  });

  describe("job detail: Run Now button", () => {
    it("renders in the job detail panel", async () => {
      const job = createJob({ job_id: 60 });
      const { getByTestId } = renderHandlersTab([], [job], "job/60");
      await waitFor(() => getByTestId("job-detail-60"));
      expect(getByTestId("run-now-btn")).toBeDefined();
      expect(getByTestId("run-now-btn").textContent).toContain("Run Now");
    });

    it("enters loading state and disables on click", async () => {
      const user = userEvent.setup();
      const job = createJob({ job_id: 61 });
      server.use(
        http.post(
          "/api/scheduler/jobs/:id/trigger",
          () => new Promise(() => {}), // never resolves — keeps the button in loading state
        ),
      );
      const { getByTestId } = renderHandlersTab([], [job], "job/61");
      await waitFor(() => getByTestId("job-detail-61"));
      const button = getByTestId("run-now-btn") as HTMLButtonElement;
      await user.click(button);
      await waitFor(() => {
        expect(button.disabled).toBe(true);
      });
    });

    it("shows inline error on 409 response", async () => {
      const user = userEvent.setup();
      const job = createJob({ job_id: 62 });
      server.use(
        http.post("/api/scheduler/jobs/:id/trigger", () => {
          return HttpResponse.json({ detail: "job is currently executing" }, { status: 409 });
        }),
      );
      const { getByTestId } = renderHandlersTab([], [job], "job/62");
      await waitFor(() => getByTestId("job-detail-62"));
      await user.click(getByTestId("run-now-btn"));
      await waitFor(() => {
        expect(getByTestId("run-now-error").textContent).toContain("job is currently executing");
      });
    });

    it("re-enables after the request completes", async () => {
      const user = userEvent.setup();
      const job = createJob({ job_id: 63 });
      const { getByTestId } = renderHandlersTab([], [job], "job/63");
      await waitFor(() => getByTestId("job-detail-63"));
      const button = getByTestId("run-now-btn") as HTMLButtonElement;
      await user.click(button);
      await waitFor(() => {
        expect(button.disabled).toBe(false);
      });
    });

    it("shows a success toast when a matching execution record appears after submission", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const user = userEvent.setup();
      const job = createJob({ job_id: 70 });
      const { getByTestId } = renderHandlersTab([], [job], "job/70");
      await waitFor(() => getByTestId("job-detail-70"));

      await user.click(getByTestId("run-now-btn"));
      await waitFor(() => expect(toast.success).not.toHaveBeenCalled());

      act(() => {
        useAppStore.setState({
          executionCompleted: [
            {
              kind: "job",
              job_id: 70,
              app_key: "test_app",
              instance_index: 0,
              status: "success",
              duration_ms: 10,
              error_type: null,
              thread_leaked: false,
            },
          ],
        });
      });

      await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Execution recorded"));
      expect(toast.error).not.toHaveBeenCalled();
      vi.useRealTimers();
    });

    it("shows a 'No execution recorded' toast when no matching record appears within the timeout", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const user = userEvent.setup();
      const job = createJob({ job_id: 71 });
      const { getByTestId } = renderHandlersTab([], [job], "job/71");
      await waitFor(() => getByTestId("job-detail-71"));

      await user.click(getByTestId("run-now-btn"));

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });

      expect(toast.error).toHaveBeenCalledWith("No execution recorded");
      expect(toast.success).not.toHaveBeenCalled();
      vi.useRealTimers();
    });

    it("ignores executionCompleted records for a different job_id", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const user = userEvent.setup();
      const job = createJob({ job_id: 72 });
      const { getByTestId } = renderHandlersTab([], [job], "job/72");
      await waitFor(() => getByTestId("job-detail-72"));

      await user.click(getByTestId("run-now-btn"));

      act(() => {
        useAppStore.setState({
          executionCompleted: [
            {
              kind: "job",
              job_id: 999,
              app_key: "test_app",
              instance_index: 0,
              status: "success",
              duration_ms: 10,
              error_type: null,
              thread_leaked: false,
            },
          ],
        });
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });

      expect(toast.success).not.toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalledWith("No execution recorded");
      vi.useRealTimers();
    });
  });

  describe("job detail: schedule status text", () => {
    it("shows 'Manual only.' for a manual job", async () => {
      const job = createJob({ job_id: 80, schedule_status: "manual", next_run: null, fire_at: null });
      const { getByTestId } = renderHandlersTab([], [job], "job/80");
      await waitFor(() => getByTestId("job-stats-row"));
      expect(getByTestId("job-stats-row").textContent).toContain("Manual only.");
    });

    it("shows 'Waiting for entity time.' for a waiting job", async () => {
      const job = createJob({ job_id: 81, schedule_status: "waiting", next_run: null, fire_at: null });
      const { getByTestId } = renderHandlersTab([], [job], "job/81");
      await waitFor(() => getByTestId("job-stats-row"));
      expect(getByTestId("job-stats-row").textContent).toContain("Waiting for entity time.");
    });

    it("shows 'Schedule completed.' for a completed job with no reason", async () => {
      const job = createJob({
        job_id: 82,
        schedule_status: "completed",
        schedule_status_reason: null,
        next_run: null,
        fire_at: null,
      });
      const { getByTestId } = renderHandlersTab([], [job], "job/82");
      await waitFor(() => getByTestId("job-stats-row"));
      expect(getByTestId("job-stats-row").textContent).toContain("Schedule completed.");
    });

    it("shows 'Schedule stopped after trigger error.' for a completed job with trigger_error reason", async () => {
      const job = createJob({
        job_id: 83,
        schedule_status: "completed",
        schedule_status_reason: "trigger_error",
        next_run: null,
        fire_at: null,
      });
      const { getByTestId } = renderHandlersTab([], [job], "job/83");
      await waitFor(() => getByTestId("job-stats-row"));
      expect(getByTestId("job-stats-row").textContent).toContain("Schedule stopped after trigger error.");
    });

    it("shows 'Legacy status unknown.' for a scheduled job with legacy_unknown reason", async () => {
      const job = createJob({
        job_id: 84,
        schedule_status: "scheduled",
        schedule_status_reason: "legacy_unknown",
        next_run: null,
        fire_at: null,
      });
      const { getByTestId } = renderHandlersTab([], [job], "job/84");
      await waitFor(() => getByTestId("job-stats-row"));
      expect(getByTestId("job-stats-row").textContent).toContain("Legacy status unknown.");
    });

    it("shows 'Timing unavailable.' for a scheduled job with null timing and no reason", async () => {
      const job = createJob({
        job_id: 85,
        schedule_status: "scheduled",
        schedule_status_reason: null,
        next_run: null,
        fire_at: null,
      });
      const { getByTestId } = renderHandlersTab([], [job], "job/85");
      await waitFor(() => getByTestId("job-stats-row"));
      expect(getByTestId("job-stats-row").textContent).toContain("Timing unavailable.");
    });

    it("shows the next relative time (not status text) for a normally scheduled job", async () => {
      const job = createJob({
        job_id: 86,
        schedule_status: "scheduled",
        schedule_status_reason: null,
        next_run: Date.now() / 1000 + 300,
      });
      const { getByTestId } = renderHandlersTab([], [job], "job/86");
      await waitFor(() => getByTestId("job-stats-row"));
      const statsRow = getByTestId("job-stats-row");
      expect(statsRow.textContent).toContain("next");
      expect(statsRow.textContent).not.toContain("Timing unavailable.");
    });

    it.each(["manual", "waiting", "completed"] as const)("Run Now stays available for status '%s'", async (status) => {
      const job = createJob({ job_id: 90, schedule_status: status, next_run: null, fire_at: null });
      const { getByTestId } = renderHandlersTab([], [job], "job/90");
      await waitFor(() => getByTestId("job-detail-90"));
      const button = getByTestId("run-now-btn") as HTMLButtonElement;
      expect(button.disabled).toBe(false);
    });
  });
});
