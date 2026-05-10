import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { OverviewTab } from "./overview-tab";
import { createListener, createJob } from "../../test/factories";

// Overview tab does not call useScopedApi or useAppState — no context needed.
// It receives listeners/jobs as props and renders links (not buttons with state).

// Suppress wouter's missing Router context warning for link rendering
vi.mock("wouter", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: preact.ComponentChildren; [k: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

function renderOverviewTab({
  listeners = [createListener()],
  jobs = [createJob()],
  appKey = "test_app",
  instanceQs = "",
} = {}) {
  return render(
    <OverviewTab
      listeners={listeners}
      jobs={jobs}
      appKey={appKey}
      instanceQs={instanceQs}
    />,
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
