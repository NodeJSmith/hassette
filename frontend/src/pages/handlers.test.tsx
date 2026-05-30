import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createJob, createListener } from "../test/factories";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
import { HandlersPage } from "./handlers";

// Mutable search string for tests that need to control query params
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/handlers", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

// State overrides shared across all tests — uptimeSeconds must be non-null so
// useScopedQuery fires for the "since-restart" preset.
const stateOverrides = { uptimeSeconds: signal(120) };

describe("HandlersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
  });

  it("shows the page heading", async () => {
    const { findByRole } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect(await findByRole("heading", { name: /handlers/i })).toBeDefined();
  });

  it("shows empty state when no handlers or jobs", async () => {
    const { findByText } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect(await findByText(/no handlers found/i)).toBeDefined();
  });

  it("renders both handler and job rows in a single table", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        ]),
      ),
      http.get("/api/scheduler/jobs", () =>
        HttpResponse.json([createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" })]),
      ),
    );
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
    expect((await findAllByTestId(/job-row-/)).length).toBe(1);
  });

  it("filters out framework-tier items by default", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
          createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
        ]),
      ),
      http.get("/api/scheduler/jobs", () =>
        HttpResponse.json([
          createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" }),
          createJob({ job_id: 11, app_key: "fw_app", job_name: "fw_job", source_tier: "framework" }),
        ]),
      ),
    );
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
    expect((await findAllByTestId(/job-row-/)).length).toBe(1);
  });

  it("filters by selected app when ?app=app_a is in URL", async () => {
    mockSearch = "app=app_a";
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
          createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_change", source_tier: "app" }),
        ]),
      ),
      http.get("/api/scheduler/jobs", () =>
        HttpResponse.json([createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" })]),
      ),
    );
    const { findAllByTestId, queryAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
    expect((await findAllByTestId(/job-row-/)).length).toBe(1);
    // app_b listener should be excluded
    expect(queryAllByTestId("listener-row-listener/2")).toHaveLength(0);
  });

  it("renders a search input above the table", async () => {
    const { findByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    const search = await findByTestId("handlers-search");
    expect(search).toBeDefined();
  });

  it("search filters by handler name when ?search= is in URL", async () => {
    mockSearch = "search=motion";
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({
            listener_id: 1,
            app_key: "app_a",
            handler_method: "on_motion_detected",
            source_tier: "app",
          }),
          createListener({
            listener_id: 2,
            app_key: "app_b",
            handler_method: "on_temperature_change",
            source_tier: "app",
          }),
        ]),
      ),
    );
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
  });

  it("search filters by app_key when ?search= is in URL", async () => {
    mockSearch = "search=climate";
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "climate_app", handler_method: "on_event", source_tier: "app" }),
          createListener({ listener_id: 2, app_key: "alarm_app", handler_method: "on_event", source_tier: "app" }),
        ]),
      ),
    );
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
  });

  it("search is case-insensitive when ?search= is in URL", async () => {
    mockSearch = "search=onmotion";
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "OnMotionDetected", source_tier: "app" }),
          createListener({ listener_id: 2, app_key: "app_b", handler_method: "on_temperature", source_tier: "app" }),
        ]),
      ),
    );
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
  });

  it("search filters jobs by job_name when ?search= is in URL", async () => {
    mockSearch = "search=backup";
    server.use(
      http.get("/api/scheduler/jobs", () =>
        HttpResponse.json([
          createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
          createJob({ job_id: 11, app_key: "app_b", job_name: "hourly_ping", source_tier: "app" }),
        ]),
      ),
    );
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/job-row-/)).length).toBe(1);
  });

  it("search filters across both handlers and jobs simultaneously when ?search= is in URL", async () => {
    mockSearch = "search=app_a";
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        ]),
      ),
      http.get("/api/scheduler/jobs", () =>
        HttpResponse.json([
          createJob({ job_id: 10, app_key: "app_a", job_name: "daily_backup", source_tier: "app" }),
          createJob({ job_id: 11, app_key: "app_b", job_name: "hourly_ping", source_tier: "app" }),
        ]),
      ),
    );
    const { findAllByTestId, queryAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
    expect((await findAllByTestId(/job-row-/)).length).toBe(1);
    // job_b should be excluded — wait for data loaded above first, then assert
    expect(queryAllByTestId(/job-row-job\/11/).length).toBe(0);
  });

  it("renders a footer with handler and job counts", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
          createListener({ listener_id: 2, app_key: "app_a", handler_method: "on_change", source_tier: "app" }),
        ]),
      ),
      http.get("/api/scheduler/jobs", () =>
        HttpResponse.json([createJob({ job_id: 10, app_key: "app_a", job_name: "my_job", source_tier: "app" })]),
      ),
    );
    const { findByText } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect(await findByText(/2 handlers/i)).toBeDefined();
    expect(await findByText(/1 job/i)).toBeDefined();
  });

  it("renders an app column filter button (funnel icon) on the app column header", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        ]),
      ),
    );
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    const filterBtns = await findAllByTestId("filter-btn");
    expect(filterBtns.length).toBe(1);
  });
});

describe("HandlersPage — query param state (FR#5, AC#6)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
          createListener({ listener_id: 2, app_key: "fw_app", handler_method: "fw_handler", source_tier: "framework" }),
        ]),
      ),
      http.get("/api/scheduler/jobs", () =>
        HttpResponse.json([createJob({ job_id: 10, app_key: "app_b", job_name: "my_job", source_tier: "app" })]),
      ),
    );
  });

  it("reads search from URL query param — ?search=event filters results", async () => {
    // "on_event" is the app-tier handler; default tier=app, so search "event" should return it
    mockSearch = "search=event";
    const { findAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
  });

  it("reads app filter from URL query param — ?app=app_a filters to that app", async () => {
    mockSearch = "app=app_a";
    const { findAllByTestId, queryAllByTestId } = renderWithAppState(<HandlersPage />, { stateOverrides });
    expect((await findAllByTestId(/listener-row-/)).length).toBe(1);
    // app_b job should be excluded — data already loaded via findAllByTestId above
    expect(queryAllByTestId(/job-row-/).length).toBe(0);
  });

  it("changing sort calls qp.set with replace (no new history entry — AC#6)", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({ listener_id: 1, app_key: "app_a", handler_method: "on_event", source_tier: "app" }),
        ]),
      ),
    );
    const { findByRole } = renderWithAppState(<HandlersPage />, { stateOverrides });
    // Wait for data to load, then click the sort button
    const sortBtn = await findByRole("button", { name: /^name/i });
    // SortHeader renders a <th><button> — click the button, not the th
    fireEvent.click(sortBtn);
    expect(mockNavigate).toHaveBeenCalledWith(expect.stringContaining("sort=name"), { replace: true });
  });

  it("handler deep-links use /apps/:key/handlers/:id format in desktop table", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json([
          createListener({
            listener_id: 42,
            app_key: "motion_lights",
            handler_method: "on_motion",
            source_tier: "app",
          }),
        ]),
      ),
    );
    const { findByRole } = renderWithAppState(<HandlersPage />, { stateOverrides });
    const link = await findByRole("link", { name: /on_motion/i });
    expect((link as HTMLAnchorElement).href).toContain("/apps/motion_lights/handlers/listener/42");
  });
});
