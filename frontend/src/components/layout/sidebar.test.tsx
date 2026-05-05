import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { h } from "preact";
import { signal } from "@preact/signals";
import { Sidebar } from "./sidebar";
import { renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import { http, HttpResponse } from "msw";
import { createManifest, createManifestList, createInstance } from "../../test/factories";
import type { components } from "../../api/generated-types";

type ManifestListResponse = components["schemas"]["AppManifestListResponse"];

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
    h("a", { href, class: cls, "aria-label": ariaLabel, "aria-current": ariaCurrent, "data-testid": testId, ...rest }, children as never),
  useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
}));

const wouter = await import("wouter");
const useLocation = wouter.useLocation as ReturnType<typeof vi.fn>;

describe("Sidebar — structure", () => {
  it("renders an aside element with ht-sidebar class", () => {
    const { container } = renderWithAppState(<Sidebar />);
    expect(container.querySelector("aside.ht-sidebar")).not.toBeNull();
  });

  it("renders main navigation with accessibility label", async () => {
    const { getByLabelText } = renderWithAppState(<Sidebar />);
    expect(getByLabelText("Main navigation")).toBeDefined();
  });

  it("renders the hassette wordmark", () => {
    const { container } = renderWithAppState(<Sidebar />);
    const wordmark = container.querySelector(".ht-wordmark");
    expect(wordmark).not.toBeNull();
    expect(wordmark!.textContent).toBe("hassette");
  });

  it("renders a brand link to home", () => {
    const { getByLabelText } = renderWithAppState(<Sidebar />);
    const brandLink = getByLabelText("Hassette home");
    expect(brandLink.getAttribute("href")).toBe("/");
  });

  it("renders the Cmd-K button", () => {
    const { container } = renderWithAppState(<Sidebar />);
    const btn = container.querySelector(".ht-sidebar__cmdkey");
    expect(btn).not.toBeNull();
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it("Cmd-K button calls onOpenPalette when clicked", () => {
    const onOpenPalette = vi.fn();
    const { container } = renderWithAppState(<Sidebar onOpenPalette={onOpenPalette} />);
    const btn = container.querySelector(".ht-sidebar__cmdkey")! as HTMLButtonElement;
    fireEvent.click(btn);
    expect(onOpenPalette).toHaveBeenCalledOnce();
  });
});

describe("Sidebar — nav items", () => {
  it("renders Overview nav link to /", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />);
    const link = getByTestId("nav-overview");
    expect(link.getAttribute("href")).toBe("/");
    expect(link.textContent).toBe("overview");
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

  it("applies is-active to Overview when at root", () => {
    useLocation.mockReturnValue(["/", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-overview").className).toContain("is-active");
    expect(getByTestId("nav-logs").className).not.toContain("is-active");
  });

  it("applies is-active to Logs when at /logs", () => {
    useLocation.mockReturnValue(["/logs", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-logs").className).toContain("is-active");
    expect(getByTestId("nav-overview").className).not.toContain("is-active");
  });

  it("applies is-active to Config when at /config", () => {
    useLocation.mockReturnValue(["/config", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-config").className).toContain("is-active");
    expect(getByTestId("nav-overview").className).not.toContain("is-active");
  });

  it("active nav item has aria-current=page", () => {
    useLocation.mockReturnValue(["/logs", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-logs").getAttribute("aria-current")).toBe("page");
    expect(getByTestId("nav-overview").getAttribute("aria-current")).toBeNull();
  });

  it("Overview is not active on /apps", () => {
    useLocation.mockReturnValue(["/apps", vi.fn()]);
    const { getByTestId } = renderWithAppState(<Sidebar />);
    expect(getByTestId("nav-overview").className).not.toContain("is-active");
  });
});

describe("Sidebar — app list", () => {
  it("renders apps from the manifests API", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "my_app", display_name: "My App", status: "running" }),
            ],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    expect(await findByText("My App")).toBeDefined();
  });

  it("renders app link with correct href", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [createManifest({ app_key: "my_app", display_name: "My App" })],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    const link = (await findByText("My App")).closest("a");
    expect(link?.getAttribute("href")).toBe("/apps/my_app");
  });

  it("shows auto badge on auto-loaded apps", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [createManifest({ auto_loaded: true, display_name: "My App" })],
          }),
        ),
      ),
    );
    const { findByTitle } = renderWithAppState(<Sidebar />);
    expect(await findByTitle("Auto-loaded")).toBeDefined();
  });

  it("does not show auto badge on non-auto-loaded apps", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [createManifest({ auto_loaded: false, display_name: "My App" })],
          }),
        ),
      ),
    );
    const { queryByTitle } = renderWithAppState(<Sidebar />);
    // Wait briefly for data to load
    await new Promise((r) => setTimeout(r, 10));
    expect(queryByTitle("Auto-loaded")).toBeNull();
  });

  it("groups apps so FAILING group header appears before RUNNING group header in DOM", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "running_app", display_name: "Running App", status: "running" }),
              createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" }),
            ],
          }),
        ),
      ),
    );
    const { findByText, container } = renderWithAppState(<Sidebar />);
    // Failed App is visible in expanded FAILING group
    expect(await findByText("Failed App")).toBeDefined();
    // Group headers are in DOM order: FAILING before RUNNING
    const groupHeaders = Array.from(container.querySelectorAll(".ht-sidebar__group-header"))
      .map((el) => el.textContent);
    const failingIdx = groupHeaders.findIndex((t) => t?.includes("FAILING"));
    const runningIdx = groupHeaders.findIndex((t) => t?.includes("RUNNING"));
    expect(failingIdx).toBeGreaterThanOrEqual(0);
    expect(runningIdx).toBeGreaterThanOrEqual(0);
    expect(failingIdx).toBeLessThan(runningIdx);
  });

  it("applies is-blocked class to blocked apps", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [createManifest({ app_key: "b_app", display_name: "Blocked App", status: "blocked" })],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    const nameEl = await findByText("Blocked App");
    const item = nameEl.closest(".ht-sidebar__app-item");
    expect(item?.className).toContain("is-blocked");
  });
});

describe("Sidebar — search", () => {
  it("renders a search input for filtering apps", () => {
    const { container } = renderWithAppState(<Sidebar />);
    const input = container.querySelector("input[type='search']");
    expect(input).not.toBeNull();
  });

  it("filters apps by display name when user types", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "alpha", display_name: "Alpha App" }),
              createManifest({ app_key: "beta", display_name: "Beta App" }),
            ],
          }),
        ),
      ),
    );
    const { findByText, queryByText, container } = renderWithAppState(<Sidebar />);
    await findByText("Alpha App");
    const input = container.querySelector("input[type='search']")!;
    fireEvent.input(input, { target: { value: "Alpha" } });
    expect(queryByText("Beta App")).toBeNull();
    expect(queryByText("Alpha App")).not.toBeNull();
  });
});

describe("Sidebar — multi-instance apps", () => {
  it("shows expand button for multi-instance apps", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({
                app_key: "multi_app",
                display_name: "Multi App",
                instance_count: 2,
                instances: [
                  createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
                  createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
                ],
              }),
            ],
          }),
        ),
      ),
    );
    const { findByLabelText } = renderWithAppState(<Sidebar />);
    const expandBtn = await findByLabelText("Expand Multi App");
    expect(expandBtn).toBeDefined();
  });

  it("clicking expand shows instance links", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({
                app_key: "multi_app",
                display_name: "Multi App",
                instance_count: 2,
                instances: [
                  createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
                  createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
                ],
              }),
            ],
          }),
        ),
      ),
    );
    const { findByLabelText, findByText } = renderWithAppState(<Sidebar />);
    const expandBtn = await findByLabelText("Expand Multi App");
    fireEvent.click(expandBtn);
    expect(await findByText("inst_0")).toBeDefined();
    expect(await findByText("inst_1")).toBeDefined();
  });
});

describe("Sidebar — version display", () => {
  it("renders version string below wordmark when systemVersion is set", () => {
    const { container } = renderWithAppState(<Sidebar />, {
      stateOverrides: { systemVersion: signal("1.2.3") },
    });
    const versionEl = container.querySelector(".ht-sidebar__version");
    expect(versionEl).not.toBeNull();
    expect(versionEl!.textContent).toContain("v1.2.3");
  });

  it("shows 'connected' status when WS is connected", () => {
    const { container } = renderWithAppState(<Sidebar />, {
      stateOverrides: {
        systemVersion: signal("1.0.0"),
        connection: signal("connected"),
      },
    });
    const versionEl = container.querySelector(".ht-sidebar__version");
    expect(versionEl!.textContent).toContain("connected");
  });

  it("shows 'reconnecting…' when WS is reconnecting", () => {
    const { container } = renderWithAppState(<Sidebar />, {
      stateOverrides: {
        systemVersion: signal("1.0.0"),
        connection: signal("reconnecting"),
      },
    });
    const versionEl = container.querySelector(".ht-sidebar__version");
    expect(versionEl!.textContent).toContain("reconnecting");
  });

  it("omits version line when systemVersion is null", () => {
    const { container } = renderWithAppState(<Sidebar />, {
      stateOverrides: { systemVersion: signal(null) },
    });
    expect(container.querySelector(".ht-sidebar__version")).toBeNull();
  });
});

describe("Sidebar — APPS section header", () => {
  it("renders APPS header above the search input", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({ manifests: [createManifest({ display_name: "My App" })] }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    expect(await findByText(/^APPS/)).toBeDefined();
  });

  it("APPS header shows total count", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "a1", display_name: "App One" }),
              createManifest({ app_key: "a2", display_name: "App Two" }),
            ],
          }),
        ),
      ),
    );
    const { container, findByText } = renderWithAppState(<Sidebar />);
    await findByText("App One");
    const header = container.querySelector(".ht-sidebar__section-header");
    expect(header?.textContent).toContain("2");
  });

  it("shows filtered/total counts when search is active", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "a1", display_name: "Alpha App" }),
              createManifest({ app_key: "a2", display_name: "Beta App" }),
            ],
          }),
        ),
      ),
    );
    const { container, findByText } = renderWithAppState(<Sidebar />);
    await findByText("Alpha App");
    const input = container.querySelector("input[type='search']")!;
    fireEvent.input(input, { target: { value: "Alpha" } });
    const header = container.querySelector(".ht-sidebar__section-header");
    expect(header?.textContent).toContain("1/2");
  });
});

describe("Sidebar — status groups", () => {
  it("groups failed apps under FAILING header", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" }),
            ],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    expect(await findByText("FAILING")).toBeDefined();
    expect(await findByText("Failed App")).toBeDefined();
  });

  it("groups running apps under RUNNING header", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "running_app", display_name: "Running App", status: "running" }),
            ],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    expect(await findByText("RUNNING")).toBeDefined();
  });

  it("groups disabled apps under DISABLED header", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "dis_app", display_name: "Disabled App", status: "disabled" }),
            ],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    expect(await findByText("DISABLED")).toBeDefined();
  });

  it("hides empty groups", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "running_app", display_name: "Running App", status: "running" }),
            ],
          }),
        ),
      ),
    );
    const { container, findByText } = renderWithAppState(<Sidebar />);
    await findByText("Running App");
    const groupHeaders = Array.from(container.querySelectorAll(".ht-sidebar__group-header")).map(
      (el) => el.textContent,
    );
    expect(groupHeaders.some((t) => t?.includes("FAILING"))).toBe(false);
    expect(groupHeaders.some((t) => t?.includes("RUNNING"))).toBe(true);
  });

  it("clicking group header collapses the group", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" }),
            ],
          }),
        ),
      ),
    );
    const { findByText, queryByText } = renderWithAppState(<Sidebar />);
    const header = await findByText("FAILING");
    // Failed App visible before collapse
    expect(await findByText("Failed App")).toBeDefined();
    // Click header to collapse
    fireEvent.click(header.closest(".ht-sidebar__group-header")!);
    // Failed App hidden after collapse
    expect(queryByText("Failed App")).toBeNull();
  });

  it("pressing Enter on group header toggles collapse", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" }),
            ],
          }),
        ),
      ),
    );
    const { findByText, queryByText } = renderWithAppState(<Sidebar />);
    const header = await findByText("FAILING");
    expect(await findByText("Failed App")).toBeDefined();
    // Keyboard collapse
    fireEvent.keyDown(header.closest(".ht-sidebar__group-header")!, { key: "Enter" });
    expect(queryByText("Failed App")).toBeNull();
    // Keyboard re-expand
    fireEvent.keyDown(header.closest(".ht-sidebar__group-header")!, { key: "Enter" });
    expect(queryByText("Failed App")).not.toBeNull();
  });

  it("maps exhausted_dead to FAILING group", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({
                app_key: "dead_app",
                display_name: "Dead App",
                status: "exhausted_dead",
              }),
            ],
          }),
        ),
      ),
    );
    const { findByText, container } = renderWithAppState(<Sidebar />);
    expect(await findByText("FAILING")).toBeDefined();
    expect(await findByText("Dead App")).toBeDefined();
    const groupHeaders = Array.from(container.querySelectorAll(".ht-sidebar__group-header"))
      .map((el) => el.textContent);
    expect(groupHeaders.some((t) => t?.includes("RUNNING"))).toBe(false);
  });

  it("pressing Space on group header toggles collapse", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "failed_app", display_name: "Failed App", status: "failed" }),
            ],
          }),
        ),
      ),
    );
    const { findByText, queryByText } = renderWithAppState(<Sidebar />);
    const header = await findByText("FAILING");
    expect(await findByText("Failed App")).toBeDefined();
    fireEvent.keyDown(header.closest(".ht-sidebar__group-header")!, { key: " " });
    expect(queryByText("Failed App")).toBeNull();
    fireEvent.keyDown(header.closest(".ht-sidebar__group-header")!, { key: " " });
    expect(queryByText("Failed App")).not.toBeNull();
  });

  it("forces RUNNING group open when all apps are healthy", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "app1", display_name: "App One", status: "running" }),
              createManifest({ app_key: "app2", display_name: "App Two", status: "running" }),
            ],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    expect(await findByText("App One")).toBeDefined();
    expect(await findByText("App Two")).toBeDefined();
  });
});

describe("Sidebar — invocation counts", () => {
  it("shows invocation count next to app name", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({
                app_key: "my_app",
                display_name: "My App",
                status: "running",
                recent_invocations_1h: 42,
              }),
            ],
          }),
        ),
      ),
    );
    const { findByText } = renderWithAppState(<Sidebar />);
    expect(await findByText("42")).toBeDefined();
  });

  it("does not show invocation count when zero", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({
                app_key: "my_app",
                display_name: "My App",
                status: "running",
                recent_invocations_1h: 0,
              }),
            ],
          }),
        ),
      ),
    );
    const { findByText, container } = renderWithAppState(<Sidebar />);
    await findByText("My App");
    const countEl = container.querySelector(".ht-sidebar__app-count");
    expect(countEl).toBeNull();
  });
});
