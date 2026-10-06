import { act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { appStatusKey, useAppStore } from "../state/store";
import { appGridResponse, createAppActivityStats, createAppGridEntry, gridEntry } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
import { AppsPage, FAILED_PART_RETRY_MS } from "./apps";

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
const STATE_WITH_UPTIME = { storeOverrides: { uptimeSeconds: 120 } };

const APP_GRID_URL = "/api/telemetry/app-grid";

/** Reads a stats-strip cell's value by its label, since cells carry no per-label testid. The
 * value span is tagged `data-role`, not `data-testid` — see `components/shared/stats-strip.tsx`.
 * Which labels exist is layout-dependent: "stopped" and "disabled" are separate cells only in
 * the desktop set (mobile merges them into "inactive"), and jsdom's default viewport is
 * desktop. Throws rather than returning undefined so a renamed or missing label reads as
 * "no such cell" instead of a value mismatch. */
function getStatValue(strip: HTMLElement, label: string): string {
  for (const cell of strip.querySelectorAll("[data-testid='stats-strip-cell']")) {
    if (cell.querySelector("[data-testid='stats-strip-label']")?.textContent !== label) continue;
    return cell.querySelector("[data-role='stats-strip-value']")?.textContent ?? "";
  }
  throw new Error(`no stats-strip cell labeled "${label}"`);
}

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

  it("renders app rows without WS-provided uptimeSeconds (HA unreachable)", async () => {
    // Regression test for design/specs/018-dashboard-without-ha: the apps page must render
    // even when the WS never connects (uptimeSeconds stays null), not spin forever on the
    // default since-restart preset.
    server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(gridEntry("my_app")))));
    const { findByTestId } = renderWithAppState(<AppsPage />);
    expect(await findByTestId("app-row-my_app")).toBeDefined();
  });

  it("renders 'apps' heading when data loads", async () => {
    server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(createAppGridEntry()))));
    const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByRole("heading", { name: /apps/i })).toBeDefined();
  });

  it("renders stats strip with counts", async () => {
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json(appGridResponse(gridEntry("a", "running"), gridEntry("b", "disabled"))),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByTestId("apps-stats-strip")).toBeDefined();
  });

  it("stats strip counts follow live WS status updates over the stale grid payload", async () => {
    // The dashboard grid query is invalidated on execution events, not app_status_changed, so
    // a cached row.status stays "running" after an app is stopped until something else forces
    // a refetch. The strip must count the live status, like the row badges and filter popover.
    // Statuses arrive after mount so this also pins the store subscription: a page that read
    // appStatus non-reactively would render the right initial counts and then never update.
    // Covers every live-countable category #1153 names: running, failed, stopped, disabled.
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json(
          appGridResponse(
            gridEntry("a", "running"),
            gridEntry("b", "running"),
            gridEntry("c", "running"),
            gridEntry("d", "disabled"),
          ),
        ),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);

    const strip = await findByTestId("apps-stats-strip");
    expect(getStatValue(strip, "total")).toBe("4");
    expect(getStatValue(strip, "running")).toBe("3");
    expect(getStatValue(strip, "failed")).toBe("0");
    expect(getStatValue(strip, "stopped")).toBe("0");
    expect(getStatValue(strip, "disabled")).toBe("1");

    // Drives the store directly rather than through a socket frame: `updateAppStatus` is the
    // exact write the WS `app_status_changed` handler makes (see `hooks/use-websocket.ts`), and
    // it is the boundary AppsPage subscribes to.
    act(() => {
      const { updateAppStatus } = useAppStore.getState();
      updateAppStatus(appStatusKey("b", 0), { status: "stopped", index: 0 });
      updateAppStatus(appStatusKey("c", 0), { status: "failed", index: 0 });
      // "disabled" is a manifest-level config state that appLiveStatus resolves before it
      // consults appStatuses, so a per-instance status left over from before the app was
      // disabled must not mask it.
      updateAppStatus(appStatusKey("d", 0), { status: "stopped", index: 0 });
    });

    expect(getStatValue(strip, "total")).toBe("4");
    expect(getStatValue(strip, "running")).toBe("1");
    expect(getStatValue(strip, "failed")).toBe("1");
    expect(getStatValue(strip, "stopped")).toBe("1");
    expect(getStatValue(strip, "disabled")).toBe("1");
  });

  it("shows '—' for handlers and runs/hr when any row's stats weren't computed, not a partial sum", async () => {
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json({
          apps: [
            createAppGridEntry({ app: { app_key: "a" }, activity: { stats: createAppActivityStats() } }),
            createAppGridEntry({ app: { app_key: "b" }, activity: { stats: null } }),
          ],
        }),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    const strip = await findByTestId("apps-stats-strip");

    expect(getStatValue(strip, "handlers")).toBe("—");
    expect(getStatValue(strip, "runs / hr")).toBe("—");
  });

  it("asks for all-time as since=null (no since param) before uptime arrives", async () => {
    const urls: string[] = [];
    server.use(
      http.get(APP_GRID_URL, ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json(appGridResponse(gridEntry("my_app")));
      }),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />);
    await findByTestId("app-row-my_app");

    expect(new URL(urls[0]).searchParams.has("since")).toBe(false);
  });

  it("shows '—' for runs/hr while placeholder rows from the previous window await a refetch", async () => {
    let calls = 0;
    server.use(
      http.get(APP_GRID_URL, () => {
        calls++;
        // The second fetch (the new window) never resolves, so the first response stays as placeholder data.
        if (calls > 1) return new Promise(() => {});
        return HttpResponse.json(appGridResponse(gridEntry("my_app")));
      }),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    const strip = await findByTestId("apps-stats-strip");
    expect(getStatValue(strip, "runs / hr")).not.toBe("—");

    act(() => {
      useAppStore.setState({ uptimeSeconds: 3600 });
    });

    await vi.waitFor(() => expect(calls).toBe(2));
    expect(getStatValue(strip, "runs / hr")).toBe("—");
    expect((await findByTestId("app-row-my_app")).isConnected).toBe(true);
  });

  describe("polling while an enrichment failure is on screen", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    function serveGrid(responses: Array<Parameters<typeof createAppGridEntry>[0]>): { calls: () => number } {
      let calls = 0;
      server.use(
        http.get(APP_GRID_URL, () => {
          const entry = responses[Math.min(calls, responses.length - 1)];
          calls++;
          return HttpResponse.json({ apps: [createAppGridEntry(entry)], since: 1000 });
        }),
      );
      return { calls: () => calls };
    }

    it("refetches while a requested part is null and stops once the grid is whole", async () => {
      const grid = serveGrid([
        { app: { app_key: "my_app" }, activity: { stats: null } },
        { app: { app_key: "my_app" } },
      ]);
      const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      await findByTestId("app-row-my_app");
      expect(grid.calls()).toBe(1);

      await vi.advanceTimersByTimeAsync(FAILED_PART_RETRY_MS);
      await vi.waitFor(() => expect(grid.calls()).toBe(2));

      await vi.advanceTimersByTimeAsync(3 * FAILED_PART_RETRY_MS);
      expect(grid.calls()).toBe(2);
    });

    it("doesn't poll a healthy grid", async () => {
      const grid = serveGrid([{ app: { app_key: "my_app" } }]);
      const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      await findByTestId("app-row-my_app");

      await vi.advanceTimersByTimeAsync(3 * FAILED_PART_RETRY_MS);
      expect(grid.calls()).toBe(1);
    });
  });

  it("renders each response as sent: a part a newer response nulls doesn't keep its old value", async () => {
    let stats: ReturnType<typeof createAppActivityStats> | null = createAppActivityStats({
      total_invocations: 7,
      total_executions: 0,
    });
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json({ apps: [createAppGridEntry({ app: { app_key: "my_app" }, activity: { stats } })] }),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect((await findByTestId("app-runs")).textContent).toBe("7");

    stats = null;
    act(() => {
      useAppStore.setState({ uptimeSeconds: 240 });
    });

    await vi.waitFor(async () => expect((await findByTestId("app-runs")).textContent).toBe("—"));
  });

  it("does not render legacy filter pills", async () => {
    server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(createAppGridEntry()))));
    const { findByRole, queryByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    // Wait for data to load before asserting absence
    await findByRole("heading", { name: /apps/i });
    expect(queryByTestId("apps-filter-pills")).toBeNull();
  });

  it("renders app rows in the table", async () => {
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json(appGridResponse(gridEntry("app_a", "running"), gridEntry("app_b", "running"))),
      ),
    );
    const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByTestId("app-row-app_a")).toBeDefined();
    expect(await findByTestId("app-row-app_b")).toBeDefined();
  });

  it("renders search input above the table", async () => {
    server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(createAppGridEntry()))));
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
        HttpResponse.json(appGridResponse(gridEntry("app_a", "running"), gridEntry("app_b", "running"))),
      ),
    );
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/2 apps/i)).toBeDefined();
  });

  it("footer count updates when search filters results", async () => {
    mockSearch = "search=motion";
    server.use(
      http.get(APP_GRID_URL, () =>
        HttpResponse.json(appGridResponse(gridEntry("motion_lights", "running"), gridEntry("alarm_app", "running"))),
      ),
    );
    const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
    expect(await findByText(/1 app/i)).toBeDefined();
  });

  describe("STATUS column filter", () => {
    it("renders a filter button on the STATUS column header", async () => {
      server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(gridEntry("app_a", "running")))));
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      // SortHeader renders filter button with data-testid="filter-btn" when filterContent is provided
      const filterBtn = await findByRole("button", { name: /filter status/i });
      expect(filterBtn).toBeDefined();
    });

    it("clicking the STATUS filter button opens the filter popover", async () => {
      const user = userEvent.setup();
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json(appGridResponse(gridEntry("running_app", "running"), gridEntry("failed_app", "failed"))),
        ),
      );
      const { findByRole, findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      const filterBtn = await findByRole("button", { name: /filter status/i });
      await user.click(filterBtn);
      // Popover should now be open and show filter options
      expect(await findByText(/all/i)).toBeDefined();
    });
  });

  describe("query param: filter", () => {
    it("reads filter from URL query params — only failed apps shown when filter=failed", async () => {
      mockSearch = "filter=failed";
      server.use(
        http.get(APP_GRID_URL, () =>
          HttpResponse.json(appGridResponse(gridEntry("running_app", "running"), gridEntry("failed_app", "failed"))),
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
          HttpResponse.json(appGridResponse(gridEntry("motion_lights", "running"), gridEntry("alarm_app", "running"))),
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
      server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(gridEntry("app_a", "running")))));
      const { findByTestId } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByTestId("app-row-app_a")).toBeDefined();
    });
  });

  describe("empty state when filters produce zero results", () => {
    it("names the active filter in the empty state message", async () => {
      mockSearch = "filter=failed";
      server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(gridEntry("running_app", "running")))));
      const { findByText } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByText(/no apps match status: failed/i)).toBeDefined();
    });

    it("provides a clear filters button in the empty state", async () => {
      mockSearch = "filter=failed";
      server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(gridEntry("running_app", "running")))));
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      expect(await findByRole("button", { name: /clear filters/i })).toBeDefined();
    });

    it("clicking clear filters calls navigate to reset filter and search", async () => {
      const user = userEvent.setup();
      mockSearch = "filter=failed";
      server.use(http.get(APP_GRID_URL, () => HttpResponse.json(appGridResponse(gridEntry("running_app", "running")))));
      const { findByRole } = renderWithAppState(<AppsPage />, STATE_WITH_UPTIME);
      const btn = await findByRole("button", { name: /clear filters/i });
      await user.click(btn);
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
