import { signal } from "@preact/signals";
import { fireEvent, waitFor } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJob, createListener } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { HandlersTab } from "./handlers-tab";

// Mock child components that make API calls
vi.mock("../shared/execution-table", () => ({
  ExecutionTable: ({ tableId, kind, records }: { tableId: string; kind: string; records: unknown[] }) => (
    <div data-testid={tableId} data-kind={kind} data-count={records.length}>
      {kind === "handler" ? "Invocations panel" : "Executions panel"}
    </div>
  ),
}));

const mockNavigate = vi.fn();
const mockCorrectUrl = vi.fn();

vi.mock("wouter", () => ({
  useLocation: () => ["/apps/test_app/handlers", mockNavigate],
}));

vi.mock("../../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

function renderHandlersTab(
  listeners = [createListener({ listener_id: 1 })],
  jobs = [createJob({ job_id: 10 })],
  selectedHandler: string | null = null,
) {
  return renderWithAppState(
    <HandlersTab listeners={listeners} jobs={jobs} selectedHandler={selectedHandler} appKey="test_app" instanceQs="" />,
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
      <HandlersTab listeners={[]} jobs={[]} selectedHandler={null} appKey="test_app" instanceQs="" />,
      { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
    );
    expect(getByTestId("handlers-empty")).toBeDefined();
  });

  it("shows detail pane placeholder when no item is selected", () => {
    const { getByTestId } = renderHandlersTab();
    expect(getByTestId("detail-placeholder")).toBeDefined();
  });

  it("shows listener detail pane when selectedHandler='h-5'", () => {
    const { getByTestId } = renderHandlersTab([createListener({ listener_id: 5 })], [], "h-5");
    expect(getByTestId("listener-detail-5")).toBeDefined();
  });

  it("shows job detail pane when selectedHandler='j-20'", () => {
    const { getByTestId } = renderHandlersTab([], [createJob({ job_id: 20 })], "j-20");
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
    const { getByTestId, getByText } = renderHandlersTab([listener], [], "h-3");
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
    const { getByTestId, getAllByText } = renderHandlersTab([], [job], "j-8");
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
    const { getByTestId, getAllByText } = renderHandlersTab([], [job], "j-9");
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
    const { getByTestId, getAllByText } = renderHandlersTab([], [job], "j-10");
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
    const { getByTestId } = renderHandlersTab([listener], [], "h-8");
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
    const { getByTestId } = renderHandlersTab([listener], [], "h-9");
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
    const { getByTestId } = renderHandlersTab([listener], [], "h-11");
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
    const { getByTestId } = renderHandlersTab([listener], [], "h-12");
    await waitFor(() => {
      expect(getByTestId("handler-registration-source")).toBeDefined();
    });
    expect(getByTestId("handler-registration-source").textContent).toContain("on_state_change");
  });

  it("handler detail: omits registration source when null", async () => {
    const listener = createListener({ listener_id: 13, registration_source: null });
    const { getByTestId, queryByTestId } = renderHandlersTab([listener], [], "h-13");
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
    const { getByTestId } = renderHandlersTab([listener], [], "h-20");
    await waitFor(() => {
      expect(getByTestId("handler-stats-row")).toBeDefined();
    });
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).toContain("Successful");
    expect(statsRow.textContent).toContain("8");
  });

  it("handler stats row: does not show cancelled when zero", async () => {
    const listener = createListener({ listener_id: 21, cancelled: 0 });
    const { getByTestId, queryByText } = renderHandlersTab([listener], [], "h-21");
    await waitFor(() => getByTestId("handler-stats-row"));
    expect(queryByText("Cancelled")).toBeNull();
  });

  it("handler stats row: shows cancelled count when > 0", async () => {
    const listener = createListener({ listener_id: 22, cancelled: 3 });
    const { getByTestId } = renderHandlersTab([listener], [], "h-22");
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
    const { getByTestId } = renderHandlersTab([listener], [], "h-23");
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    // Min and Max labels exist
    expect(statsRow.textContent).toContain("Min");
    expect(statsRow.textContent).toContain("Max");
    // Both show dash when null
    const cells = statsRow.querySelectorAll("[data-testid='handler-stats-row-cell']");
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
    const { getByTestId } = renderHandlersTab([listener], [], "h-24");
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
    const { getByTestId } = renderHandlersTab([], [job], "j-30");
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
    const { getByTestId } = renderHandlersTab([], [job], "j-31");
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
    const { getByTestId } = renderHandlersTab([], [job], "j-32");
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

  // URL-driven selection tests (T03)
  it("selects listener by selectedHandler='h-1' prop", () => {
    const listeners = [createListener({ listener_id: 1 })];
    const { getByTestId } = renderHandlersTab(listeners, [], "h-1");
    expect(getByTestId("listener-detail-1")).toBeDefined();
  });

  it("selects job by selectedHandler='j-10' prop", () => {
    const jobs = [createJob({ job_id: 10 })];
    const { getByTestId } = renderHandlersTab([], jobs, "j-10");
    expect(getByTestId("job-detail-10")).toBeDefined();
  });

  it("shows detail placeholder when selectedHandler is null", () => {
    const { getByTestId } = renderHandlersTab([createListener({ listener_id: 1 })], [], null);
    expect(getByTestId("detail-placeholder")).toBeDefined();
  });

  it("calls correctUrl when selectedHandler references a non-existent listener", () => {
    const listeners = [createListener({ listener_id: 1 })];
    renderHandlersTab(listeners, [], "h-999");
    expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers");
  });

  it("calls correctUrl when selectedHandler references a non-existent job", () => {
    const jobs = [createJob({ job_id: 1 })];
    renderHandlersTab([], jobs, "j-999");
    expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers");
  });

  it("does not call correctUrl when data is empty (loading guard)", () => {
    // Empty arrays = loading state / no data — should not correct URL
    renderHandlersTab([], [], "h-999");
    // The empty-state branch renders, no correctUrl call
    expect(mockCorrectUrl).not.toHaveBeenCalled();
  });

  it("clicking a listener row navigates to handler deep-link URL", () => {
    const listeners = [createListener({ listener_id: 5 })];
    const { getByTestId } = renderHandlersTab(listeners, [], null);
    fireEvent.click(getByTestId("unified-row-listener-5"));
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/h-5");
  });

  it("clicking a job row navigates to job deep-link URL", () => {
    const jobs = [createJob({ job_id: 20 })];
    const { getByTestId } = renderHandlersTab([], jobs, null);
    fireEvent.click(getByTestId("unified-row-job-20"));
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/j-20");
  });

  it("clicking a listener row includes instanceQs in deep-link URL", () => {
    const listeners = [createListener({ listener_id: 3 })];
    const { getByTestId } = renderWithAppState(
      <HandlersTab listeners={listeners} jobs={[]} selectedHandler={null} appKey="test_app" instanceQs="?instance=1" />,
      { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
    );
    fireEvent.click(getByTestId("unified-row-listener-3"));
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/h-3?instance=1");
  });

  it("job detail: renders schedule chips when jitter and group are set", async () => {
    const job = createJob({
      job_id: 40,
      jitter: 5,
      group: "my-group",
      trigger_type: "Every",
    });
    const { getByTestId } = renderHandlersTab([], [job], "j-40");
    await waitFor(() => getByTestId("job-detail-40"));
    const chips = getByTestId("schedule-chips");
    expect(chips.textContent).toContain("±5s jitter");
    expect(chips.textContent).toContain("group: my-group");
  });

  it("job detail: shows auto-generated name hint when name_auto is true", async () => {
    const job = createJob({ job_id: 41, name_auto: true });
    const { getByTestId } = renderHandlersTab([], [job], "j-41");
    await waitFor(() => getByTestId("job-detail-41"));
    const hint = getByTestId("job-detail-41").querySelector("[aria-label='Auto-generated name']");
    expect(hint).not.toBeNull();
  });

  it("job detail: shows next-run text when next_run is set", async () => {
    const job = createJob({
      job_id: 42,
      next_run: Date.now() / 1000 + 300,
    });
    const { getByTestId } = renderHandlersTab([], [job], "j-42");
    await waitFor(() => getByTestId("job-detail-42"));
    expect(getByTestId("job-next-run")).toBeDefined();
    expect(getByTestId("job-next-run").textContent).toContain("next");
  });

  it("job detail: shows fire-at text when fire_at is set but next_run is null", async () => {
    const job = createJob({
      job_id: 43,
      next_run: null,
      fire_at: Date.now() / 1000 + 60,
    });
    const { getByTestId } = renderHandlersTab([], [job], "j-43");
    await waitFor(() => getByTestId("job-detail-43"));
    expect(getByTestId("job-next-run")).toBeDefined();
    expect(getByTestId("job-next-run").textContent).toContain("fire at");
  });

  it("job detail: shows failing badge when job has errors", async () => {
    const job = createJob({
      job_id: 44,
      failed: 1,
      last_error_type: "RuntimeError",
      last_error_message: "boom",
    });
    const { getByTestId } = renderHandlersTab([], [job], "j-44");
    await waitFor(() => getByTestId("job-detail-44"));
    expect(getByTestId("handler-status-pill").textContent).toBe("failing");
  });

  it("shows placeholder when selectedHandler has invalid format", () => {
    const { queryByTestId, getByTestId } = renderHandlersTab(
      [createListener({ listener_id: 1 })],
      [],
      "invalid-format",
    );
    expect(queryByTestId("listener-detail-1")).toBeNull();
    expect(getByTestId("detail-placeholder")).toBeDefined();
  });

  it("handler detail: calls onSwitchToCode with line number when view-in-code clicked", async () => {
    const onSwitch = vi.fn();
    const listener = createListener({
      listener_id: 45,
      source_location: "my_app.py:99",
    });
    const { getByTestId } = renderWithAppState(
      <HandlersTab
        listeners={[listener]}
        jobs={[]}
        selectedHandler="h-45"
        appKey="test_app"
        instanceQs=""
        onSwitchToCode={onSwitch}
      />,
      { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
    );
    await waitFor(() => getByTestId("listener-detail-45"));
    fireEvent.click(getByTestId("view-in-code-btn"));
    expect(onSwitch).toHaveBeenCalledWith(99);
  });
});
