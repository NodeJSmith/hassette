import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createAppGridEntry } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
import { AppsPage } from "./apps";

// Mutable search string for tests that need to control query params
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () =>
  createWouterMock({
    useSearch: () => mockSearch,
    useLocation: () => ["/apps", mockNavigate],
  }),
);

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

// uptimeSeconds=120 ensures useScopedQuery is enabled (since-restart preset requires uptime).
const STATE_WITH_UPTIME = { stateOverrides: { uptimeSeconds: signal(120) } };

const APP_GRID_URL = "/api/telemetry/dashboard/app-grid";

describe("AppsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
  });

  it("shows spinner while loading", () => {
    server.use(http.get(APP_GRID_URL, () => new Promise(() => {})));
    const { container } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(container.querySelector("[data-testid='spinner']")).not.toBeNull();
  });

  it("renders 'apps' heading when data loads", async () => {
    server.use(http.get(APP_GRID_URL, () => HttpResponse.json({ apps: [createAppGridEntry()] })));
    const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByRole("heading", { name: /apps/i })).toBeDefined();
  });

  it("renders stats strip with counts", async () => {
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json({
          apps: [
            createAppGridEntry({ app_key: "a", status: "running" }),
            createAppGridEntry({ app_key: "b", status: "disabled" }),
          ],
        }),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByTestId("apps-stats-strip")).toBeDefined();
  });

  it("does not render legacy filter pills", async () => {
    server.use(http.get(APP_GRID_URL, () => HttpResponse.json({ apps: [createAppGridEntry()] })));
    const { findByRole, queryByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    // Wait for data to load before asserting absence
    await findByRole("heading", { name: /apps/i });
    expect(queryByTestId("apps-filter-pills")).toBeNull();
  });

  it("renders app rows in the table", async () => {
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json({
          apps: [
            createAppGridEntry({ app_key: "app_a", status: "running" }),
            createAppGridEntry({ app_key: "app_b", status: "running" }),
          ],
        }),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByTestId("app-row-app_a")).toBeDefined();
    expect(await findByTestId("app-row-app_b")).toBeDefined();
  });

  it("renders search input above the table", async () => {
    server.use(http.get(APP_GRID_URL, () => HttpResponse.json({ apps: [createAppGridEntry()] })));
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    const search = await findByTestId("apps-search");
    expect(search).toBeDefined();
  });

  it("shows empty state when no apps", async () => {
    // Default handler returns empty apps list — no override needed
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/no apps match/i)).toBeDefined();
  });

  it("renders record count in the table footer", async () => {
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json({
          apps: [
            createAppGridEntry({ app_key: "app_a", status: "running" }),
            createAppGridEntry({ app_key: "app_b", status: "running" }),
          ],
        }),
      ),
    );
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/2 apps/i)).toBeDefined();
  });

  it("footer count updates when search filters results", async () => {
    mockSearch = "search=motion";
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json({
          apps: [
            createAppGridEntry({ app_key: "motion_lights", status: "running" }),
            createAppGridEntry({ app_key: "alarm_app", status: "running" }),
          ],
        }),
      ),
    );
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/1 app/i)).toBeDefined();
  });

  describe("STATUS column filter", () => {
    it("renders a filter button on the STATUS column header", async () => {
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({ apps: [createAppGridEntry({ app_key: "app_a", status: "running" })] }),
        ),
      );
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      // SortHeader renders filter button with data-testid="filter-btn" when filterContent is provided
      const filterBtn = await findByRole("button", { name: /filter status/i });
      expect(filterBtn).toBeDefined();
    });

    it("clicking the STATUS filter button opens the filter popover", async () => {
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({
            apps: [
              createAppGridEntry({ app_key: "running_app", status: "running" }),
              createAppGridEntry({ app_key: "failed_app", status: "failed" }),
            ],
          }),
        ),
      );
      const { findByRole, findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      const filterBtn = await findByRole("button", { name: /filter status/i });
      fireEvent.click(filterBtn);
      // Popover should now be open and show filter options
      expect(await findByText(/all/i)).toBeDefined();
    });
  });

  describe("query param: filter", () => {
    it("reads filter from URL query params — only failed apps shown when filter=failed", async () => {
      mockSearch = "filter=failed";
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({
            apps: [
              createAppGridEntry({ app_key: "running_app", status: "running" }),
              createAppGridEntry({ app_key: "failed_app", status: "failed" }),
            ],
          }),
        ),
      );
      const { findByTestId, queryByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByTestId("app-row-failed_app")).toBeDefined();
      expect(queryByTestId("app-row-running_app")).toBeNull();
    });
  });

  describe("query param: search", () => {
    it("reads search from URL query params — filters apps by name", async () => {
      mockSearch = "search=motion";
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({
            apps: [
              createAppGridEntry({ app_key: "motion_lights", status: "running" }),
              createAppGridEntry({ app_key: "alarm_app", status: "running" }),
            ],
          }),
        ),
      );
      const { findByTestId, queryByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByTestId("app-row-motion_lights")).toBeDefined();
      expect(queryByTestId("app-row-alarm_app")).toBeNull();
    });
  });

  describe("query param: sort/dir", () => {
    it("reads sort key from URL — defaults to status when absent", async () => {
      mockSearch = "";
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({ apps: [createAppGridEntry({ app_key: "app_a", status: "running" })] }),
        ),
      );
      const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByTestId("app-row-app_a")).toBeDefined();
    });
  });

  describe("empty state when filters produce zero results", () => {
    it("names the active filter in the empty state message", async () => {
      mockSearch = "filter=failed";
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({ apps: [createAppGridEntry({ app_key: "running_app", status: "running" })] }),
        ),
      );
      const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByText(/no apps match status: failed/i)).toBeDefined();
    });

    it("provides a clear filters button in the empty state", async () => {
      mockSearch = "filter=failed";
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({ apps: [createAppGridEntry({ app_key: "running_app", status: "running" })] }),
        ),
      );
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByRole("button", { name: /clear filters/i })).toBeDefined();
    });

    it("clicking clear filters calls navigate to reset filter and search", async () => {
      mockSearch = "filter=failed";
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json({ apps: [createAppGridEntry({ app_key: "running_app", status: "running" })] }),
        ),
      );
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      const btn = await findByRole("button", { name: /clear filters/i });
      fireEvent.click(btn);
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.not.stringContaining("filter="),
        expect.objectContaining({ replace: true }),
      );
    });
  });

  describe("503 error state", () => {
    it("shows a telemetry-unavailable banner when the grid endpoint returns 503", async () => {
      server.use(http.get(APP_GRID_URL, () => HttpResponse.json({ detail: "db down" }, { status: 503 })));
      const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      const alert = await findByTestId("apps-load-error");
      expect(alert.textContent).toMatch(/telemetry unavailable/i);
    });
  });
});
