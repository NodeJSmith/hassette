import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, waitFor } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { renderWithAppState } from "../../test/render-helpers";
import { HandlersTab } from "./handlers-tab";
import { createListener, createJob } from "../../test/factories";

// Mock child components that make API calls
vi.mock("./handler-invocations", () => ({
  HandlerInvocations: ({ listenerId }: { invocations: unknown[]; listenerId: number }) => (
    <div data-testid={`invocations-${listenerId}`}>Invocations panel</div>
  ),
}));
vi.mock("./job-executions", () => ({
  JobExecutions: ({ jobId }: { executions: unknown[]; jobId: number }) => (
    <div data-testid={`executions-${jobId}`}>Executions panel</div>
  ),
}));

function renderHandlersTab(
  listeners = [createListener({ listener_id: 1 })],
  jobs = [createJob({ job_id: 10 })],
) {
  return renderWithAppState(
    <HandlersTab
      listeners={listeners}
      jobs={jobs}
      focusMethod={null}
    />,
    { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
  );
}

describe("HandlersTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the master list container", () => {
    const { getByTestId } = renderHandlersTab();
    expect(getByTestId("handler-list")).toBeDefined();
  });

  it("renders empty state when no listeners or jobs", () => {
    const { getByTestId } = renderWithAppState(
      <HandlersTab listeners={[]} jobs={[]} focusMethod={null} />,
      { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
    );
    expect(getByTestId("handlers-empty")).toBeDefined();
  });

  it("shows detail pane placeholder when no item is selected", () => {
    const { getByTestId } = renderHandlersTab();
    expect(getByTestId("detail-placeholder")).toBeDefined();
  });

  it("shows listener detail pane after selecting a listener", () => {
    const { getByTestId } = renderHandlersTab(
      [createListener({ listener_id: 5 })],
      [],
    );
    const row = getByTestId("unified-row-listener-5");
    fireEvent.click(row);
    // Detail pane for handler (invocations)
    expect(getByTestId("listener-detail-5")).toBeDefined();
  });

  it("shows job detail pane after selecting a job", () => {
    const { getByTestId } = renderHandlersTab(
      [],
      [createJob({ job_id: 20 })],
    );
    const row = getByTestId("unified-row-job-20");
    fireEvent.click(row);
    expect(getByTestId("job-detail-20")).toBeDefined();
  });

  it("renders modifier chips for listener in detail pane", async () => {
    const listener = createListener({
      listener_id: 3,
      debounce: 0.5,
      throttle: null,
      once: 0,
      immediate: 0,
    });
    const { getByTestId, getByText } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-3"));
    await waitFor(() => {
      expect(getByTestId("listener-detail-3")).toBeDefined();
    });
    expect(getByText(/debounce/i)).toBeDefined();
  });

  it("renders schedule chips for job in detail pane", async () => {
    const job = createJob({
      job_id: 8,
      trigger_label: "every 30s",
      trigger_type: "Every",
    });
    const { getByTestId, getAllByText } = renderHandlersTab([], [job]);
    fireEvent.click(getByTestId("unified-row-job-8"));
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
    const { getByTestId, getAllByText } = renderHandlersTab([], [job]);
    fireEvent.click(getByTestId("unified-row-job-9"));
    await waitFor(() => {
      expect(getByTestId("job-detail-9")).toBeDefined();
    });
    expect(getAllByText("every 5m").length).toBeGreaterThanOrEqual(2);
  });

  it("job detail: shows only detail when trigger_label is empty", async () => {
    const job = createJob({
      job_id: 10,
      trigger_label: "",
      trigger_detail: "300s",
      trigger_type: "interval",
    });
    const { getByTestId, getAllByText } = renderHandlersTab([], [job]);
    fireEvent.click(getByTestId("unified-row-job-10"));
    await waitFor(() => {
      expect(getByTestId("job-detail-10")).toBeDefined();
    });
    expect(getAllByText("5m").length).toBeGreaterThanOrEqual(1);
  });

  it("does not show back button on desktop layout", () => {
    const { queryByTestId } = renderHandlersTab();
    expect(queryByTestId("back-to-list")).toBeNull();
  });

  it("handler detail: shows source location when available", async () => {
    const listener = createListener({
      listener_id: 8,
      source_location: "garage_alerts.py:42",
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-8"));
    await waitFor(() => {
      expect(getByTestId("handler-source-location")).toBeDefined();
    });
    expect(getByTestId("handler-source-location").textContent).toContain("garage_alerts.py");
    expect(getByTestId("handler-source-location").textContent).toContain("42");
  });

  it("handler detail: stats row renders with counts", async () => {
    const listener = createListener({
      listener_id: 9,
      total_invocations: 15,
      failed: 2,
      timed_out: 1,
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-9"));
    await waitFor(() => {
      expect(getByTestId("handler-stats-row")).toBeDefined();
    });
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).toContain("15");
    expect(statsRow.textContent).toContain("2");
    expect(statsRow.textContent).toContain("1");
  });

  it("handler detail: shows error banner when listener has errors", async () => {
    const listener = createListener({
      listener_id: 11,
      failed: 1,
      last_error_type: "KeyError",
      last_error_message: "missing key 'state'",
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-11"));
    await waitFor(() => {
      expect(getByTestId("handler-error-banner")).toBeDefined();
    });
    expect(getByTestId("handler-error-banner").textContent).toContain("KeyError");
  });

  it("handler detail: shows registration source when available", async () => {
    const listener = createListener({
      listener_id: 12,
      registration_source: "self.bus.on_state_change('light.kitchen', handler=self.on_light)",
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-12"));
    await waitFor(() => {
      expect(getByTestId("handler-registration-source")).toBeDefined();
    });
    expect(getByTestId("handler-registration-source").textContent).toContain("on_state_change");
  });

  it("handler detail: omits registration source when null", async () => {
    const listener = createListener({ listener_id: 13, registration_source: null });
    const { getByTestId, queryByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-13"));
    await waitFor(() => {
      expect(getByTestId("listener-detail-13")).toBeDefined();
    });
    expect(queryByTestId("handler-registration-source")).toBeNull();
  });

  it("handler stats row: renders successful count", async () => {
    const listener = createListener({
      listener_id: 20,
      total_invocations: 10,
      successful: 8,
      failed: 2,
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-20"));
    await waitFor(() => {
      expect(getByTestId("handler-stats-row")).toBeDefined();
    });
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).toContain("Successful");
    expect(statsRow.textContent).toContain("8");
  });

  it("handler stats row: does not show cancelled when zero", async () => {
    const listener = createListener({ listener_id: 21, cancelled: 0 });
    const { getByTestId, queryByText } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-21"));
    await waitFor(() => getByTestId("handler-stats-row"));
    expect(queryByText("Cancelled")).toBeNull();
  });

  it("handler stats row: shows cancelled count when > 0", async () => {
    const listener = createListener({ listener_id: 22, cancelled: 3 });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-22"));
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).toContain("Cancelled");
    expect(statsRow.textContent).toContain("3");
  });

  it("handler stats row: shows — for min/max when null (no executions)", async () => {
    const listener = createListener({
      listener_id: 23,
      min_duration_ms: null,
      max_duration_ms: null,
      avg_duration_ms: 0,
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-23"));
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    // Min and Max labels exist
    expect(statsRow.textContent).toContain("Min");
    expect(statsRow.textContent).toContain("Max");
    // Both show dash when null
    const cells = statsRow.querySelectorAll(".ht-detail-stats-row__cell");
    const minCell = Array.from(cells).find((c) => c.textContent?.includes("Min"));
    const maxCell = Array.from(cells).find((c) => c.textContent?.includes("Max"));
    expect(minCell?.textContent).toContain("—");
    expect(maxCell?.textContent).toContain("—");
  });

  it("handler error banner: shows expandable traceback when available", async () => {
    const listener = createListener({
      listener_id: 24,
      failed: 1,
      last_error_type: "ValueError",
      last_error_message: "bad value",
      last_error_traceback: "Traceback (most recent call last):\n  File test.py line 1\nValueError: bad value",
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-24"));
    await waitFor(() => getByTestId("handler-error-banner"));
    const banner = getByTestId("handler-error-banner");
    // Traceback toggle button should be present
    const toggle = banner.querySelector("[data-testid='traceback-toggle']");
    expect(toggle).not.toBeNull();
    // Traceback is initially collapsed
    const tracebackContent = banner.querySelector("[data-testid='traceback-content']");
    expect(tracebackContent).not.toBeNull();
    // Expand it
    fireEvent.click(toggle!);
    expect(banner.textContent).toContain("Traceback (most recent call last)");
  });

  it("job detail: shows error banner when job has errors", async () => {
    const job = createJob({
      job_id: 30,
      failed: 1,
      last_error_type: "RuntimeError",
      last_error_message: "something failed",
      last_error_traceback: "Traceback (most recent call last):\nRuntimeError: something failed",
    });
    const { getByTestId } = renderHandlersTab([], [job]);
    fireEvent.click(getByTestId("unified-row-job-30"));
    await waitFor(() => getByTestId("job-detail-30"));
    const banner = getByTestId("job-error-banner");
    expect(banner.textContent).toContain("RuntimeError");
    expect(banner.textContent).toContain("something failed");
    // Toggle and check traceback
    const toggle = banner.querySelector("[data-testid='traceback-toggle']");
    expect(toggle).not.toBeNull();
    fireEvent.click(toggle!);
    expect(banner.textContent).toContain("Traceback (most recent call last)");
  });

  it("job stats row: renders successful count", async () => {
    const job = createJob({
      job_id: 31,
      total_executions: 10,
      successful: 7,
      failed: 2,
      timed_out: 1,
    });
    const { getByTestId } = renderHandlersTab([], [job]);
    fireEvent.click(getByTestId("unified-row-job-31"));
    await waitFor(() => getByTestId("job-stats-row"));
    const statsRow = getByTestId("job-stats-row");
    expect(statsRow.textContent).toContain("Successful");
    expect(statsRow.textContent).toContain("7");
  });

  it("job stats row: visually separates failed and timed_out as distinct cells", async () => {
    const job = createJob({
      job_id: 32,
      failed: 2,
      timed_out: 1,
    });
    const { getByTestId } = renderHandlersTab([], [job]);
    fireEvent.click(getByTestId("unified-row-job-32"));
    await waitFor(() => getByTestId("job-stats-row"));
    const statsRow = getByTestId("job-stats-row");
    // Both labels must be present as distinct cells
    expect(statsRow.textContent).toContain("Failed");
    expect(statsRow.textContent).toContain("Timed Out");
    // Failed uses err color class, Timed Out uses warn color class
    const errValue = statsRow.querySelector(".ht-detail-stats-row__value--err");
    const warnValue = statsRow.querySelector(".ht-detail-stats-row__value--warn");
    expect(errValue).not.toBeNull();
    expect(warnValue).not.toBeNull();
    expect(errValue?.textContent).toBe("2");
    expect(warnValue?.textContent).toBe("1");
  });

  it("selects first item automatically when focusMethod matches a handler", () => {
    const listeners = [
      createListener({ listener_id: 1, handler_method: "app.on_motion" }),
    ];
    const { getByTestId } = renderWithAppState(
      <HandlersTab
        listeners={listeners}
        jobs={[]}
        focusMethod="app.on_motion"
      />,
      { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
    );
    expect(getByTestId("listener-detail-1")).toBeDefined();
  });
});
