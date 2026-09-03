import { waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createListener } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { renderHandlersTab } from "./handlers-tab.test-helpers";

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

describe("HandlersTab listener detail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("handler detail: shows listener detail pane when selectedHandler='listener/5'", () => {
    const { getByTestId } = renderHandlersTab([createListener({ listener_id: 5 })], [], "listener/5");
    expect(getByTestId("listener-detail-5")).toBeDefined();
  });

  it("handler detail: uses a semantic heading for the selected handler name", () => {
    const listener = createListener({ listener_id: 6, handler_method: "on_garage_opened" });
    const { getByRole } = renderHandlersTab([listener], [], "listener/6");
    expect(getByRole("heading", { level: 2, name: "on_garage_opened" })).toBeDefined();
  });

  it("handler detail: renders modifier chips for listener in detail pane", async () => {
    const listener = createListener({
      listener_id: 3,
      debounce: 0.5,
      throttle: null,
      once: 0,
      immediate: 0,
    });
    const { getByTestId, getByText } = renderHandlersTab([listener], [], "listener/3");
    await waitFor(() => {
      expect(getByTestId("listener-detail-3")).toBeDefined();
    });
    expect(getByText(/debounce/i)).toBeDefined();
  });

  it("handler detail: shows source location when available", async () => {
    const listener = createListener({
      listener_id: 8,
      source_location: "garage_alerts.py:42",
    });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/8");
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
    const { getByTestId } = renderHandlersTab([listener], [], "listener/9");
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
    const { getByTestId } = renderHandlersTab([listener], [], "listener/11");
    await waitFor(() => {
      expect(getByTestId("handler-error-banner")).toBeDefined();
    });
    expect(getByTestId("handler-error-banner").textContent).toContain("KeyError");
  });

  it("handler detail: shows registration source when available", async () => {
    const user = userEvent.setup();
    const listener = createListener({
      listener_id: 12,
      registration_source: "self.bus.on_state_change('light.kitchen', handler=self.on_light)",
    });
    const { getByRole, getByTestId, queryByTestId } = renderHandlersTab([listener], [], "listener/12");
    await waitFor(() => {
      expect(getByTestId("handler-registration-toggle")).toBeDefined();
    });
    expect(getByRole("region", { name: "Registration" })).toBeDefined();
    const toggle = getByTestId("handler-registration-toggle");
    expect(toggle.getAttribute("aria-controls")).toBe("listener-detail-12-registration-source-panel");
    expect(toggle.textContent).toContain("show call");
    expect(queryByTestId("handler-registration-source")).toBeNull();
    await user.click(toggle);
    const registrationSource = getByTestId("handler-registration-source");
    expect(registrationSource.id).toBe(toggle.getAttribute("aria-controls"));
    expect(registrationSource.textContent).toContain("on_state_change");
  });

  it("handler detail: omits registration source when null", async () => {
    const listener = createListener({ listener_id: 13, registration_source: null });
    const { getByTestId, queryByTestId } = renderHandlersTab([listener], [], "listener/13");
    await waitFor(() => {
      expect(getByTestId("listener-detail-13")).toBeDefined();
    });
    expect(queryByTestId("handler-registration-source")).toBeNull();
  });

  it("handler stats row: renders err rate cell", async () => {
    const listener = createListener({
      listener_id: 20,
      total_invocations: 10,
      successful: 8,
      failed: 2,
    });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/20");
    await waitFor(() => {
      expect(getByTestId("handler-stats-row")).toBeDefined();
    });
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).toContain("Err %");
    expect(statsRow.textContent).toContain("20%");
  });

  it("handler stats row: does not show cancelled when zero", async () => {
    const listener = createListener({ listener_id: 21, cancelled: 0 });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/21");
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).not.toContain("Cancelled");
  });

  it("handler stats row: shows cancelled count when > 0", async () => {
    const listener = createListener({ listener_id: 22, cancelled: 3 });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/22");
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).toContain("Cancelled");
    expect(statsRow.textContent).toContain("3");
  });

  it("handler stats row: shows Backpressure Dropped with warn tone when count > 0", async () => {
    const listener = createListener({
      listener_id: 24,
      backpressure: "drop_newest",
      backpressure_dropped_count: 5,
      total_invocations: 5,
      failed: 0,
      timed_out: 0,
    });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/24");
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    expect(statsRow.textContent).toContain("Backpressure Dropped");
    // Dropped events are data loss: warns, with drop-rate percentage
    const warnValue = statsRow.querySelector("[data-tone='warn']");
    expect(warnValue?.textContent).toBe("5 (50%)");
  });

  it("handler stats row: shows 100% rate when every event was dropped", async () => {
    const listener = createListener({
      listener_id: 25,
      backpressure: "drop_newest",
      backpressure_dropped_count: 5,
      total_invocations: 0,
      failed: 0,
      timed_out: 0,
    });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/25");
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    const warnValue = statsRow.querySelector("[data-tone='warn']");
    expect(warnValue?.textContent).toBe("5 (100%)");
  });

  it("handler stats row: shows — for avg when there are no executions", async () => {
    const listener = createListener({
      listener_id: 23,
      min_duration_ms: null,
      max_duration_ms: null,
      avg_duration_ms: 0,
    });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/23");
    await waitFor(() => getByTestId("handler-stats-row"));
    const statsRow = getByTestId("handler-stats-row");
    const cells = statsRow.querySelectorAll("[data-testid='handler-stats-row-cell']");
    const avgCell = Array.from(cells).find((c) => c.textContent?.includes("Avg"));
    expect(avgCell?.textContent).toContain("—");
  });

  it("handler error banner: shows expandable traceback when available", async () => {
    const user = userEvent.setup();
    const listener = createListener({
      listener_id: 26,
      failed: 1,
      last_error_type: "ValueError",
      last_error_message: "bad value",
      last_error_traceback: "Traceback (most recent call last):\n  File test.py line 1\nValueError: bad value",
    });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/26");
    await waitFor(() => getByTestId("handler-error-banner"));
    const banner = getByTestId("handler-error-banner");
    expect(within(banner).getByTestId("traceback-content")).toBeDefined();
    const toggle = within(banner).getByTestId("traceback-toggle");
    expect(banner.textContent).not.toContain("Traceback (most recent call last)");
    await user.click(toggle);
    expect(banner.textContent).toContain("Traceback (most recent call last)");
  });

  it("handler detail: shows mode chip", async () => {
    const listener = createListener({ listener_id: 70, mode: "queued" });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/70");
    await waitFor(() => getByTestId("listener-detail-70"));
    const modeChip = getByTestId("handler-mode-chip");
    expect(modeChip.textContent).toBe("mode: queued");
    expect(modeChip.getAttribute("data-variant")).toBe("muted");
  });

  it("handler detail: registration source stays hidden until the toggle is clicked", async () => {
    const user = userEvent.setup();
    const listener = createListener({
      listener_id: 71,
      registration_source: "self.bus.on_state_change('light.kitchen', handler=self.on_light)",
    });
    const { getByTestId, queryByTestId } = renderHandlersTab([listener], [], "listener/71");
    await waitFor(() => getByTestId("listener-detail-71"));
    expect(queryByTestId("handler-registration-source")).toBeNull();
    const toggle = getByTestId("handler-registration-toggle");
    expect(toggle.textContent).toContain("show call");
    await user.click(toggle);
    expect(getByTestId("handler-registration-source")).toBeDefined();
    expect(toggle.textContent).toContain("hide call");
  });

  it("handler detail: renders the executions table inside the detail card", async () => {
    const listener = createListener({ listener_id: 72 });
    const { getByTestId } = renderHandlersTab([listener], [], "listener/72");
    await waitFor(() => getByTestId("listener-detail-72"));
    const table = await waitFor(() => getByTestId("invocation-table-72"));
    const detailCard = getByTestId("listener-detail-72");
    expect(detailCard.contains(table)).toBe(true);
  });
});
