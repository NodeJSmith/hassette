import { render } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { createJob, createListener } from "../../test/factories";
import { HandlerList } from "./handler-list";
import type { UnifiedItemKind } from "./unified-handler-row";
import { ROW_TESTID_PREFIX, rowTestId } from "./unified-row.test-helpers";

const HANDLER_LIST_TEST_ID = "handler-list";

const noop = () => {};

// Mock UnifiedHandlerRow to isolate HandlerList behavior — the row component
// calls query hooks which require the Zustand app store (useAppStore) and MSW.
vi.mock("./unified-handler-row", () => ({
  UnifiedHandlerRow: ({
    item,
    isSelected,
  }: {
    item: { kind: UnifiedItemKind; id: number; name: string; humanDescription: string | null };
    isSelected: boolean;
    onSelect: () => void;
  }) => (
    <div data-testid={rowTestId(item.kind, item.id)} data-selected={String(isSelected)}>
      {item.name}
      {item.humanDescription && <span>{item.humanDescription}</span>}
    </div>
  ),
}));

/** Renders HandlerList with empty/unselected defaults so each test states only the props it varies. */
function renderHandlerList(overrides: Partial<ComponentProps<typeof HandlerList>> = {}) {
  return render(<HandlerList listeners={[]} jobs={[]} selectedId={null} onSelect={noop} {...overrides} />);
}

describe("HandlerList", () => {
  it("renders nothing when both arrays are empty", () => {
    const { container } = renderHandlerList();
    expect(container.querySelector(`[data-testid='${HANDLER_LIST_TEST_ID}']`)).toBeNull();
  });

  it("renders handler-list container when listeners are present", () => {
    const { getByTestId } = renderHandlerList({ listeners: [createListener({ listener_id: 1 })] });
    expect(getByTestId(HANDLER_LIST_TEST_ID)).toBeDefined();
  });

  it("renders handler-list container when jobs are present", () => {
    const { getByTestId } = renderHandlerList({ jobs: [createJob({ job_id: 10 })] });
    expect(getByTestId(HANDLER_LIST_TEST_ID)).toBeDefined();
  });

  it("renders a row for each listener with kind='listener'", () => {
    const { getByTestId } = renderHandlerList({
      listeners: [createListener({ listener_id: 1 }), createListener({ listener_id: 2 })],
    });
    expect(getByTestId(rowTestId("listener", 1))).toBeDefined();
    expect(getByTestId(rowTestId("listener", 2))).toBeDefined();
  });

  it("renders a row for each job with kind='job'", () => {
    const { getByTestId } = renderHandlerList({ jobs: [createJob({ job_id: 5 }), createJob({ job_id: 6 })] });
    expect(getByTestId(rowTestId("job", 5))).toBeDefined();
    expect(getByTestId(rowTestId("job", 6))).toBeDefined();
  });

  it("renders both listeners and jobs in the same list", () => {
    const { getByTestId } = renderHandlerList({
      listeners: [createListener({ listener_id: 1 })],
      jobs: [createJob({ job_id: 10 })],
    });
    expect(getByTestId(rowTestId("listener", 1))).toBeDefined();
    expect(getByTestId(rowTestId("job", 10))).toBeDefined();
  });

  it("renders listener human_description as subtitle via row", () => {
    const { getByText } = renderHandlerList({
      listeners: [createListener({ listener_id: 3, human_description: "Triggers when kitchen light changes" })],
    });
    expect(getByText("Triggers when kitchen light changes")).toBeDefined();
  });

  it("passes isSelected=true for the selected item", () => {
    const { getByTestId } = renderHandlerList({
      listeners: [createListener({ listener_id: 1 }), createListener({ listener_id: 2 })],
      selectedId: { kind: "listener", id: 1 },
    });
    expect(getByTestId(rowTestId("listener", 1)).getAttribute("data-selected")).toBe("true");
    expect(getByTestId(rowTestId("listener", 2)).getAttribute("data-selected")).toBe("false");
  });

  it("renders issues first while preserving source order within each health group", () => {
    const healthyListener = createListener({
      listener_id: 1,
      handler_method: "healthy_listener",
      total_invocations: 1,
    });
    const failingListener = createListener({ listener_id: 2, handler_method: "failing_listener", failed: 1 });
    const healthyJob = createJob({ job_id: 5, job_name: "healthy_job", total_executions: 1 });
    const failingJob = createJob({ job_id: 6, job_name: "failing_job", failed: 1 });
    const idleJob = createJob({ job_id: 7, job_name: "idle_job", total_executions: 0 });

    const { container } = renderHandlerList({
      listeners: [healthyListener, failingListener],
      jobs: [healthyJob, failingJob, idleJob],
    });

    const rows = container.querySelectorAll(`[data-testid^='${ROW_TESTID_PREFIX}']`);
    expect(Array.from(rows, (row) => row.getAttribute("data-testid"))).toEqual([
      rowTestId("listener", failingListener.listener_id),
      rowTestId("job", failingJob.job_id),
      rowTestId("listener", healthyListener.listener_id),
      rowTestId("job", healthyJob.job_id),
      rowTestId("job", idleJob.job_id),
    ]);
  });
});
