import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { ErrorFeed } from "./error-feed";
import type { DashboardErrorEntry, HandlerErrorEntry, JobErrorEntry } from "../../api/endpoints";

vi.mock("../../hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

function createError(overrides: Partial<HandlerErrorEntry> = {}): HandlerErrorEntry {
  return {
    kind: "handler",
    error_message: "something broke",
    error_type: "ValueError",
    execution_start_ts: 1700000000,
    app_key: "test_app",
    listener_id: 42,
    topic: "state_changed",
    handler_method: "on_light_change",
    source_tier: "app",
    ...overrides,
  };
}

function createJobError(overrides: Partial<JobErrorEntry> = {}): JobErrorEntry {
  return {
    kind: "job",
    error_message: "something broke",
    error_type: "ValueError",
    execution_start_ts: 1700000000,
    app_key: "test_app",
    job_id: 7,
    job_name: "cleanup",
    source_tier: "app",
    ...overrides,
  };
}

describe("ErrorFeed", () => {
  it("renders empty state when no errors", () => {
    const { getByText } = render(<ErrorFeed errors={[]} />);
    expect(getByText("No recent errors. All systems healthy.")).toBeDefined();
  });

  it("badge shows error_type not kind", () => {
    const { container } = render(<ErrorFeed errors={[createError({ error_type: "ValueError" })]} />);
    const badge = container.querySelector(".ht-tag");
    expect(badge?.textContent).toBe("ValueError");
  });

  it("badge falls back to kind when error_type is empty", () => {
    const { container } = render(<ErrorFeed errors={[createError({ error_type: "" })]} />);
    const badge = container.querySelector(".ht-tag");
    expect(badge?.textContent).toBe("handler");
  });

  it("truncates long dotted error_type to last component", () => {
    const { container } = render(
      <ErrorFeed errors={[createError({ error_type: "homeassistant.exceptions.ServiceNotFound" })]} />,
    );
    const badge = container.querySelector(".ht-tag");
    expect(badge?.textContent).toBe("ServiceNotFound");
  });

  it("shows handler_method in subtitle", () => {
    const { getByText } = render(
      <ErrorFeed errors={[createError({ handler_method: "on_button_press" })]} />,
    );
    expect(getByText("on_button_press")).toBeDefined();
  });

  it("shows job_name for job errors", () => {
    const { getByText } = render(
      <ErrorFeed
        errors={[createJobError({ job_name: "cleanup" })]}
      />,
    );
    expect(getByText("cleanup")).toBeDefined();
  });

  it("unknown kind gets neutral class", () => {
    const { container } = render(
      <ErrorFeed errors={[{ ...createError(), kind: "cron" } as unknown as DashboardErrorEntry]} />,
    );
    const badge = container.querySelector(".ht-tag");
    expect(badge?.className).toContain("ht-tag--neutral");
  });

  it("renders 'deleted handler' when listener_id is null", () => {
    const err = createError({ listener_id: null as unknown as number, app_key: null as unknown as string });
    const { getAllByText } = render(<ErrorFeed errors={[err]} />);
    expect(getAllByText("deleted handler").length).toBeGreaterThan(0);
  });

  it("renders 'deleted job' when job_id is null", () => {
    const err = createJobError({ job_id: null as unknown as number, app_key: null as unknown as string });
    const { getAllByText } = render(<ErrorFeed errors={[err]} />);
    expect(getAllByText("deleted job").length).toBeGreaterThan(0);
  });

  it("renders a 'Framework' tier badge when source_tier is 'framework'", () => {
    const err = createError({ source_tier: "framework" } as Parameters<typeof createError>[0]);
    const { getByText } = render(<ErrorFeed errors={[err]} />);
    expect(getByText("Framework")).toBeDefined();
  });

  it("does not render tier badge for app-tier errors", () => {
    const err = createError({ source_tier: "app" } as Parameters<typeof createError>[0]);
    const { queryByText } = render(<ErrorFeed errors={[err]} />);
    expect(queryByText("Framework")).toBeNull();
  });

  it("key uses listener_id not execution_start_ts+index", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const errors = [
      createError({ listener_id: 10, execution_start_ts: 1700000000, app_key: "app_a" }),
      createError({ listener_id: 20, execution_start_ts: 1700000000, app_key: "app_a" }),
    ];
    render(<ErrorFeed errors={errors} />);
    // No duplicate key warnings should appear
    const keyWarnings = spy.mock.calls.filter(
      (args) => typeof args[0] === "string" && args[0].includes("key"),
    );
    expect(keyWarnings).toHaveLength(0);
    spy.mockRestore();
  });
});
