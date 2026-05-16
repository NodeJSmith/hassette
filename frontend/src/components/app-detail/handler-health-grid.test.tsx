import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { HandlerHealthGrid } from "./handler-health-grid";
import { createListener, createJob } from "../../test/factories";
import type { UnifiedItem } from "./unified-handler-row";

vi.mock("wouter", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: preact.ComponentChildren; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
  useLocation: () => ["/", vi.fn()],
  useSearch: () => "",
}));

function makeListenerItem(overrides: Partial<ReturnType<typeof createListener>> = {}): UnifiedItem {
  const listener = createListener(overrides);
  const failing = (listener.failed ?? 0) > 0 || (listener.timed_out ?? 0) > 0;
  return {
    kind: "listener",
    id: listener.listener_id,
    name: listener.handler_summary ?? listener.handler_method,
    humanDescription: listener.human_description ?? null,
    statusKind: failing ? "err" : "ok",
    data: listener,
  };
}

function makeJobItem(overrides: Partial<ReturnType<typeof createJob>> = {}): UnifiedItem {
  const job = createJob(overrides);
  const failing = (job.failed ?? 0) > 0 || (job.timed_out ?? 0) > 0;
  return {
    kind: "job",
    id: job.job_id,
    name: job.job_name,
    humanDescription: job.trigger_label || null,
    statusKind: failing ? "err" : "ok",
    data: job,
  };
}

describe("HandlerHealthGrid — empty state", () => {
  it("renders the section wrapper with testid even when empty", () => {
    const { getByTestId } = render(
      <HandlerHealthGrid items={[]} appKey="test_app" instanceQs="" />,
    );
    expect(getByTestId("overview-health-grid")).toBeDefined();
  });

  it("renders EmptyState with testid when no items", () => {
    const { getByTestId } = render(
      <HandlerHealthGrid items={[]} appKey="test_app" instanceQs="" />,
    );
    expect(getByTestId("overview-health-empty")).toBeDefined();
  });

  it("does not render cards when items are empty", () => {
    const { container } = render(
      <HandlerHealthGrid items={[]} appKey="test_app" instanceQs="" />,
    );
    expect(container.querySelectorAll("[data-testid^='overview-health-card-']")).toHaveLength(0);
  });
});

describe("HandlerHealthGrid — with items", () => {
  it("renders a card per item", () => {
    const items = [
      makeListenerItem({ listener_id: 1 }),
      makeJobItem({ job_id: 2 }),
    ];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(getByTestId("overview-health-card-listener-1")).toBeDefined();
    expect(getByTestId("overview-health-card-job-2")).toBeDefined();
  });

  it("does not render EmptyState when items are present", () => {
    const items = [makeListenerItem({ listener_id: 1 })];
    const { queryByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(queryByTestId("overview-health-empty")).toBeNull();
  });

  it("renders the section heading", () => {
    const items = [makeListenerItem({ listener_id: 1 })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const heading = container.querySelector("h3");
    expect(heading?.textContent?.toLowerCase()).toContain("handler health");
  });
});

describe("HandlerHealthGrid — sorting (failing first)", () => {
  it("renders failing items before healthy items", () => {
    const items = [
      makeListenerItem({ listener_id: 1, failed: 0, timed_out: 0, handler_summary: "on_healthy()" }),
      makeListenerItem({ listener_id: 2, failed: 2, total_invocations: 5, handler_summary: "on_broken()" }),
    ];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const cards = container.querySelectorAll("[data-testid^='overview-health-card-']");
    expect(cards[0].getAttribute("data-testid")).toBe("overview-health-card-listener-2");
    expect(cards[1].getAttribute("data-testid")).toBe("overview-health-card-listener-1");
  });
});

describe("HandlerHealthGrid — passes props to cards", () => {
  it("renders correct number of cards for given items", () => {
    const items = [
      makeListenerItem({ listener_id: 3 }),
      makeJobItem({ job_id: 7 }),
      makeListenerItem({ listener_id: 5 }),
    ];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="?instance=1" />,
    );
    const cards = container.querySelectorAll("[data-testid^='overview-health-card-']");
    expect(cards).toHaveLength(3);
  });
});
