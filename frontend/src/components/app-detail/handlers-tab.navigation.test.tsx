import { fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJob, createListener } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { renderWithAppState } from "../../test/render-helpers";
import { HandlersTab } from "./handlers-tab";
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

describe("HandlersTab navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // URL-driven selection tests (T03)
  it("selects listener by selectedHandler='listener/1' prop", () => {
    const listeners = [createListener({ listener_id: 1 })];
    const { getByTestId } = renderHandlersTab(listeners, [], "listener/1");
    expect(getByTestId("listener-detail-1")).toBeDefined();
  });

  it("selects job by selectedHandler='job/10' prop", () => {
    const jobs = [createJob({ job_id: 10 })];
    const { getByTestId } = renderHandlersTab([], jobs, "job/10");
    expect(getByTestId("job-detail-10")).toBeDefined();
  });

  it("shows detail placeholder when selectedHandler is null", () => {
    const { getByTestId } = renderHandlersTab([createListener({ listener_id: 1 })], [], null);
    expect(getByTestId("detail-placeholder")).toBeDefined();
  });

  it("calls correctUrl when selectedHandler references a non-existent listener", () => {
    const listeners = [createListener({ listener_id: 1 })];
    renderHandlersTab(listeners, [], "listener/999");
    expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers");
  });

  it("calls correctUrl when selectedHandler references a non-existent job", () => {
    const jobs = [createJob({ job_id: 1 })];
    renderHandlersTab([], jobs, "job/999");
    expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers");
  });

  it("does not call correctUrl when data is empty (loading guard)", () => {
    // Empty arrays = loading state / no data — should not correct URL
    renderHandlersTab([], [], "listener/999");
    // The empty-state branch renders, no correctUrl call
    expect(mockCorrectUrl).not.toHaveBeenCalled();
  });

  it("clicking a listener row navigates to handler deep-link URL", () => {
    const listeners = [createListener({ listener_id: 5 })];
    const { getByTestId } = renderHandlersTab(listeners, [], null);
    fireEvent.click(getByTestId("unified-row-listener-5"));
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/listener/5");
  });

  it("clicking a job row navigates to job deep-link URL", () => {
    const jobs = [createJob({ job_id: 20 })];
    const { getByTestId } = renderHandlersTab([], jobs, null);
    fireEvent.click(getByTestId("unified-row-job-20"));
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/job/20");
  });

  it("clicking a listener row includes instanceQs in deep-link URL", () => {
    const listeners = [createListener({ listener_id: 3 })];
    const { getByTestId } = renderWithAppState(
      <HandlersTab
        listeners={listeners}
        jobs={[]}
        selectedHandler={null}
        selectedExecId={null}
        appKey="test_app"
        instanceIndex={1}
      />,
      { storeOverrides: { uptimeSeconds: 120 } },
    );
    fireEvent.click(getByTestId("unified-row-listener-3"));
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/listener/3?instance=1");
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
        selectedHandler="listener/45"
        selectedExecId={null}
        appKey="test_app"
        onSwitchToCode={onSwitch}
      />,
      { storeOverrides: { uptimeSeconds: 120 } },
    );
    await waitFor(() => getByTestId("listener-detail-45"));
    fireEvent.click(getByTestId("view-in-code-btn"));
    expect(onSwitch).toHaveBeenCalledWith(99);
  });

  it("renders execution detail even when no handlers are registered", () => {
    const { getByTestId, queryByTestId } = renderWithAppState(
      <HandlersTab listeners={[]} jobs={[]} selectedHandler="listener/5" selectedExecId="abc-123" appKey="test_app" />,
      { storeOverrides: { uptimeSeconds: 120 } },
    );
    expect(getByTestId("execution-detail-fetcher")).toBeTruthy();
    expect(queryByTestId("handlers-empty")).toBeNull();
  });
});
