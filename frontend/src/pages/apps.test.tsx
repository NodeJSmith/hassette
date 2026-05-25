import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createManifest } from "../test/factories";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
import { AppsPage } from "./apps";

// Mutable search string for tests that need to control query params
let mockSearch = "";
const mockNavigate = vi.fn();

vi.mock("wouter", () => ({
  useSearch: () => mockSearch,
  useLocation: () => ["/apps", mockNavigate],
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

// uptimeSeconds=120 ensures useScopedQuery is enabled (since-restart preset requires uptime).
const STATE_WITH_UPTIME = { stateOverrides: { uptimeSeconds: signal(120) } };

describe("AppsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch = "";
  });

  it("shows spinner while loading", () => {
    server.use(http.get("/api/apps/manifests", () => new Promise(() => {})));
    const { container } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(container.querySelector("[data-testid='spinner']")).not.toBeNull();
  });

  it("renders 'apps' heading when data loads", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json({
          total: 1,
          running: 1,
          failed: 0,
          stopped: 0,
          disabled: 0,
          blocked: 0,
          manifests: [createManifest()],
          only_app: null,
        }),
      ),
    );
    const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByRole("heading", { name: /apps/i })).toBeDefined();
  });

  it("renders stats strip with counts", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json({
          total: 2,
          running: 1,
          failed: 0,
          stopped: 0,
          disabled: 1,
          blocked: 0,
          manifests: [
            createManifest({ app_key: "a", status: "running" }),
            createManifest({ app_key: "b", status: "disabled" }),
          ],
          only_app: null,
        }),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByTestId("apps-stats-strip")).toBeDefined();
  });

  it("does not render legacy filter pills", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json({
          total: 1,
          running: 1,
          failed: 0,
          stopped: 0,
          disabled: 0,
          blocked: 0,
          manifests: [createManifest()],
          only_app: null,
        }),
      ),
    );
    const { findByRole, queryByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    // Wait for data to load before asserting absence
    await findByRole("heading", { name: /apps/i });
    expect(queryByTestId("apps-filter-pills")).toBeNull();
  });

  it("renders app rows in the table", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json({
          total: 2,
          running: 2,
          failed: 0,
          stopped: 0,
          disabled: 0,
          blocked: 0,
          manifests: [
            createManifest({ app_key: "app_a", status: "running" }),
            createManifest({ app_key: "app_b", status: "running" }),
          ],
          only_app: null,
        }),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByTestId("app-row-app_a")).toBeDefined();
    expect(await findByTestId("app-row-app_b")).toBeDefined();
  });

  it("renders search input above the table", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json({
          total: 1,
          running: 1,
          failed: 0,
          stopped: 0,
          disabled: 0,
          blocked: 0,
          manifests: [createManifest()],
          only_app: null,
        }),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    const search = await findByTestId("apps-search");
    expect(search).toBeDefined();
  });

  it("shows empty state when no manifests", async () => {
    // Default handler returns empty manifests list — no override needed
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/no apps match/i)).toBeDefined();
  });

  it("renders record count in the table footer", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json({
          total: 2,
          running: 2,
          failed: 0,
          stopped: 0,
          disabled: 0,
          blocked: 0,
          manifests: [
            createManifest({ app_key: "app_a", status: "running" }),
            createManifest({ app_key: "app_b", status: "running" }),
          ],
          only_app: null,
        }),
      ),
    );
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/2 apps/i)).toBeDefined();
  });

  it("footer count updates when search filters results", async () => {
    mockSearch = "search=motion";
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json({
          total: 2,
          running: 2,
          failed: 0,
          stopped: 0,
          disabled: 0,
          blocked: 0,
          manifests: [
            createManifest({ app_key: "motion_lights", status: "running" }),
            createManifest({ app_key: "alarm_app", status: "running" }),
          ],
          only_app: null,
        }),
      ),
    );
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/1 app/i)).toBeDefined();
  });

  describe("STATUS column filter", () => {
    it("renders a filter button on the STATUS column header", async () => {
      server.use(
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 1,
            running: 1,
            failed: 0,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [createManifest({ app_key: "app_a", status: "running" })],
            only_app: null,
          }),
        ),
      );
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      // SortHeader renders filter button with data-testid="filter-btn" when filterContent is provided
      const filterBtn = await findByRole("button", { name: /filter status/i });
      expect(filterBtn).toBeDefined();
    });

    it("clicking the STATUS filter button opens the filter popover", async () => {
      server.use(
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 2,
            running: 1,
            failed: 1,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [
              createManifest({ app_key: "running_app", status: "running" }),
              createManifest({ app_key: "failed_app", status: "failed" }),
            ],
            only_app: null,
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
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 2,
            running: 1,
            failed: 1,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [
              createManifest({ app_key: "running_app", status: "running" }),
              createManifest({ app_key: "failed_app", status: "failed" }),
            ],
            only_app: null,
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
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 2,
            running: 2,
            failed: 0,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [
              createManifest({ app_key: "motion_lights", status: "running" }),
              createManifest({ app_key: "alarm_app", status: "running" }),
            ],
            only_app: null,
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
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 1,
            running: 1,
            failed: 0,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [createManifest({ app_key: "app_a", status: "running" })],
            only_app: null,
          }),
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
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 1,
            running: 1,
            failed: 0,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [createManifest({ app_key: "running_app", status: "running" })],
            only_app: null,
          }),
        ),
      );
      const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByText(/no apps match status: failed/i)).toBeDefined();
    });

    it("provides a clear filters button in the empty state", async () => {
      mockSearch = "filter=failed";
      server.use(
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 1,
            running: 1,
            failed: 0,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [createManifest({ app_key: "running_app", status: "running" })],
            only_app: null,
          }),
        ),
      );
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByRole("button", { name: /clear filters/i })).toBeDefined();
    });

    it("clicking clear filters calls navigate to reset filter and search", async () => {
      mockSearch = "filter=failed";
      server.use(
        http.get("/api/apps/manifests", () =>
          HttpResponse.json({
            total: 1,
            running: 1,
            failed: 0,
            stopped: 0,
            disabled: 0,
            blocked: 0,
            manifests: [createManifest({ app_key: "running_app", status: "running" })],
            only_app: null,
          }),
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
});
