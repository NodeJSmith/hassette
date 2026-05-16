import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { HandlerHealthGrid } from "./handler-health-grid";
import { createListener, createJob } from "../../test/factories";
import type { UnifiedItem } from "./unified-handler-row";

const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: preact.ComponentChildren; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
  useLocation: () => ["/", mockNavigate],
  useSearch: () => "",
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

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

  it("does not render a table when items are empty", () => {
    const { container } = render(
      <HandlerHealthGrid items={[]} appKey="test_app" instanceQs="" />,
    );
    expect(container.querySelector("table")).toBeNull();
  });
});

describe("HandlerHealthGrid — table with items", () => {
  it("renders a table when items are present", () => {
    const items = [makeListenerItem({ listener_id: 1 })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("renders a row per item", () => {
    const items = [
      makeListenerItem({ listener_id: 1 }),
      makeJobItem({ job_id: 2 }),
    ];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(getByTestId("overview-health-row-listener-1")).toBeDefined();
    expect(getByTestId("overview-health-row-job-2")).toBeDefined();
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

describe("HandlerHealthGrid — failing rows", () => {
  it("applies the failing row class when item has errors", () => {
    const items = [makeListenerItem({ listener_id: 1, failed: 3, total_invocations: 10 })];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const row = getByTestId("overview-health-row-listener-1");
    // The component applies a healthRowFailing CSS module class
    expect(row.className).toMatch(/healthRowFailing/);
  });

  it("does NOT apply the failing class when item has no errors", () => {
    const items = [makeListenerItem({ listener_id: 1, failed: 0, timed_out: 0 })];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const row = getByTestId("overview-health-row-listener-1");
    expect(row.className).not.toMatch(/healthRowFailing/);
  });

  it("renders error type text for failing items", () => {
    const items = [
      makeListenerItem({
        listener_id: 1,
        failed: 1,
        last_error_type: "KeyError",
        total_invocations: 5,
      }),
    ];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(container.textContent).toContain("KeyError");
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
    const rows = container.querySelectorAll("[data-testid^='overview-health-row-']");
    // Failing row (id=2) should appear first after sort
    expect(rows[0].getAttribute("data-testid")).toBe("overview-health-row-listener-2");
    expect(rows[1].getAttribute("data-testid")).toBe("overview-health-row-listener-1");
  });
});

describe("HandlerHealthGrid — run count", () => {
  it("shows invocation count for listeners", () => {
    const items = [makeListenerItem({ listener_id: 1, total_invocations: 7 })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(container.textContent).toContain("7");
  });

  it("shows execution count for jobs", () => {
    const items = [makeJobItem({ job_id: 1, total_executions: 4 })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(container.textContent).toContain("4");
  });
});

describe("HandlerHealthGrid — navigation link", () => {
  it("renders a link to the handler path for listener items", () => {
    const items = [makeListenerItem({ listener_id: 3 })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toContain("/apps/test_app/handlers/h-3");
  });

  it("renders a link to the handler path for job items", () => {
    const items = [makeJobItem({ job_id: 5 })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toContain("/apps/test_app/handlers/j-5");
  });

  it("includes instanceQs in the handler path", () => {
    const items = [makeListenerItem({ listener_id: 1 })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="?instance=1" />,
    );
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toContain("?instance=1");
  });
});

describe("HandlerHealthGrid — row interactions", () => {
  it("navigates on row click", () => {
    mockNavigate.mockClear();
    const items = [makeListenerItem({ listener_id: 1 })];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const row = getByTestId("overview-health-row-listener-1");
    fireEvent.click(row);
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/h-1");
  });

  it("navigates on Enter keydown", () => {
    mockNavigate.mockClear();
    const items = [makeListenerItem({ listener_id: 1 })];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const row = getByTestId("overview-health-row-listener-1");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/h-1");
  });

  it("navigates on Space keydown", () => {
    mockNavigate.mockClear();
    const items = [makeListenerItem({ listener_id: 1 })];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const row = getByTestId("overview-health-row-listener-1");
    fireEvent.keyDown(row, { key: " " });
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/handlers/h-1");
  });

  it("does not navigate on other key presses", () => {
    mockNavigate.mockClear();
    const items = [makeListenerItem({ listener_id: 1 })];
    const { getByTestId } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    const row = getByTestId("overview-health-row-listener-1");
    fireEvent.keyDown(row, { key: "Tab" });
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("renders kind chip with correct label for listener", () => {
    const items = [makeListenerItem({ listener_id: 1, listener_kind: "state change" })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(container.textContent).toContain("state change");
  });

  it("renders kind chip with correct label for job", () => {
    const items = [makeJobItem({ job_id: 1, trigger_type: "interval" })];
    const { container } = render(
      <HandlerHealthGrid items={items} appKey="test_app" instanceQs="" />,
    );
    expect(container.textContent).toContain("interval");
  });
});
