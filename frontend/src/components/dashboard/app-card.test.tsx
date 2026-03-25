import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { AppCard } from "./app-card";
import type { DashboardAppGridEntry } from "../../api/endpoints";

vi.mock("../../hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

function createApp(overrides: Partial<DashboardAppGridEntry> = {}): DashboardAppGridEntry {
  return {
    app_key: "test_app",
    status: "running",
    display_name: "Test App",
    instance_count: 1,
    handler_count: 3,
    job_count: 2,
    total_invocations: 10,
    total_errors: 0,
    total_executions: 5,
    total_job_errors: 0,
    avg_duration_ms: 50,
    health_status: "good",
    error_rate: 0,
    error_rate_class: "good",
    last_activity_ts: Date.now() / 1000,
    ...overrides,
  };
}

describe("AppCard", () => {
  it("renders display name", () => {
    const { getByText } = render(<AppCard app={createApp({ display_name: "My Automation" })} />);
    expect(getByText("My Automation")).toBeDefined();
  });

  it("renders handler and job counts", () => {
    const { getByText } = render(<AppCard app={createApp({ handler_count: 5, job_count: 3 })} />);
    expect(getByText("5 handlers")).toBeDefined();
    expect(getByText("3 jobs")).toBeDefined();
  });

  it("does not show instance badge when count is 1", () => {
    const { container } = render(<AppCard app={createApp({ instance_count: 1 })} />);
    expect(container.querySelector(".ht-badge--neutral")).toBeNull();
  });

  it("shows instance badge when count > 1", () => {
    const { getByTitle } = render(<AppCard app={createApp({ instance_count: 3 })} />);
    const badge = getByTitle("3 instances");
    expect(badge).toBeDefined();
    expect(badge.textContent).toContain("3");
  });

  it("does not show instance badge when count is 0", () => {
    const { container } = render(<AppCard app={createApp({ instance_count: 0 })} />);
    expect(container.querySelector(".ht-badge--neutral")).toBeNull();
  });

  it("shows invocation and execution counts when non-zero", () => {
    const { getByTestId } = render(
      <AppCard app={createApp({ total_invocations: 10, total_executions: 5 })} />,
    );
    expect(getByTestId("app-card-counts")).toBeDefined();
  });

  it("hides counts when invocations and executions are zero", () => {
    const { queryByTestId } = render(
      <AppCard app={createApp({ total_invocations: 0, total_executions: 0 })} />,
    );
    expect(queryByTestId("app-card-counts")).toBeNull();
  });

  it("shows error rate when invocations exist", () => {
    const { getByTestId } = render(
      <AppCard app={createApp({ error_rate: 5.0, error_rate_class: "good", total_invocations: 100, total_executions: 0 })} />,
    );
    const errorRate = getByTestId("app-card-error-rate");
    expect(errorRate.textContent).toBe("5.0% errors");
  });

  it("hides error rate when no invocations or executions", () => {
    const { queryByTestId } = render(
      <AppCard app={createApp({ error_rate: 0, total_invocations: 0, total_executions: 0 })} />,
    );
    expect(queryByTestId("app-card-error-rate")).toBeNull();
  });

  it("colors error rate using error rate class variant", () => {
    const { getByTestId } = render(
      <AppCard app={createApp({ error_rate: 50.0, error_rate_class: "bad", total_invocations: 100, total_errors: 50 })} />,
    );
    const errorRate = getByTestId("app-card-error-rate");
    expect(errorRate.className).toContain("ht-text-danger");
  });
});
