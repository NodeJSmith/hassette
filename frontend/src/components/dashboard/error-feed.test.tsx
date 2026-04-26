import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { ErrorFeed } from "./error-feed";
import type { DashboardErrorEntry } from "../../api/endpoints";
import { createHandlerError, createJobError } from "../../test/factories";

vi.mock("../../hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

describe("ErrorFeed", () => {
  it("renders empty state when no errors", () => {
    const { getByText } = render(<ErrorFeed errors={[]} />);
    expect(getByText("No recent errors. All systems healthy.")).toBeDefined();
  });

  it("badge shows error_type not kind", () => {
    const { container } = render(<ErrorFeed errors={[createHandlerError({ error_type: "ValueError" })]} />);
    const badge = container.querySelector(".ht-tag");
    expect(badge?.textContent).toBe("ValueError");
  });

  it("badge falls back to kind when error_type is empty", () => {
    const { container } = render(<ErrorFeed errors={[createHandlerError({ error_type: "" })]} />);
    const badge = container.querySelector(".ht-tag");
    expect(badge?.textContent).toBe("handler");
  });

  it("truncates long dotted error_type to last component", () => {
    const { container } = render(
      <ErrorFeed errors={[createHandlerError({ error_type: "homeassistant.exceptions.ServiceNotFound" })]} />,
    );
    const badge = container.querySelector(".ht-tag");
    expect(badge?.textContent).toBe("ServiceNotFound");
  });

  it("shows handler_method in subtitle", () => {
    const { getByText } = render(
      <ErrorFeed errors={[createHandlerError({ handler_method: "on_button_press" })]} />,
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
      <ErrorFeed errors={[{ ...createHandlerError(), kind: "cron" } as unknown as DashboardErrorEntry]} />,
    );
    const badge = container.querySelector(".ht-tag");
    expect(badge?.className).toContain("ht-tag--neutral");
  });

  it("renders 'deleted handler' when listener_id is null", () => {
    const err = createHandlerError({ listener_id: null as unknown as number, app_key: null as unknown as string });
    const { getAllByText } = render(<ErrorFeed errors={[err]} />);
    expect(getAllByText("deleted handler").length).toBeGreaterThan(0);
  });

  it("renders 'deleted job' when job_id is null", () => {
    const err = createJobError({ job_id: null as unknown as number, app_key: null as unknown as string });
    const { getAllByText } = render(<ErrorFeed errors={[err]} />);
    expect(getAllByText("deleted job").length).toBeGreaterThan(0);
  });

  it("renders a 'Framework' tier badge when source_tier is 'framework'", () => {
    const err = createHandlerError({ source_tier: "framework" } as Parameters<typeof createHandlerError>[0]);
    const { getByText } = render(<ErrorFeed errors={[err]} />);
    expect(getByText("Framework")).toBeDefined();
  });

  it("does not render tier badge for app-tier errors", () => {
    const err = createHandlerError({ source_tier: "app" } as Parameters<typeof createHandlerError>[0]);
    const { queryByText } = render(<ErrorFeed errors={[err]} />);
    expect(queryByText("Framework")).toBeNull();
  });

  it("key uses listener_id not execution_start_ts+index", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const errors = [
      createHandlerError({ listener_id: 10, execution_start_ts: 1700000000, app_key: "app_a" }),
      createHandlerError({ listener_id: 20, execution_start_ts: 1700000000, app_key: "app_a" }),
    ];
    render(<ErrorFeed errors={errors} />);
    // No duplicate key warnings should appear
    const keyWarnings = spy.mock.calls.filter(
      (args) => typeof args[0] === "string" && args[0].includes("key"),
    );
    expect(keyWarnings).toHaveLength(0);
    spy.mockRestore();
  });

  it("test_framework_error_renders_badge_not_link: framework app_key renders as span not anchor", () => {
    const err = createHandlerError({ app_key: "__hassette__.service_watcher", source_tier: "framework" });
    const { container, queryByRole } = render(<ErrorFeed errors={[err]} />);
    // Must not be an anchor link
    const links = queryByRole("link");
    expect(links).toBeNull();
    // Must be a span with muted text showing the display label
    const spans = container.querySelectorAll(".ht-text-muted");
    const found = Array.from(spans).some((el) => el.textContent === "Service Watcher");
    expect(found).toBe(true);
  });

  it("test_traceback_toggle_shown_when_present: traceback button visible when error_traceback set", () => {
    const err = createHandlerError({ error_traceback: "Traceback (most recent call last):\n  File test.py" });
    const { getByRole } = render(<ErrorFeed errors={[err]} />);
    const button = getByRole("button", { name: /traceback/i });
    expect(button).toBeDefined();
  });

  it("test_traceback_toggle_hidden_when_absent: no traceback button when error_traceback is null", () => {
    const err = createHandlerError({ error_traceback: null });
    const { queryByRole } = render(<ErrorFeed errors={[err]} />);
    expect(queryByRole("button", { name: /traceback/i })).toBeNull();
  });

  it("test_traceback_toggle_expands_pre: clicking toggle reveals pre with traceback text", () => {
    const tracebackText = "Traceback (most recent call last):\n  File test.py, line 1";
    const err = createHandlerError({ error_traceback: tracebackText });
    const { container, getByRole } = render(<ErrorFeed errors={[err]} />);

    // No <pre> element initially
    expect(container.querySelector("pre.ht-traceback")).toBeNull();

    // Click toggle
    const button = getByRole("button", { name: /traceback/i });
    fireEvent.click(button);

    // <pre> with traceback should now be visible
    const pre = container.querySelector("pre.ht-traceback");
    expect(pre).not.toBeNull();
    expect(pre!.textContent).toContain("Traceback (most recent call last)");
  });

  it("framework error with null listener_id does not render 'deleted handler'", () => {
    const err = createHandlerError({
      app_key: "__hassette__.service_watcher",
      listener_id: null as unknown as number,
      source_tier: "framework",
    });
    const { queryByText, getByText } = render(<ErrorFeed errors={[err]} />);
    expect(queryByText("deleted handler")).toBeNull();
    expect(getByText("Service Watcher")).toBeDefined();
  });

  it("framework error with null listener_id shows '(unregistered)' suffix", () => {
    const err = createHandlerError({
      app_key: "__hassette__.service_watcher",
      listener_id: null as unknown as number,
      handler_method: "restart_service",
      source_tier: "framework",
    });
    const { getByText } = render(<ErrorFeed errors={[err]} />);
    expect(getByText("restart_service (unregistered)")).toBeDefined();
  });

  it("framework error with null handler_method and null listener_id shows '(unregistered)'", () => {
    const err = createHandlerError({
      app_key: "__hassette__.service_watcher",
      listener_id: null as unknown as number,
      handler_method: null as unknown as string,
      source_tier: "framework",
    });
    const { getByText } = render(<ErrorFeed errors={[err]} />);
    expect(getByText("(unregistered)")).toBeDefined();
  });

  it("framework job error with null job_id does not render 'deleted job'", () => {
    const err = createJobError({
      app_key: "__hassette__.scheduler_service",
      job_id: null as unknown as number,
      source_tier: "framework",
    });
    const { queryByText } = render(<ErrorFeed errors={[err]} />);
    expect(queryByText("deleted job")).toBeNull();
  });

  it("test_unified_feed_includes_both_tiers: renders both app and framework errors", () => {
    const appErr = createHandlerError({ app_key: "my_app", source_tier: "app" });
    const fwErr = createHandlerError({ app_key: "__hassette__.core", source_tier: "framework", listener_id: 99 });
    const { getByText } = render(<ErrorFeed errors={[appErr, fwErr]} />);

    // App error renders as link
    expect(getByText("my_app").tagName.toLowerCase()).toBe("a");
    // Framework error renders as span (no links for framework)
    expect(getByText("Core")).toBeDefined();
    // Both Framework badges appear
    expect(getByText("Framework")).toBeDefined();
  });
});
