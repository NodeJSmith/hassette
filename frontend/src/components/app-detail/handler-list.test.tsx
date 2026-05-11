import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { HandlerList } from "./handler-list";
import { createListener, createJob } from "../../test/factories";

// Mock UnifiedHandlerRow to isolate HandlerList behavior — the row component
// calls useScopedApi which requires AppStateContext and MSW.
vi.mock("./unified-handler-row", () => ({
  UnifiedHandlerRow: ({
    item,
    isSelected,
  }: {
    item: { kind: string; id: number; name: string; humanDescription: string | null };
    isSelected: boolean;
    onSelect: () => void;
  }) => (
    <div
      data-testid={`unified-row-${item.kind}-${item.id}`}
      data-selected={String(isSelected)}
    >
      {item.name}
      {item.humanDescription && <span>{item.humanDescription}</span>}
    </div>
  ),
}));

describe("HandlerList", () => {
  it("renders nothing when both arrays are empty", () => {
    const { container } = render(<HandlerList listeners={[]} jobs={[]} selectedId={null} onSelect={() => {}} />);
    expect(container.querySelector("[data-testid='handler-list']")).toBeNull();
  });

  it("renders handler-list container when listeners are present", () => {
    const listeners = [createListener({ listener_id: 1 })];
    const { getByTestId } = render(
      <HandlerList listeners={listeners} jobs={[]} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId("handler-list")).toBeDefined();
  });

  it("renders handler-list container when jobs are present", () => {
    const jobs = [createJob({ job_id: 10 })];
    const { getByTestId } = render(
      <HandlerList listeners={[]} jobs={jobs} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId("handler-list")).toBeDefined();
  });

  it("renders a row for each listener with kind='listener'", () => {
    const listeners = [
      createListener({ listener_id: 1 }),
      createListener({ listener_id: 2 }),
    ];
    const { getByTestId } = render(
      <HandlerList listeners={listeners} jobs={[]} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId("unified-row-listener-1")).toBeDefined();
    expect(getByTestId("unified-row-listener-2")).toBeDefined();
  });

  it("renders a row for each job with kind='job'", () => {
    const jobs = [
      createJob({ job_id: 5 }),
      createJob({ job_id: 6 }),
    ];
    const { getByTestId } = render(
      <HandlerList listeners={[]} jobs={jobs} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId("unified-row-job-5")).toBeDefined();
    expect(getByTestId("unified-row-job-6")).toBeDefined();
  });

  it("renders both listeners and jobs in the same list", () => {
    const listeners = [createListener({ listener_id: 1 })];
    const jobs = [createJob({ job_id: 10 })];
    const { getByTestId } = render(
      <HandlerList listeners={listeners} jobs={jobs} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByTestId("unified-row-listener-1")).toBeDefined();
    expect(getByTestId("unified-row-job-10")).toBeDefined();
  });

  it("renders listener human_description as subtitle via row", () => {
    const listeners = [
      createListener({ listener_id: 3, human_description: "Triggers when kitchen light changes" }),
    ];
    const { getByText } = render(
      <HandlerList listeners={listeners} jobs={[]} selectedId={null} onSelect={() => {}} />,
    );
    expect(getByText("Triggers when kitchen light changes")).toBeDefined();
  });

  it("passes isSelected=true for the selected item", () => {
    const listeners = [
      createListener({ listener_id: 1 }),
      createListener({ listener_id: 2 }),
    ];
    const { getByTestId } = render(
      <HandlerList
        listeners={listeners}
        jobs={[]}
        selectedId={{ kind: "listener", id: 1 }}
        onSelect={() => {}}
      />,
    );
    expect(getByTestId("unified-row-listener-1").getAttribute("data-selected")).toBe("true");
    expect(getByTestId("unified-row-listener-2").getAttribute("data-selected")).toBe("false");
  });

  it("listeners are rendered before jobs in the list", () => {
    const listeners = [createListener({ listener_id: 1, handler_method: "on_motion" })];
    const jobs = [createJob({ job_id: 5, job_name: "cleanup" })];
    const { container } = render(
      <HandlerList listeners={listeners} jobs={jobs} selectedId={null} onSelect={() => {}} />,
    );
    const rows = container.querySelectorAll("[data-testid^='unified-row-']");
    expect(rows[0].getAttribute("data-testid")).toBe("unified-row-listener-1");
    expect(rows[1].getAttribute("data-testid")).toBe("unified-row-job-5");
  });
});
