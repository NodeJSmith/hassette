import { fireEvent } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { renderWithAppState } from "../test/render-helpers";
import type { AppRow } from "../utils/app-data";
import { INACTIVE_STATUSES } from "../utils/status";
import { AppTableRow } from "./apps-table-row";

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

vi.mock("../components/shared/action-buttons", () => ({
  ActionButtons: () => <div data-testid="action-buttons" />,
}));

vi.mock("../components/shared/mini-sparkline", () => ({
  MiniSparkline: () => <svg data-testid="mini-sparkline" />,
}));

function createAppRow(overrides: Partial<AppRow> = {}): AppRow {
  return {
    app_key: "my_app",
    class_name: "MyApp",
    display_name: "My App",
    filename: "my_app.py",
    status: "running",
    block_reason: null,
    enabled: true,
    auto_loaded: false,
    autostart: true,
    instance_count: 1,
    instances: [],
    error_message: null,
    handler_count: 3,
    job_count: 1,
    total_invocations: 100,
    total_executions: 50,
    total_errors: 2,
    total_timed_out: 0,
    total_job_errors: 0,
    total_job_timed_out: 0,
    error_rate: 0.02,
    last_activity_ts: null,
    activity_buckets: [],
    last_error_message: null,
    last_error_type: null,
    last_error_ts: null,
    ...overrides,
  };
}

function renderRow(props: Partial<Parameters<typeof AppTableRow>[0]> = {}) {
  const defaults = { app: createAppRow(), isExpanded: false, onToggle: vi.fn() };
  return renderWithAppState(
    <table>
      <tbody>
        <AppTableRow {...defaults} {...props} />
      </tbody>
    </table>,
  );
}

describe("AppTableRow", () => {
  it("renders data-testid based on app_key", () => {
    const { getByTestId } = renderRow({ app: createAppRow({ app_key: "motion_lights" }) });
    expect(getByTestId("app-row-motion_lights")).toBeDefined();
  });

  it("shows app name as a link", () => {
    const { getByRole } = renderRow({ app: createAppRow({ app_key: "my_app" }) });
    const link = getByRole("link", { name: /my_app/i });
    expect(link).toBeDefined();
    expect((link as HTMLAnchorElement).href).toContain("/apps/my_app");
  });

  it("shows class_name", () => {
    const { getByText } = renderRow({ app: createAppRow({ class_name: "MotionLightsApp" }) });
    expect(getByText("MotionLightsApp")).toBeDefined();
  });

  it("shows status badge with the status text", () => {
    const { getByTestId } = renderRow({ app: createAppRow({ status: "running" }) });
    expect(getByTestId("status-pill").textContent).toBe("running");
  });

  it("shows 'auto' chip when auto_loaded is true", () => {
    const { getByText } = renderRow({ app: createAppRow({ auto_loaded: true }) });
    expect(getByText("auto")).toBeDefined();
  });

  it("does not show 'auto' chip when auto_loaded is false", () => {
    const { queryByText } = renderRow({ app: createAppRow({ auto_loaded: false }) });
    expect(queryByText("auto")).toBeNull();
  });

  it("shows total runs as sum of invocations and executions", () => {
    const { getByText } = renderRow({
      app: createAppRow({ total_invocations: 80, total_executions: 20 }),
    });
    expect(getByText("100")).toBeDefined();
  });

  it("shows em dash when error_message is null", () => {
    const { getAllByText } = renderRow({ app: createAppRow({ error_message: null }) });
    // "—" also appears in last_activity cell; at least one instance expected
    expect(getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows error message text when present", () => {
    const { getByText } = renderRow({
      app: createAppRow({ error_message: "Something went wrong" }),
    });
    expect(getByText(/something went wrong/i)).toBeDefined();
  });

  it("error cell has role='button' when error_message is present", () => {
    const { getAllByRole } = renderRow({
      app: createAppRow({ error_message: "Boom" }),
    });
    const buttons = getAllByRole("button");
    const errorCell = buttons.find((el) => el.getAttribute("aria-label")?.includes("error"));
    expect(errorCell).toBeDefined();
  });

  it("error cell has no role='button' when error_message is null", () => {
    const { queryByRole } = renderRow({ app: createAppRow({ error_message: null }) });
    // Only button present would be from ActionButtons (mocked) or expand button
    const errorBtn = queryByRole("button", { name: /error/i });
    expect(errorBtn).toBeNull();
  });

  it("clicking error cell toggles aria-label to Collapse", () => {
    const { getAllByRole } = renderRow({
      app: createAppRow({ error_message: "Boom" }),
    });
    const buttons = getAllByRole("button");
    const errorCell = buttons.find((el) =>
      el.getAttribute("aria-label")?.toLowerCase().includes("error"),
    ) as HTMLElement;

    expect(errorCell.getAttribute("aria-label")).toMatch(/^expand error/i);
    fireEvent.click(errorCell);
    expect(errorCell.getAttribute("aria-label")).toMatch(/^collapse error/i);
  });

  it("liveStatus overrides app.status in the badge", () => {
    const { getByTestId } = renderRow({
      app: createAppRow({ status: "stopped" }),
      liveStatus: "running",
    });
    expect(getByTestId("status-pill").textContent).toBe("running");
  });

  it("shows expand button when instance_count > 1", () => {
    const { getByTestId } = renderRow({
      app: createAppRow({ instance_count: 2 }),
    });
    expect(getByTestId("app-row-expand")).toBeDefined();
  });

  it("does not show expand button when instance_count === 1", () => {
    const { queryByTestId } = renderRow({
      app: createAppRow({ instance_count: 1 }),
    });
    expect(queryByTestId("app-row-expand")).toBeNull();
  });

  it("calls onToggle when expand button is clicked", () => {
    const onToggle = vi.fn();
    const { getByTestId } = renderRow({
      app: createAppRow({ instance_count: 2 }),
      onToggle,
    });
    fireEvent.click(getByTestId("app-row-expand"));
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("shows instance rows when isExpanded and instance_count > 1", () => {
    const app = createAppRow({
      instance_count: 2,
      instances: [
        {
          app_key: "my_app",
          class_name: "MyApp",
          index: 0,
          instance_name: "my_app[0]",
          status: "running",
          error_message: null,
        },
        {
          app_key: "my_app",
          class_name: "MyApp",
          index: 1,
          instance_name: "my_app[1]",
          status: "stopped",
          error_message: null,
        },
      ],
    });
    const { getByTestId } = renderRow({ app, isExpanded: true });
    expect(getByTestId("instance-row-my_app-0")).toBeDefined();
    expect(getByTestId("instance-row-my_app-1")).toBeDefined();
  });

  it("does not show instance rows when isExpanded is false", () => {
    const app = createAppRow({
      instance_count: 2,
      instances: [
        {
          app_key: "my_app",
          class_name: "MyApp",
          index: 0,
          instance_name: "my_app[0]",
          status: "running",
          error_message: null,
        },
      ],
    });
    const { queryByTestId } = renderRow({ app, isExpanded: false });
    expect(queryByTestId("instance-row-my_app-0")).toBeNull();
  });

  it("shows instance count text when multi-instance", () => {
    const { getByText } = renderRow({
      app: createAppRow({ instance_count: 3 }),
    });
    expect(getByText(/3 instances/i)).toBeDefined();
  });

  it("shows 'no autostart' chip when autostart is false", () => {
    const { getByText } = renderRow({ app: createAppRow({ autostart: false }) });
    expect(getByText("no autostart")).toBeDefined();
  });

  it("does not show 'no autostart' chip when autostart is true", () => {
    const { queryByText } = renderRow({ app: createAppRow({ autostart: true }) });
    expect(queryByText("no autostart")).toBeNull();
  });

  describe("dimmed styling for inactive statuses", () => {
    for (const status of INACTIVE_STATUSES) {
      it(`applies dimmed class for status "${status}"`, () => {
        const { getByTestId } = renderRow({ app: createAppRow({ status }) });
        const row = getByTestId(`app-row-my_app`);
        // The row element receives the rowDimmed CSS module class when inactive.
        // In jsdom with CSS Modules, module class names are hashed; we verify
        // the element has more than one class (base + dimmed), not the literal name.
        const classes = row.className.split(/\s+/).filter(Boolean);
        expect(classes.length).toBeGreaterThan(1);
      });
    }

    it("does not apply extra dimmed class for active status 'running'", () => {
      const { getByTestId } = renderRow({ app: createAppRow({ status: "running" }) });
      const row = getByTestId("app-row-my_app");
      const classes = row.className.split(/\s+/).filter(Boolean);
      // Only the base row class — no dimmed class
      expect(classes.length).toBe(1);
    });
  });
});
