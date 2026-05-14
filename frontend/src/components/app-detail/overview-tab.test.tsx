import { describe, expect, it, vi } from "vitest";
import { fireEvent, waitFor } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { http, HttpResponse } from "msw";
import { OverviewTab } from "./overview-tab";
import { createListener, createJob, createLogEntry } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import type { components } from "../../api/generated-types";

type ActivityFeedEntry = components["schemas"]["ActivityFeedEntry"];

// Overview tab tests are split into two groups:
//  1. Props-only tests (error spotlight, health grid) — no context needed
//  2. API-driven tests (activity, logs, real-time) — require AppStateContext + MSW
// MSW server lifecycle is managed globally in src/test-setup.ts.

// Suppress wouter's missing Router context warning for link rendering
vi.mock("wouter", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: preact.ComponentChildren; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
  useSearch: () => "",
  useLocation: () => ["/", () => {}],
}));

function renderOverviewTab({
  listeners = [createListener()],
  jobs = [createJob()],
  appKey = "test_app",
  instanceQs = "",
  resolvedInstanceIndex = 0,
} = {}) {
  return renderWithAppState(
    <OverviewTab
      listeners={listeners}
      jobs={jobs}
      appKey={appKey}
      instanceQs={instanceQs}
      resolvedInstanceIndex={resolvedInstanceIndex}
    />,
    { stateOverrides: { uptimeSeconds: signal<number | null>(120) } },
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Error Spotlight
// ──────────────────────────────────────────────────────────────────────────────

describe("OverviewTab — Error Spotlight", () => {
  it("is absent when no listeners or jobs are failing", () => {
    const { queryByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 1, failed: 0, timed_out: 0 })],
      jobs: [createJob({ job_id: 1, failed: 0, timed_out: 0 })],
    });
    expect(queryByTestId("overview-error-spotlight")).toBeNull();
  });

  it("renders when a listener has failures", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 1, failed: 2, last_error_type: "KeyError", last_error_message: "missing key" })],
      jobs: [],
    });
    expect(getByTestId("overview-error-spotlight")).toBeDefined();
  });

  it("renders when a listener has timeouts", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 1, timed_out: 1 })],
      jobs: [],
    });
    expect(getByTestId("overview-error-spotlight")).toBeDefined();
  });

  it("renders when a job has failures", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [],
      jobs: [createJob({ job_id: 5, failed: 1, last_error_type: "RuntimeError", last_error_message: "crashed" })],
    });
    expect(getByTestId("overview-error-spotlight")).toBeDefined();
  });

  it("renders when a job has timeouts", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [],
      jobs: [createJob({ job_id: 5, timed_out: 1 })],
    });
    expect(getByTestId("overview-error-spotlight")).toBeDefined();
  });

  it("shows error type and message for failing listener", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [
        createListener({
          listener_id: 1,
          failed: 1,
          last_error_type: "KeyError",
          last_error_message: "missing key 'state'",
        }),
      ],
      jobs: [],
    });
    const spotlight = getByTestId("overview-error-spotlight");
    expect(spotlight.textContent).toContain("KeyError");
    expect(spotlight.textContent).toContain("missing key 'state'");
  });

  it("shows error type and message for failing job", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [],
      jobs: [
        createJob({
          job_id: 5,
          failed: 1,
          last_error_type: "RuntimeError",
          last_error_message: "division by zero",
        }),
      ],
    });
    const spotlight = getByTestId("overview-error-spotlight");
    expect(spotlight.textContent).toContain("RuntimeError");
    expect(spotlight.textContent).toContain("division by zero");
  });

  it("shows max 3 entries expanded when 3 or fewer are failing", () => {
    const listeners = [
      createListener({ listener_id: 1, failed: 1 }),
      createListener({ listener_id: 2, failed: 1 }),
      createListener({ listener_id: 3, failed: 1 }),
    ];
    const { getAllByTestId, queryByTestId } = renderOverviewTab({ listeners, jobs: [] });
    expect(getAllByTestId(/^overview-spotlight-entry-/).length).toBe(3);
    expect(queryByTestId("overview-spotlight-show-more")).toBeNull();
  });

  it("shows 3 expanded entries and a 'show N more' button when more than 3 are failing", () => {
    const listeners = [
      createListener({ listener_id: 1, failed: 1 }),
      createListener({ listener_id: 2, failed: 1 }),
      createListener({ listener_id: 3, failed: 1 }),
      createListener({ listener_id: 4, failed: 1 }),
      createListener({ listener_id: 5, failed: 1 }),
    ];
    const { getAllByTestId, getByTestId } = renderOverviewTab({ listeners, jobs: [] });
    // Initially only 3 visible
    expect(getAllByTestId(/^overview-spotlight-entry-/).length).toBe(3);
    const btn = getByTestId("overview-spotlight-show-more");
    expect(btn.textContent).toContain("2");
  });

  it("expands remaining entries when 'show N more' is clicked", () => {
    const listeners = [
      createListener({ listener_id: 1, failed: 1 }),
      createListener({ listener_id: 2, failed: 1 }),
      createListener({ listener_id: 3, failed: 1 }),
      createListener({ listener_id: 4, failed: 1 }),
    ];
    const { getAllByTestId, getByTestId } = renderOverviewTab({ listeners, jobs: [] });
    expect(getAllByTestId(/^overview-spotlight-entry-/).length).toBe(3);
    fireEvent.click(getByTestId("overview-spotlight-show-more"));
    expect(getAllByTestId(/^overview-spotlight-entry-/).length).toBe(4);
  });

  it("links failing listener entry to handlers tab with correct listener ID", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 7, failed: 1 })],
      jobs: [],
      appKey: "my_app",
      instanceQs: "",
    });
    const entry = getByTestId("overview-spotlight-entry-listener-7");
    const anchor = entry.querySelector("a");
    expect(anchor).not.toBeNull();
    expect(anchor!.getAttribute("href")).toBe("/apps/my_app/handlers/h-7");
  });

  it("links failing job entry to handlers tab with correct job ID", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [],
      jobs: [createJob({ job_id: 20, failed: 1 })],
      appKey: "my_app",
      instanceQs: "",
    });
    const entry = getByTestId("overview-spotlight-entry-job-20");
    const anchor = entry.querySelector("a");
    expect(anchor).not.toBeNull();
    expect(anchor!.getAttribute("href")).toBe("/apps/my_app/handlers/j-20");
  });

  it("links entry includes instanceQs when provided", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 3, failed: 1 })],
      jobs: [],
      appKey: "test_app",
      instanceQs: "?instance=1",
    });
    const entry = getByTestId("overview-spotlight-entry-listener-3");
    const anchor = entry.querySelector("a");
    expect(anchor!.getAttribute("href")).toBe("/apps/test_app/handlers/h-3?instance=1");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Handler Health Grid
// ──────────────────────────────────────────────────────────────────────────────

describe("OverviewTab — Handler Health Grid", () => {
  it("renders the health grid section", () => {
    const { getByTestId } = renderOverviewTab();
    expect(getByTestId("overview-health-grid")).toBeDefined();
  });

  it("renders a row for each listener", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [
        createListener({ listener_id: 1 }),
        createListener({ listener_id: 2 }),
      ],
      jobs: [],
    });
    expect(getByTestId("overview-health-row-listener-1")).toBeDefined();
    expect(getByTestId("overview-health-row-listener-2")).toBeDefined();
  });

  it("renders a row for each job", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [],
      jobs: [
        createJob({ job_id: 10 }),
        createJob({ job_id: 11 }),
      ],
    });
    expect(getByTestId("overview-health-row-job-10")).toBeDefined();
    expect(getByTestId("overview-health-row-job-11")).toBeDefined();
  });

  it("renders rows for both listeners and jobs", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 1 })],
      jobs: [createJob({ job_id: 5 })],
    });
    expect(getByTestId("overview-health-row-listener-1")).toBeDefined();
    expect(getByTestId("overview-health-row-job-5")).toBeDefined();
  });

  it("shows empty state when no listeners or jobs", () => {
    const { getByTestId } = renderOverviewTab({ listeners: [], jobs: [] });
    expect(getByTestId("overview-health-empty")).toBeDefined();
  });

  it("orders failing items first in the health grid", () => {
    const listeners = [
      createListener({ listener_id: 1, failed: 0, timed_out: 0 }),
      createListener({ listener_id: 2, failed: 3, timed_out: 0 }),
    ];
    const { container } = renderOverviewTab({ listeners, jobs: [] });
    const rows = container.querySelectorAll("[data-testid^='overview-health-row-']");
    // The failing listener (id=2) should appear first
    expect(rows[0].getAttribute("data-testid")).toBe("overview-health-row-listener-2");
    expect(rows[1].getAttribute("data-testid")).toBe("overview-health-row-listener-1");
  });

  it("orders timed-out items before healthy items", () => {
    const listeners = [
      createListener({ listener_id: 1, failed: 0, timed_out: 0 }),
      createListener({ listener_id: 2, failed: 0, timed_out: 1 }),
    ];
    const { container } = renderOverviewTab({ listeners, jobs: [] });
    const rows = container.querySelectorAll("[data-testid^='overview-health-row-']");
    expect(rows[0].getAttribute("data-testid")).toBe("overview-health-row-listener-2");
    expect(rows[1].getAttribute("data-testid")).toBe("overview-health-row-listener-1");
  });

  it("each health grid row links to handlers tab with correct listener ID", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 4 })],
      jobs: [],
      appKey: "my_app",
      instanceQs: "",
    });
    const row = getByTestId("overview-health-row-listener-4");
    const anchor = row.tagName === "A" ? row : row.querySelector("a");
    const href = anchor?.getAttribute("href") ?? row.getAttribute("href");
    expect(href).toBe("/apps/my_app/handlers/h-4");
  });

  it("each health grid row links to handlers tab with correct job ID", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [],
      jobs: [createJob({ job_id: 15 })],
      appKey: "my_app",
      instanceQs: "",
    });
    const row = getByTestId("overview-health-row-job-15");
    const anchor = row.tagName === "A" ? row : row.querySelector("a");
    const href = anchor?.getAttribute("href") ?? row.getAttribute("href");
    expect(href).toBe("/apps/my_app/handlers/j-15");
  });

  it("health grid row link includes instanceQs", () => {
    const { getByTestId } = renderOverviewTab({
      listeners: [createListener({ listener_id: 6 })],
      jobs: [],
      appKey: "test_app",
      instanceQs: "?instance=2",
    });
    const row = getByTestId("overview-health-row-listener-6");
    const anchor = row.tagName === "A" ? row : row.querySelector("a");
    const href = anchor?.getAttribute("href") ?? row.getAttribute("href");
    expect(href).toBe("/apps/test_app/handlers/h-6?instance=2");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Recent Activity Section
// ──────────────────────────────────────────────────────────────────────────────

describe("OverviewTab — Recent Activity", () => {
  it("renders activity data from the endpoint", async () => {
    const entries: ActivityFeedEntry[] = [
      {
        row_id: "h-1",
        status: "success",
        timestamp: 1700000100,
        app_key: "test_app",
        handler_name: "on_motion",
        duration_ms: 42,
        error_type: null,
        kind: "handler",
      },
    ];
    server.use(
      http.get("/api/telemetry/app/:app_key/activity", () =>
        HttpResponse.json<ActivityFeedEntry[]>(entries),
      ),
    );

    const { getByTestId } = renderOverviewTab({ appKey: "test_app" });
    await waitFor(() => {
      expect(getByTestId("overview-activity-section")).toBeDefined();
    });
    const section = getByTestId("overview-activity-section");
    await waitFor(() => {
      expect(section.textContent).toContain("on_motion");
    });
  });

  it("renders empty state when activity endpoint returns no entries", async () => {
    server.use(
      http.get("/api/telemetry/app/:app_key/activity", () =>
        HttpResponse.json<ActivityFeedEntry[]>([]),
      ),
    );

    const { getByTestId } = renderOverviewTab({ appKey: "test_app" });
    await waitFor(() => {
      expect(getByTestId("overview-activity-empty")).toBeDefined();
    });
  });

  it("shows status shape, handler name, duration, and relative time per row", async () => {
    const entries: ActivityFeedEntry[] = [
      {
        row_id: "h-2",
        status: "error",
        timestamp: 1700000200,
        app_key: "test_app",
        handler_name: "on_door_open",
        duration_ms: 155,
        error_type: "ValueError",
        kind: "handler",
      },
    ];
    server.use(
      http.get("/api/telemetry/app/:app_key/activity", () =>
        HttpResponse.json<ActivityFeedEntry[]>(entries),
      ),
    );

    const { getByTestId } = renderOverviewTab({ appKey: "test_app" });
    await waitFor(() => {
      const section = getByTestId("overview-activity-section");
      expect(section.textContent).toContain("on_door_open");
      expect(section.textContent).toContain("155");
    });
  });

  it("groups consecutive same-handler same-status entries", async () => {
    const entries: ActivityFeedEntry[] = [
      { row_id: "r1", status: "success", timestamp: 1700000300, app_key: "test_app", handler_name: "check", duration_ms: 10, error_type: null, kind: "job" },
      { row_id: "r2", status: "success", timestamp: 1700000200, app_key: "test_app", handler_name: "check", duration_ms: 20, error_type: null, kind: "job" },
      { row_id: "r3", status: "success", timestamp: 1700000100, app_key: "test_app", handler_name: "check", duration_ms: 30, error_type: null, kind: "job" },
      { row_id: "r4", status: "error",   timestamp: 1700000050, app_key: "test_app", handler_name: "on_event", duration_ms: 5, error_type: "ValueError", kind: "handler" },
      { row_id: "r5", status: "success", timestamp: 1700000000, app_key: "test_app", handler_name: "check", duration_ms: 15, error_type: null, kind: "job" },
    ];
    server.use(
      http.get("/api/telemetry/app/:app_key/activity", () =>
        HttpResponse.json<ActivityFeedEntry[]>(entries),
      ),
    );

    const { getByTestId, getAllByTestId } = renderOverviewTab({ appKey: "test_app" });
    await waitFor(() => {
      const rows = getAllByTestId("overview-activity-row");
      expect(rows.length).toBe(3);
    });
    const section = getByTestId("overview-activity-section");
    expect(section.textContent).toContain("× 3");
    expect(section.textContent).toContain("on_event");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Recent Logs Section
// ──────────────────────────────────────────────────────────────────────────────

describe("OverviewTab — Recent Logs", () => {
  it("renders recent log entries for the app", async () => {
    const logs = [
      createLogEntry({ seq: 10, app_key: "test_app", level: "INFO", message: "handler fired" }),
      createLogEntry({ seq: 11, app_key: "test_app", level: "ERROR", message: "something went wrong" }),
    ];
    server.use(
      http.get("/api/logs/recent", () => HttpResponse.json(logs)),
    );

    const { getByTestId } = renderOverviewTab({ appKey: "test_app" });
    await waitFor(() => {
      expect(getByTestId("overview-logs-section")).toBeDefined();
    });
    const section = getByTestId("overview-logs-section");
    await waitFor(() => {
      expect(section.textContent).toContain("handler fired");
    });
  });

  it("renders empty state when logs endpoint returns no entries", async () => {
    server.use(
      http.get("/api/logs/recent", () => HttpResponse.json([])),
    );

    const { getByTestId } = renderOverviewTab({ appKey: "test_app" });
    await waitFor(() => {
      const section = getByTestId("overview-logs-section");
      expect(section.textContent).toContain("no log lines in window");
    });
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Real-Time Updates
// ──────────────────────────────────────────────────────────────────────────────

describe("OverviewTab — Real-time refetch", () => {
  it("refetches activity when invocationCompleted signal changes with matching app_key", async () => {
    let fetchCount = 0;
    server.use(
      http.get("/api/telemetry/app/:app_key/activity", () => {
        fetchCount++;
        return HttpResponse.json<ActivityFeedEntry[]>([]);
      }),
    );

    const invocationCompleted = signal<Array<{ listener_id: number; app_key: string; instance_index: number; status: string; duration_ms: number; error_type: string | null }> | null>(null);

    renderWithAppState(
      <OverviewTab
        listeners={[]}
        jobs={[]}
        appKey="test_app"
        instanceQs=""
        resolvedInstanceIndex={0}
      />,
      { stateOverrides: {
        uptimeSeconds: signal<number | null>(120),
        invocationCompleted,
      }},
    );

    // Wait for initial fetch
    await waitFor(() => expect(fetchCount).toBeGreaterThan(0));
    const countAfterMount = fetchCount;

    // Simulate a matching WebSocket event
    invocationCompleted.value = [{ listener_id: 1, app_key: "test_app", instance_index: 0, status: "success", duration_ms: 10, error_type: null }];

    // The debounced effect fires after 500ms — use waitFor with longer timeout
    await waitFor(() => expect(fetchCount).toBeGreaterThan(countAfterMount), { timeout: 1500 });
  });

  it("does not refetch when invocationCompleted events are for a different app_key", async () => {
    let fetchCount = 0;
    server.use(
      http.get("/api/telemetry/app/:app_key/activity", () => {
        fetchCount++;
        return HttpResponse.json<ActivityFeedEntry[]>([]);
      }),
    );

    const invocationCompleted = signal<Array<{ listener_id: number; app_key: string; instance_index: number; status: string; duration_ms: number; error_type: string | null }> | null>(null);

    renderWithAppState(
      <OverviewTab
        listeners={[]}
        jobs={[]}
        appKey="test_app"
        instanceQs=""
        resolvedInstanceIndex={0}
      />,
      { stateOverrides: {
        uptimeSeconds: signal<number | null>(120),
        invocationCompleted,
      }},
    );

    await waitFor(() => expect(fetchCount).toBeGreaterThan(0));
    const countAfterMount = fetchCount;

    // Event for a different app — should not trigger refetch
    invocationCompleted.value = [{ listener_id: 99, app_key: "other_app", instance_index: 0, status: "success", duration_ms: 5, error_type: null }];

    // Wait a moment and confirm count did not increase
    await new Promise((r) => setTimeout(r, 700));
    expect(fetchCount).toBe(countAfterMount);
  });

  it("refetches activity when executionCompleted signal changes with matching app_key", async () => {
    let fetchCount = 0;
    server.use(
      http.get("/api/telemetry/app/:app_key/activity", () => {
        fetchCount++;
        return HttpResponse.json<ActivityFeedEntry[]>([]);
      }),
    );

    const executionCompleted = signal<Array<{ job_id: number; app_key: string; instance_index: number; status: string; duration_ms: number; error_type: string | null }> | null>(null);

    renderWithAppState(
      <OverviewTab
        listeners={[]}
        jobs={[]}
        appKey="test_app"
        instanceQs=""
        resolvedInstanceIndex={0}
      />,
      { stateOverrides: {
        uptimeSeconds: signal<number | null>(120),
        executionCompleted,
      }},
    );

    await waitFor(() => expect(fetchCount).toBeGreaterThan(0));
    const countAfterMount = fetchCount;

    executionCompleted.value = [{ job_id: 5, app_key: "test_app", instance_index: 0, status: "success", duration_ms: 20, error_type: null }];

    await waitFor(() => expect(fetchCount).toBeGreaterThan(countAfterMount), { timeout: 1500 });
  });
});
