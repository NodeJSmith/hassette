import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { FrameworkHealth } from "./framework-health";
import type { DashboardErrorEntry } from "../../api/endpoints";

function makeError(overrides: Partial<DashboardErrorEntry> = {}): DashboardErrorEntry {
  return {
    kind: "handler",
    listener_id: 1,
    job_id: null,
    topic: "state_changed",
    handler_method: "on_test",
    job_name: null,
    error_message: "boom",
    error_type: "RuntimeError",
    execution_start_ts: 1000,
    app_key: "test_app",
    source_tier: "app",
    error_traceback: null,
    ...overrides,
  };
}

describe("FrameworkHealth", () => {
  it("test_renders_count_badge: shows error count badge from feed data", () => {
    const errors: DashboardErrorEntry[] = [
      makeError({ source_tier: "framework", app_key: "__hassette__.bus_service" }),
      makeError({ source_tier: "framework", app_key: "__hassette__.service_watcher" }),
      makeError({ source_tier: "framework", app_key: "__hassette__.command_executor" }),
      makeError({ source_tier: "app" }),
    ];
    const { getByTestId } = render(
      <FrameworkHealth errors={errors} loading={false} hasError={false} />,
    );
    const badge = getByTestId("framework-error-count");
    expect(badge.textContent).toBe("3");
  });

  it("shows zero count when no framework errors", () => {
    const errors: DashboardErrorEntry[] = [
      makeError({ source_tier: "app" }),
    ];
    const { getByTestId } = render(
      <FrameworkHealth errors={errors} loading={false} hasError={false} />,
    );
    const badge = getByTestId("framework-error-count");
    expect(badge.textContent).toBe("0");
    expect(badge.className).toContain("ht-badge--success");
  });

  it("badge shows danger variant when framework errors present", () => {
    const errors: DashboardErrorEntry[] = [
      makeError({ source_tier: "framework", app_key: "__hassette__.bus_service" }),
    ];
    const { getByTestId } = render(
      <FrameworkHealth errors={errors} loading={false} hasError={false} />,
    );
    const badge = getByTestId("framework-error-count");
    expect(badge.className).toContain("ht-badge--danger");
  });

  it("test_no_error_feed_expansion: no expandable error list or aria-expanded", () => {
    const errors: DashboardErrorEntry[] = [
      makeError({ source_tier: "framework", app_key: "__hassette__.bus_service" }),
    ];
    const { container, queryByRole } = render(
      <FrameworkHealth errors={errors} loading={false} hasError={false} />,
    );
    expect(queryByRole("button")).toBeNull();
    expect(container.querySelector("[aria-expanded]")).toBeNull();
    expect(container.querySelector("[data-testid='dashboard-errors']")).toBeNull();
  });

  it("shows System Health label", () => {
    const { getByText } = render(
      <FrameworkHealth errors={[]} loading={false} hasError={false} />,
    );
    expect(getByText("System Health")).toBeDefined();
  });

  it("shows loading state", () => {
    const { getByTestId } = render(
      <FrameworkHealth errors={null} loading={true} hasError={false} />,
    );
    const badge = getByTestId("framework-error-count");
    expect(badge.textContent).toBe("…");
    expect(badge.className).toContain("ht-badge--neutral");
  });

  it("shows error state", () => {
    const { getByTestId } = render(
      <FrameworkHealth errors={null} loading={false} hasError={true} />,
    );
    const badge = getByTestId("framework-error-count");
    expect(badge.textContent).toBe("?");
    expect(badge.className).toContain("ht-badge--neutral");
  });
});
