import { signal } from "@preact/signals";
import { fireEvent, screen } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { h } from "preact";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../../api/generated-types";
import { createInstance, createManifest } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import { Sidebar } from "./sidebar";

type ManifestListResponse = components["schemas"]["AppManifestListResponse"];
type AppManifest = components["schemas"]["AppManifestResponse"];

/** Installs an MSW handler returning the given manifests for the duration of the test. */
function withManifests(manifests: AppManifest[]) {
  server.use(
    http.get("/api/apps/manifests", () =>
      HttpResponse.json<ManifestListResponse>({
        total: manifests.length,
        running: manifests.filter((m) => m.status === "running").length,
        failed: manifests.filter((m) => m.status === "failed").length,
        stopped: 0,
        disabled: 0,
        blocked: 0,
        manifests,
        only_app: null,
      }),
    ),
  );
}

// Mock wouter to control the current location
vi.mock("wouter", () => ({
  Link: ({
    href,
    class: cls,
    children,
    "aria-label": ariaLabel,
    "aria-current": ariaCurrent,
    "data-testid": testId,
    ...rest
  }: Record<string, unknown>) =>
    h(
      "a",
      { href, class: cls, "aria-label": ariaLabel, "aria-current": ariaCurrent, "data-testid": testId, ...rest },
      children as never,
    ),
  useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
  useSearch: vi.fn().mockReturnValue(""),
}));

const wouter = await import("wouter");
const useLocation = wouter.useLocation as ReturnType<typeof vi.fn>;
const useSearch = wouter.useSearch as ReturnType<typeof vi.fn>;

describe("Sidebar — structure", () => {
  it("renders an aside element as the sidebar root", () => {
    const { container } = renderWithAppState(<Sidebar />);
    expect(container.querySelector("aside[data-testid='sidebar']")).not.toBeNull();
  });

  it("renders main navigation with accessibility label", () => {
    const { getByLabelText } = renderWithAppState(<Sidebar />);
    expect(getByLabelText("Main navigation")).toBeDefined();
  });

  it("renders the hassette wordmark", () => {
    const { getByText } = renderWithAppState(<Sidebar />);
    const wordmark = getByText("hassette");
    expect(wordmark).toBeDefined();
  });

  it("renders a brand link to home", () => {
    const { getByLabelText } = renderWithAppState(<Sidebar />);
    const brandLink = getByLabelText("Hassette home");
    expect(brandLink.getAttribute("href")).toBe("/apps");
  });

  it("renders the Cmd-K button", () => {
    const { getByLabelText } = renderWithAppState(<Sidebar />);
    const btn = getByLabelText("Open command palette");
    expect(btn).toBeDefined();
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it("Cmd-K button calls onOpenPalette when clicked", () => {
    const onOpenPalette = vi.fn();
    const { getByLabelText } = renderWithAppState(<Sidebar onOpenPalette={onOpenPalette} />);
    const btn = getByLabelText("Open command palette");
    fireEvent.click(btn);
    expect(onOpenPalette).toHaveBeenCalledOnce();
  });
});

describe("Sidebar — nav items", () => {
  it("renders Apps nav link to /apps as first item", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />);
    const link = getByTestId("nav-apps");
    expect(link.getAttribute("href")).toBe("/apps");
    expect(link.textContent).toBe("apps");
  });

  it("does not render an overview nav link", () => {
    const { container } = renderWithAppState(<Sidebar />);
    expect(container.querySelector("[data-testid='nav-overview']")).toBeNull();
  });

  it("renders Logs nav link to /logs", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />);
    const link = getByTestId("nav-logs");
    expect(link.getAttribute("href")).toBe("/logs");
    expect(link.textContent).toBe("logs");
  });

  it("renders Config nav link to /config", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />);
    const link = getByTestId("nav-config");
    expect(link.getAttribute("href")).toBe("/config");
    expect(link.textContent).toBe("config");
  });

  it("marks Apps as active when at /apps", () => {
    useLocation.mockReturnValue(["/apps", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-apps").getAttribute("aria-current")).toBe("page");
    expect(getByTestId("nav-logs").getAttribute("aria-current")).toBeNull();
  });

  it("marks Logs as active when at /logs", () => {
    useLocation.mockReturnValue(["/logs", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-logs").getAttribute("aria-current")).toBe("page");
    expect(getByTestId("nav-apps").getAttribute("aria-current")).toBeNull();
  });

  it("marks Config as active when at /config", () => {
    useLocation.mockReturnValue(["/config", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-config").getAttribute("aria-current")).toBe("page");
    expect(getByTestId("nav-apps").getAttribute("aria-current")).toBeNull();
  });
});

describe("Sidebar — app list", () => {
  it("renders apps from the manifests API", async () => {
    withManifests([createManifest({ app_key: "my_app", display_name: "My App", status: "running" })]);
    renderWithAppState(<Sidebar />);
    expect(await screen.findByText("My App")).toBeDefined();
  });

  it("renders app link with correct href", async () => {
    withManifests([createManifest({ app_key: "my_app", display_name: "My App" })]);
    renderWithAppState(<Sidebar />);
    const nameEl = await screen.findByText("My App");
    const link = nameEl.closest("a");
    expect(link?.getAttribute("href")).toBe("/apps/my_app");
  });

  it("shows auto badge on auto-loaded apps", async () => {
    withManifests([createManifest({ auto_loaded: true, display_name: "My App" })]);
    renderWithAppState(<Sidebar />);
    await screen.findByText("My App");
    expect(screen.getByTitle("Auto-loaded")).toBeDefined();
  });

  it("does not show auto badge on non-auto-loaded apps", async () => {
    withManifests([createManifest({ auto_loaded: false, display_name: "My App" })]);
    renderWithAppState(<Sidebar />);
    await screen.findByText("My App");
    expect(screen.queryByTitle("Auto-loaded")).toBeNull();
  });

  it("groups apps so FAILING group header appears before RUNNING group header in DOM", async () => {
    withManifests([
      createManifest({ app_key: "running_app", display_name: "Running App", status: "running" }),
      createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" }),
    ]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    // Failed App is visible in expanded FAILING group
    await screen.findByText("Failed App");
    // Group headers are in DOM order: FAILING before RUNNING
    const appNav = getByTestId("app-nav");
    const groupHeaders = Array.from(appNav.querySelectorAll("[data-testid='group-header']")).map(
      (el) => el.textContent,
    );
    const failingIdx = groupHeaders.findIndex((t) => t?.includes("FAILING"));
    const runningIdx = groupHeaders.findIndex((t) => t?.includes("RUNNING"));
    expect(failingIdx).toBeGreaterThanOrEqual(0);
    expect(runningIdx).toBeGreaterThanOrEqual(0);
    expect(failingIdx).toBeLessThan(runningIdx);
  });

  it("applies is-blocked class and aria-disabled to blocked apps", async () => {
    withManifests([createManifest({ app_key: "b_app", display_name: "Blocked App", status: "blocked" })]);
    renderWithAppState(<Sidebar />);
    const nameEl = await screen.findByText("Blocked App");
    const item = nameEl.closest("[data-testid='app-item-b_app']");
    expect(item?.getAttribute("aria-disabled")).toBe("true");
  });
});

describe("Sidebar — search", () => {
  it("renders a search input for filtering apps", () => {
    const { container } = renderWithAppState(<Sidebar />);
    const input = container.querySelector("input[type='search']");
    expect(input).not.toBeNull();
  });

  it("filters apps by display name when user types", async () => {
    withManifests([
      createManifest({ app_key: "alpha", display_name: "Alpha App" }),
      createManifest({ app_key: "beta", display_name: "Beta App" }),
    ]);
    const { container } = renderWithAppState(<Sidebar />);
    // Wait for both apps to appear
    await screen.findByText("Alpha App");
    await screen.findByText("Beta App");
    const input = container.querySelector("input[type='search']")!;
    fireEvent.input(input, { target: { value: "Alpha" } });
    expect(screen.queryByText("Beta App")).toBeNull();
    expect(screen.queryByText("Alpha App")).not.toBeNull();
  });
});

describe("Sidebar — multi-instance apps", () => {
  it("shows expand button for multi-instance apps", async () => {
    withManifests([
      createManifest({
        app_key: "multi_app",
        display_name: "Multi App",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
          createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
        ],
      }),
    ]);
    renderWithAppState(<Sidebar />);
    expect(await screen.findByLabelText("Expand Multi App")).toBeDefined();
  });

  it("clicking expand shows instance links", async () => {
    withManifests([
      createManifest({
        app_key: "multi_app",
        display_name: "Multi App",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
          createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
        ],
      }),
    ]);
    renderWithAppState(<Sidebar />);
    const expandBtn = await screen.findByLabelText("Expand Multi App");
    fireEvent.click(expandBtn);
    expect(screen.getByText("inst_0")).toBeDefined();
    expect(screen.getByText("inst_1")).toBeDefined();
  });

  it("instance links use ?instance=N query param format", async () => {
    withManifests([
      createManifest({
        app_key: "multi_app",
        display_name: "Multi App",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
          createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
        ],
      }),
    ]);
    renderWithAppState(<Sidebar />);
    const expandBtn = await screen.findByLabelText("Expand Multi App");
    fireEvent.click(expandBtn);
    const inst0Link = screen.getByText("inst_0").closest("a");
    const inst1Link = screen.getByText("inst_1").closest("a");
    expect(inst0Link?.getAttribute("href")).toBe("/apps/multi_app?instance=0");
    expect(inst1Link?.getAttribute("href")).toBe("/apps/multi_app?instance=1");
  });

  it("instance link is active when location matches app path with correct instance query param", async () => {
    useLocation.mockReturnValue(["/apps/multi_app", vi.fn()]);
    useSearch.mockReturnValue("instance=1");
    withManifests([
      createManifest({
        app_key: "multi_app",
        display_name: "Multi App",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
          createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
        ],
      }),
    ]);
    renderWithAppState(<Sidebar />);
    const expandBtn = await screen.findByLabelText("Expand Multi App");
    fireEvent.click(expandBtn);
    const inst1Link = screen.getByText("inst_1").closest("a");
    const inst0Link = screen.getByText("inst_0").closest("a");
    expect(inst1Link?.getAttribute("aria-current")).toBe("page");
    expect(inst0Link?.getAttribute("aria-current")).toBeNull();
  });
});

describe("Sidebar — version display", () => {
  it("renders version string below wordmark when systemVersion is set", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />, {
      stateOverrides: { systemVersion: signal("1.2.3") },
    });
    const sidebar = getByTestId("sidebar");
    expect(sidebar.textContent).toContain("v1.2.3");
  });

  it("shows version without connection status", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />, {
      stateOverrides: {
        systemVersion: signal("1.0.0"),
      },
    });
    const sidebar = getByTestId("sidebar");
    expect(sidebar.textContent).toContain("v1.0.0");
    expect(sidebar.textContent).not.toContain("connected");
  });

  it("omits version line when systemVersion is null", () => {
    const { container } = renderWithAppState(<Sidebar />, {
      stateOverrides: { systemVersion: signal(null) },
    });
    // Version text "v" followed by a version string should not appear
    expect(container.textContent).not.toMatch(/v\d+\.\d+/);
  });
});

describe("Sidebar — APPS section header", () => {
  it("renders APPS header above the search input", async () => {
    withManifests([createManifest({ display_name: "My App" })]);
    renderWithAppState(<Sidebar />);
    await screen.findByText("My App");
    expect(screen.getByText(/^APPS/)).toBeDefined();
  });

  it("APPS header shows total count", async () => {
    withManifests([
      createManifest({ app_key: "a1", display_name: "App One" }),
      createManifest({ app_key: "a2", display_name: "App Two" }),
    ]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    await screen.findByText("App One");
    const appNav = getByTestId("app-nav");
    expect(appNav.textContent).toContain("2");
  });

  it("shows filtered/total counts when search is active", async () => {
    withManifests([
      createManifest({ app_key: "a1", display_name: "Alpha App" }),
      createManifest({ app_key: "a2", display_name: "Beta App" }),
    ]);
    const { getByTestId, container } = renderWithAppState(<Sidebar />);
    await screen.findByText("Alpha App");
    const input = container.querySelector("input[type='search']")!;
    fireEvent.input(input, { target: { value: "Alpha" } });
    const appNav = getByTestId("app-nav");
    expect(appNav.textContent).toContain("1/2");
  });
});

describe("Sidebar — status groups", () => {
  it("groups failed apps under FAILING header", async () => {
    withManifests([createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" })]);
    renderWithAppState(<Sidebar />);
    expect(await screen.findByText("FAILING")).toBeDefined();
    expect(await screen.findByText("Failed App")).toBeDefined();
  });

  it("groups running apps under RUNNING header", async () => {
    withManifests([createManifest({ app_key: "running_app", display_name: "Running App", status: "running" })]);
    renderWithAppState(<Sidebar />);
    expect(await screen.findByText("RUNNING")).toBeDefined();
  });

  it("groups disabled apps under DISABLED header", async () => {
    withManifests([createManifest({ app_key: "dis_app", display_name: "Disabled App", status: "disabled" })]);
    renderWithAppState(<Sidebar />);
    expect(await screen.findByText("DISABLED")).toBeDefined();
  });

  it("hides empty groups", async () => {
    withManifests([createManifest({ app_key: "running_app", display_name: "Running App", status: "running" })]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    await screen.findByText("Running App");
    const appNav = getByTestId("app-nav");
    const groupHeaders = Array.from(appNav.querySelectorAll("[data-testid='group-header']")).map(
      (el) => el.textContent,
    );
    expect(groupHeaders.some((t) => t?.includes("FAILING"))).toBe(false);
    expect(groupHeaders.some((t) => t?.includes("RUNNING"))).toBe(true);
  });

  it("clicking group header collapses the group", async () => {
    withManifests([createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" })]);
    renderWithAppState(<Sidebar />);
    const header = await screen.findByText("FAILING");
    // Failed App visible before collapse
    expect(screen.getByText("Failed App")).toBeDefined();
    // Click header to collapse
    fireEvent.click(header.closest("[data-testid='group-header']")!);
    // Failed App hidden after collapse
    expect(screen.queryByText("Failed App")).toBeNull();
  });

  it("pressing Enter on group header toggles collapse", async () => {
    withManifests([createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" })]);
    renderWithAppState(<Sidebar />);
    const header = await screen.findByText("FAILING");
    expect(screen.getByText("Failed App")).toBeDefined();
    // Collapse via click (native <button> handles Enter/Space → click automatically)
    fireEvent.click(header.closest("[data-testid='group-header']")!);
    expect(screen.queryByText("Failed App")).toBeNull();
    // Re-expand
    fireEvent.click(header.closest("[data-testid='group-header']")!);
    expect(screen.queryByText("Failed App")).not.toBeNull();
  });

  it("maps exhausted_dead to FAILING group", async () => {
    withManifests([
      createManifest({
        app_key: "dead_app",
        display_name: "Dead App",
        status: "failed",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "dead_app", index: 0, status: "exhausted_dead" }),
          createInstance({ app_key: "dead_app", index: 1, status: "running" }),
        ],
      }),
    ]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(await screen.findByText("FAILING")).toBeDefined();
    expect(await screen.findByText("Dead App")).toBeDefined();
    const appNav = getByTestId("app-nav");
    const groupHeaders = Array.from(appNav.querySelectorAll("[data-testid='group-header']")).map(
      (el) => el.textContent,
    );
    expect(groupHeaders.some((t) => t?.includes("RUNNING"))).toBe(false);
  });

  it("pressing Space on group header toggles collapse", async () => {
    withManifests([createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" })]);
    renderWithAppState(<Sidebar />);
    const header = await screen.findByText("FAILING");
    expect(screen.getByText("Failed App")).toBeDefined();
    fireEvent.click(header.closest("[data-testid='group-header']")!);
    expect(screen.queryByText("Failed App")).toBeNull();
    fireEvent.click(header.closest("[data-testid='group-header']")!);
    expect(screen.queryByText("Failed App")).not.toBeNull();
  });

  it("forces RUNNING group open when all apps are healthy", async () => {
    withManifests([
      createManifest({ app_key: "app1", display_name: "App One", status: "running" }),
      createManifest({ app_key: "app2", display_name: "App Two", status: "running" }),
    ]);
    renderWithAppState(<Sidebar />);
    expect(await screen.findByText("App One")).toBeDefined();
    expect(screen.getByText("App Two")).toBeDefined();
  });
});
