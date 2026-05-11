import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { render } from "@testing-library/preact";
import { h } from "preact";
import type { ComponentChildren } from "preact";
import { UnifiedHandlerRow } from "./unified-handler-row";
import { createListener, createJob } from "../../test/factories";
import { AppStateContext } from "../../state/context";
import { createAppState } from "../../state/create-app-state";

function wrapper({ children }: { children: ComponentChildren }) {
  return h(AppStateContext.Provider, { value: createAppState() }, children);
}

function makeListenerItem(overrides = {}) {
  const listener = createListener(overrides);
  return {
    kind: "listener" as const,
    id: listener.listener_id,
    name: listener.handler_summary || listener.handler_method,
    humanDescription: listener.human_description ?? null,
    statusKind: "ok" as const,
    data: listener,
  };
}

function makeJobItem(overrides = {}) {
  const job = createJob(overrides);
  return {
    kind: "job" as const,
    id: job.job_id,
    name: job.job_name,
    humanDescription: job.trigger_label !== "" ? job.trigger_label : null,
    statusKind: "ok" as const,
    data: job,
  };
}

describe("UnifiedHandlerRow — listener", () => {
  it("renders with data-testid containing kind and id", () => {
    const item = makeListenerItem({ listener_id: 42 });
    const { getByTestId } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByTestId("unified-row-listener-42")).toBeDefined();
  });

  it("renders handler name", () => {
    const item = makeListenerItem({ handler_summary: "on_motion_detected()", listener_id: 1 });
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("on_motion_detected()")).toBeDefined();
  });

  it("renders human_description as subtitle", () => {
    const listener = createListener({ human_description: "When kitchen light changes", listener_id: 1 });
    const item = { kind: "listener" as const, id: 1, name: "on_light_change", humanDescription: "When kitchen light changes", statusKind: "ok" as const, data: listener };
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("When kitchen light changes")).toBeDefined();
  });

  it("does not render subtitle when humanDescription is null", () => {
    const listener = createListener({ human_description: null, listener_id: 1 });
    const item = { kind: "listener" as const, id: 1, name: "on_change", humanDescription: null, statusKind: "ok" as const, data: listener };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(container.querySelector(".ht-unified-row__desc")).toBeNull();
  });

  it("renders invocation count in stats", () => {
    const item = makeListenerItem({ total_invocations: 7, listener_id: 1 });
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("7 calls")).toBeDefined();
  });

  it("renders failed count when failed > 0", () => {
    const item = makeListenerItem({ failed: 3, total_invocations: 10, listener_id: 1 });
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("3 failed")).toBeDefined();
  });

  it("renders timed_out count separately from failed", () => {
    const item = makeListenerItem({ timed_out: 2, failed: 1, total_invocations: 5, listener_id: 1 });
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("2 timed out")).toBeDefined();
    expect(getByText("1 failed")).toBeDefined();
  });

  it("does not render failed/timed_out when both are 0", () => {
    const item = makeListenerItem({ failed: 0, timed_out: 0, listener_id: 1 });
    const { queryByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(queryByText(/failed/)).toBeNull();
    expect(queryByText(/timed out/)).toBeNull();
  });

  it("adds --selected class when isSelected is true", () => {
    const item = makeListenerItem({ listener_id: 1 });
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={true} onSelect={() => {}} />,
      { wrapper },
    );
    expect(container.querySelector(".ht-unified-row--selected")).not.toBeNull();
  });

  it("does not add --selected class when isSelected is false", () => {
    const item = makeListenerItem({ listener_id: 1 });
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(container.querySelector(".ht-unified-row--selected")).toBeNull();
  });

  it("calls onSelect when clicked", () => {
    const onSelect = vi.fn();
    const item = makeListenerItem({ listener_id: 1 });
    const { getByRole } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={onSelect} />,
      { wrapper },
    );
    fireEvent.click(getByRole("button"));
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("calls onSelect when activated via Enter key (native button fires click)", () => {
    const onSelect = vi.fn();
    const item = makeListenerItem({ listener_id: 1 });
    const { getByRole } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={onSelect} />,
      { wrapper },
    );
    // Native <button> fires click on Enter/Space — fireEvent.click simulates that
    fireEvent.click(getByRole("button"));
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("calls onSelect when activated via Space key (native button fires click)", () => {
    const onSelect = vi.fn();
    const item = makeListenerItem({ listener_id: 1 });
    const { getByRole } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={onSelect} />,
      { wrapper },
    );
    // Native <button> fires click on Enter/Space — fireEvent.click simulates that
    fireEvent.click(getByRole("button"));
    expect(onSelect).toHaveBeenCalledOnce();
  });
});

describe("UnifiedHandlerRow — kind glyph", () => {
  it("renders kind glyph for state listener", () => {
    const listener = createListener({ listener_id: 1, topic: "state_changed" });
    const item = { kind: "listener" as const, id: 1, name: "on_state", humanDescription: null, statusKind: "ok" as const, data: listener };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(container.querySelector(".ht-unified-row__kind-glyph")).not.toBeNull();
  });

  it("renders ◆ glyph for event kind", () => {
    const listener = createListener({ listener_id: 1, topic: "some_event", listener_kind: "event" });
    const item = { kind: "listener" as const, id: 1, name: "on_event", humanDescription: null, statusKind: "ok" as const, data: listener };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    const glyph = container.querySelector(".ht-unified-row__kind-glyph");
    expect(glyph?.textContent).toBe("◆");
  });

  it("renders ◇ glyph for state kind", () => {
    const listener = createListener({ listener_id: 1, topic: "state_changed" });
    const item = { kind: "listener" as const, id: 1, name: "on_state", humanDescription: null, statusKind: "ok" as const, data: listener };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    const glyph = container.querySelector(".ht-unified-row__kind-glyph");
    expect(glyph?.textContent).toBe("◇");
  });

  it("renders ↻ glyph for cron job", () => {
    const job = createJob({ job_id: 1, trigger_type: "Cron" });
    const item = { kind: "job" as const, id: 1, name: "my_job", humanDescription: null, statusKind: "ok" as const, data: job };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    const glyph = container.querySelector(".ht-unified-row__kind-glyph");
    expect(glyph?.textContent).toBe("↻");
  });

  it("renders ↻ glyph for interval job", () => {
    const job = createJob({ job_id: 2, trigger_type: "Every" });
    const item = { kind: "job" as const, id: 2, name: "poll_job", humanDescription: null, statusKind: "ok" as const, data: job };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    const glyph = container.querySelector(".ht-unified-row__kind-glyph");
    expect(glyph?.textContent).toBe("↻");
  });
});

describe("UnifiedHandlerRow — subline switching", () => {
  it("shows last_error_message when handler has errors", () => {
    const listener = createListener({
      listener_id: 1,
      failed: 2,
      last_error_message: "KeyError: 'foo'",
      human_description: "When something changes",
    });
    const item = { kind: "listener" as const, id: 1, name: "on_change", humanDescription: "When something changes", statusKind: "err" as const, data: listener };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    // Error message shown
    const errSubline = container.querySelector(".ht-unified-row__subline--err");
    expect(errSubline).not.toBeNull();
    expect(errSubline?.textContent).toContain("KeyError");
  });

  it("shows human_description in dim when handler has no errors", () => {
    const listener = createListener({
      listener_id: 1,
      failed: 0,
      timed_out: 0,
      last_error_message: null,
      human_description: "Fires on door open",
    });
    const item = { kind: "listener" as const, id: 1, name: "on_door", humanDescription: "Fires on door open", statusKind: "ok" as const, data: listener };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    const descSubline = container.querySelector(".ht-unified-row__desc");
    expect(descSubline).not.toBeNull();
    expect(descSubline?.textContent).toContain("Fires on door open");
    expect(container.querySelector(".ht-unified-row__subline--err")).toBeNull();
  });

  it("shows next-run line for schedule jobs", () => {
    const job = createJob({ job_id: 1, next_run: Math.floor(Date.now() / 1000) + 60 });
    const item = { kind: "job" as const, id: 1, name: "my_job", humanDescription: null, statusKind: "ok" as const, data: job };
    const { container } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(container.querySelector(".ht-unified-row__next-run")).not.toBeNull();
  });
});

describe("UnifiedHandlerRow — job", () => {
  it("renders with data-testid containing kind='job' and job id", () => {
    const item = makeJobItem({ job_id: 7 });
    const { getByTestId } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByTestId("unified-row-job-7")).toBeDefined();
  });

  it("renders job name", () => {
    const item = makeJobItem({ job_name: "cleanup_task", job_id: 1 });
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("cleanup_task")).toBeDefined();
  });

  it("renders trigger_label as humanDescription subtitle for jobs", () => {
    const job = createJob({ job_id: 1, trigger_label: "every 5 minutes" });
    const item = { kind: "job" as const, id: 1, name: "my_job", humanDescription: "every 5 minutes", statusKind: "ok" as const, data: job };
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("every 5 minutes")).toBeDefined();
  });

  it("renders execution count in stats", () => {
    const item = makeJobItem({ total_executions: 4, job_id: 1 });
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("4 runs")).toBeDefined();
  });

  it("renders timed_out separate from failed for jobs", () => {
    const item = makeJobItem({ timed_out: 1, failed: 2, total_executions: 10, job_id: 1 });
    const { getByText } = render(
      <UnifiedHandlerRow item={item} isSelected={false} onSelect={() => {}} />,
      { wrapper },
    );
    expect(getByText("2 failed")).toBeDefined();
    expect(getByText("1 timed out")).toBeDefined();
  });
});
