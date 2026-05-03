import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/preact";
import { h } from "preact";
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

  it("renders the Cmd-K button (disabled)", () => {
    const { container } = renderWithAppState(<Sidebar />);
    const btn = container.querySelector(".sidebar__cmdkey");
    expect(btn).not.toBeNull();
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("Sidebar — nav items", () => {
  it("renders Overview nav link to /", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />);
    const link = getByTestId("nav-overview");
    expect(link.getAttribute("href")).toBe("/");
    expect(link.textContent).toBe("Overview");
  });

  it("renders Logs nav link to /logs", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />);
    const link = getByTestId("nav-logs");
    expect(link.getAttribute("href")).toBe("/logs");
    expect(link.textContent).toBe("Logs");
  });

  it("renders Config nav link to /config", () => {
    const { getByTestId } = renderWithAppState(<Sidebar />);
    const link = getByTestId("nav-config");
    expect(link.getAttribute("href")).toBe("/config");
    expect(link.textContent).toBe("Config");
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

  it("groups apps so failed apps appear before running ones", async () => {
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
    expect(await findByText("Failed App")).toBeDefined();
    expect(await findByText("Running App")).toBeDefined();
    const names = Array.from(container.querySelectorAll(".sidebar__app-name")).map((el) => el.textContent);
    const failedIdx = names.indexOf("Failed App");
    const runningIdx = names.indexOf("Running App");
    expect(failedIdx).toBeLessThan(runningIdx);
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
    const item = nameEl.closest(".sidebar__app-item");
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
