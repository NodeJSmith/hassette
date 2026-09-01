import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createJob, createListener } from "../../test/factories";
import { HandlerList } from "./handler-list";

const HANDLER_LIST_TEST_ID = "handler-list";

// vi.hoisted so the row test-id convention is shared between the hoisted vi.mock
// factory below and the assertions that read it.
const { ROW_TEST_ID_PREFIX, rowTestId } = vi.hoisted(() => {
  const prefix = "unified-row-";
  return {
    ROW_TEST_ID_PREFIX: prefix,
    rowTestId: (kind: string, id: number) => `${prefix}${kind}-${id}`,
  };
});

// Mock UnifiedHandlerRow to isolate HandlerList behavior — the row component
// calls query hooks which require the Zustand app store (useAppStore) and MSW.
vi.mock("./unified-handler-row", () => ({
  UnifiedHandlerRow: ({
    item,
    isSelected,
  }: {
    item: { kind: string; id: number; name: string; humanDescription: string | null };
    isSelected: boolean;
    onSelect: () => void;
  }) => (
    <div data-testid={rowTestId(item.kind, item.id)} data-selected={String(isSelected)}>
      {item.name}
      {item.humanDescription && <span>{item.humanDescription}</span>}
    </div>
  ),
}));

describe("HandlerList", () => {
  it("renders nothing when both arrays are empty", () => {
    const { container } = render(<HandlerList listeners={[]} jobs={[]} selectedId={null} onSelect={() => {}} />);
    expect(container.querySelector(`[data-testid='${HANDLER_LIST_TEST_ID}']`)).toBeNull();
  });

  it("renders handler-list container when listeners are present", () => {
    const listeners = [createListener({ listener_id: 1 })];
    const { getByTestId } = render(
      <HandlerList listeners={listeners} jobs={[]} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId(HANDLER_LIST_TEST_ID)).toBeDefined();
  });

  it("renders handler-list container when jobs are present", () => {
    const jobs = [createJob({ job_id: 10 })];
    const { getByTestId } = render(<HandlerList listeners={[]} jobs={jobs} selectedId={null} onSelect={() => {}} />);
    expect(getByTestId(HANDLER_LIST_TEST_ID)).toBeDefined();
  });

  it("renders a row for each listener with kind='listener'", () => {
    const listeners = [createListener({ listener_id: 1 }), createListener({ listener_id: 2 })];
    const { getByTestId } = render(
      <HandlerList listeners={listeners} jobs={[]} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId(rowTestId("listener", 1))).toBeDefined();
    expect(getByTestId(rowTestId("listener", 2))).toBeDefined();
  });

  it("renders a row for each job with kind='job'", () => {
    const jobs = [createJob({ job_id: 5 }), createJob({ job_id: 6 })];
    const { getByTestId } = render(<HandlerList listeners={[]} jobs={jobs} selectedId={null} onSelect={() => {}} />);
    expect(getByTestId(rowTestId("job", 5))).toBeDefined();
    expect(getByTestId(rowTestId("job", 6))).toBeDefined();
  });

  it("renders both listeners and jobs in the same list", () => {
    const listeners = [createListener({ listener_id: 1 })];
    const jobs = [createJob({ job_id: 10 })];
    const { getByTestId } = render(
      <HandlerList listeners={listeners} jobs={jobs} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId(rowTestId("listener", 1))).toBeDefined();
    expect(getByTestId(rowTestId("job", 10))).toBeDefined();
  });

  it("renders listener human_description as subtitle via row", () => {
    const listeners = [createListener({ listener_id: 3, human_description: "Triggers when kitchen light changes" })];
    const { getByText } = render(<HandlerList listeners={listeners} jobs={[]} selectedId={null} onSelect={() => {}} />);
    expect(getByText("Triggers when kitchen light changes")).toBeDefined();
  });

  it("passes isSelected=true for the selected item", () => {
    const listeners = [createListener({ listener_id: 1 }), createListener({ listener_id: 2 })];
    const { getByTestId } = render(
      <HandlerList listeners={listeners} jobs={[]} selectedId={{ kind: "listener", id: 1 }} onSelect={() => {}} />,
    );
    expect(getByTestId(rowTestId("listener", 1)).getAttribute("data-selected")).toBe("true");
    expect(getByTestId(rowTestId("listener", 2)).getAttribute("data-selected")).toBe("false");
  });

  it("renders issues first while preserving source order within each health group", () => {
    const listeners = [
      createListener({ listener_id: 1, handler_method: "healthy_listener", total_invocations: 1 }),
      createListener({ listener_id: 2, handler_method: "failing_listener", failed: 1 }),
    ];
    const jobs = [
      createJob({ job_id: 5, job_name: "healthy_job", total_executions: 1 }),
      createJob({ job_id: 6, job_name: "failing_job", failed: 1 }),
      createJob({ job_id: 7, job_name: "idle_job", total_executions: 0 }),
    ];
    const { container } = render(
      <HandlerList listeners={listeners} jobs={jobs} selectedId={null} onSelect={() => {}} />,
    );
    const rows = container.querySelectorAll(`[data-testid^='${ROW_TEST_ID_PREFIX}']`);
    expect(Array.from(rows, (row) => row.getAttribute("data-testid"))).toEqual([
      rowTestId("listener", 2),
      rowTestId("job", 6),
      rowTestId("listener", 1),
      rowTestId("job", 5),
      rowTestId("job", 7),
    ]);
  });
});
