import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { ErrorFeed } from "./error-feed";
import type { DashboardErrorEntry } from "../../api/endpoints";

vi.mock("../../hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

function createError(overrides: Partial<DashboardErrorEntry> = {}): DashboardErrorEntry {
  return {
    kind: "handler",
    error_message: "something broke",
    error_type: "ValueError",
    timestamp: 1700000000,
    app_key: "test_app",
    listener_id: 42,
    topic: "state_changed",
    handler_method: "on_light_change",
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
        errors={[createError({ kind: "job", job_name: "cleanup", handler_method: undefined, job_id: 7 })]}
      />,
    );
    expect(getByText("cleanup")).toBeDefined();
  });

  it("unknown kind gets neutral class", () => {
    const { container } = render(
      <ErrorFeed errors={[createError({ kind: "cron" as DashboardErrorEntry["kind"] })]} />,
    );
    const badge = container.querySelector(".ht-tag");
    expect(badge?.className).toContain("ht-tag--neutral");
  });

  it("key uses listener_id not timestamp+index", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const errors = [
      createError({ listener_id: 10, timestamp: 1700000000, app_key: "app_a" }),
      createError({ listener_id: 20, timestamp: 1700000000, app_key: "app_a" }),
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
