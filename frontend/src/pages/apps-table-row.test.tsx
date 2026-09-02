import { within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type AppStatusEntry, appStatusKey } from "../state/store";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import type { AppRow } from "../utils/app-data";
import { INACTIVE_STATUSES } from "../utils/status";
import { AppTableRow } from "./apps-table-row";

vi.mock("wouter", () => createWouterMock());

vi.mock("../components/shared/action-buttons", () => ({
  ActionButtons: (props: { confirmStop?: boolean; instance?: { index: number; name: string } }) => (
    <div
      data-testid="action-buttons"
      data-confirm-stop={props.confirmStop ? "true" : "false"}
      data-instance={props.instance ? JSON.stringify(props.instance) : ""}
    />
  ),
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
    in_current_config: true,
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
  const defaults = { app: createAppRow(), appStatuses: {}, isExpanded: false, onToggle: vi.fn() };
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

  it("shows display_name as the link text", () => {
    const { getByRole } = renderRow({
      app: createAppRow({ app_key: "examples.security_monitor.SecurityMonitor", display_name: "SecurityMonitor" }),
    });
    const link = getByRole("link", { name: "SecurityMonitor" });
    expect(link).toBeDefined();
    expect(link.textContent).toBe("SecurityMonitor");
    expect((link as HTMLAnchorElement).href).toContain("/apps/examples.security_monitor.SecurityMonitor");
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

  it("clicking error cell toggles aria-label to Collapse", async () => {
    const user = userEvent.setup();
    const { getAllByRole } = renderRow({
      app: createAppRow({ error_message: "Boom" }),
    });
    const buttons = getAllByRole("button");
    const errorCell = buttons.find((el) =>
      el.getAttribute("aria-label")?.toLowerCase().includes("error"),
    ) as HTMLElement;

    expect(errorCell.getAttribute("aria-label")).toMatch(/^expand error/i);
    await user.click(errorCell);
    expect(errorCell.getAttribute("aria-label")).toMatch(/^collapse error/i);
  });

  it("appStatuses overrides app.status in the badge", () => {
    const entry: AppStatusEntry = { status: "running", index: 0 };
    const { getByTestId } = renderRow({
      app: createAppRow({ app_key: "my_app", status: "stopped" }),
      appStatuses: { [appStatusKey("my_app", 0)]: entry },
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

  it("calls onToggle when expand button is clicked", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const { getByTestId } = renderRow({
      app: createAppRow({ instance_count: 2 }),
      onToggle,
    });
    await user.click(getByTestId("app-row-expand"));
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

  it("expanded instance rows show per-instance live status", () => {
    const app = createAppRow({
      app_key: "my_app",
      instance_count: 2,
      instances: [
        {
          app_key: "my_app",
          class_name: "MyApp",
          index: 0,
          instance_name: "my_app[0]",
          status: "stopped",
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
    const appStatuses: Record<string, AppStatusEntry> = {
      [appStatusKey("my_app", 0)]: { status: "running", index: 0 },
      [appStatusKey("my_app", 1)]: { status: "failed", index: 1 },
    };
    const { getByTestId } = renderRow({ app, appStatuses, isExpanded: true });
    const row0 = getByTestId("instance-row-my_app-0");
    const row1 = getByTestId("instance-row-my_app-1");
    expect(row0.textContent).toContain("running");
    expect(row0.textContent).not.toContain("stopped");
    expect(row1.textContent).toContain("failed");
    expect(row1.textContent).not.toContain("stopped");
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

  it("shows 'removed' chip when in_current_config is false", () => {
    const { getByText } = renderRow({ app: createAppRow({ in_current_config: false }) });
    expect(getByText("removed")).toBeDefined();
  });

  it("does not show 'removed' chip when in_current_config is true", () => {
    const { queryByText } = renderRow({ app: createAppRow({ in_current_config: true }) });
    expect(queryByText("removed")).toBeNull();
  });

  describe("dimmed styling for inactive statuses", () => {
    // "shutting_down" and "unknown" can no longer reach `AppRow.status` (typed to the backend's
    // `ManifestStatus`) — they only exist in INACTIVE_STATUSES for backwards-compat matching
    // against live-status values (`ManifestStatus | ResourceStatus`), neither of which includes
    // them either. See design/specs/102-status-exhaustiveness-enforcement.
    const manifestInactiveStatuses = [...INACTIVE_STATUSES].filter(
      (s): s is AppRow["status"] => s !== "shutting_down" && s !== "unknown",
    );
    for (const status of manifestInactiveStatuses) {
      it(`marks status "${status}" as inactive`, () => {
        const { getByTestId } = renderRow({ app: createAppRow({ status }) });
        const row = getByTestId(`app-row-my_app`);
        expect(row.getAttribute("data-state")).toBe("inactive");
      });
    }

    it("marks active status 'running' as active", () => {
      const { getByTestId } = renderRow({ app: createAppRow({ status: "running" }) });
      const row = getByTestId("app-row-my_app");
      expect(row.getAttribute("data-state")).toBe("active");
    });
  });

  describe("ActionButtons instance/confirmStop wiring", () => {
    it("app-level row passes confirmStop but does not pass instance", () => {
      const { getByTestId } = renderRow({ app: createAppRow({ instance_count: 1 }) });
      const actionButtons = getByTestId("action-buttons");
      expect(actionButtons.getAttribute("data-confirm-stop")).toBe("true");
      expect(actionButtons.getAttribute("data-instance")).toBe("");
    });

    it("instance sub-rows pass instance and confirmStop to ActionButtons", () => {
      const app = createAppRow({
        app_key: "my_app",
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

      const row0 = getByTestId("instance-row-my_app-0");
      const actionButtons0 = within(row0).getByTestId("action-buttons");
      expect(actionButtons0.getAttribute("data-confirm-stop")).toBe("true");
      expect(actionButtons0.getAttribute("data-instance")).toBe(JSON.stringify({ index: 0, name: "my_app[0]" }));

      const row1 = getByTestId("instance-row-my_app-1");
      const actionButtons1 = within(row1).getByTestId("action-buttons");
      expect(actionButtons1.getAttribute("data-confirm-stop")).toBe("true");
      expect(actionButtons1.getAttribute("data-instance")).toBe(JSON.stringify({ index: 1, name: "my_app[1]" }));
    });
  });
});
