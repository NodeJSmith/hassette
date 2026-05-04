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

  it("does not show back button on desktop layout", () => {
    const { queryByTestId } = renderHandlersTab();
    expect(queryByTestId("back-to-list")).toBeNull();
  });

  it("handler detail: shows method handler block when listener is selected", async () => {
    const listener = createListener({
      listener_id: 7,
      handler_method: "on_door_opened",
      source_location: "garage_alerts.py:42",
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-7"));
    await waitFor(() => {
      expect(getByTestId("listener-detail-7")).toBeDefined();
    });
    expect(getByTestId("handler-method-block")).toBeDefined();
    expect(getByTestId("handler-method-block").textContent).toContain("on_door_opened");
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

  it("handler detail: shows fires-when when predicate_description is set", async () => {
    const listener = createListener({
      listener_id: 12,
      predicate_description: "entity_id == 'light.kitchen'",
    });
    const { getByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-12"));
    await waitFor(() => {
      expect(getByTestId("handler-fires-when")).toBeDefined();
    });
  });

  it("handler detail: does not show fires-when when predicate_description is null", async () => {
    const listener = createListener({ listener_id: 13, predicate_description: null });
    const { getByTestId, queryByTestId } = renderHandlersTab([listener], []);
    fireEvent.click(getByTestId("unified-row-listener-13"));
    await waitFor(() => {
      expect(getByTestId("listener-detail-13")).toBeDefined();
    });
    expect(queryByTestId("handler-fires-when")).toBeNull();
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
