import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appStatusKey, type AppStore } from "../state/store";
import { createInstance, createManifest } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import type { AppDetailTab } from "../utils/app-routes";
import { AppDetailPage } from "./app-detail";
import { setupApi, setupMultiInstanceParent } from "./app-detail.test-helpers";

// Mutable search string for tests that need to control query params
let mockSearchString = "";
const mockNavigate = vi.fn();

// Stub wouter navigation
vi.mock("wouter", () =>
  createWouterMock({
    useLocation: () => ["/apps/test_app", mockNavigate],
    useSearch: () => mockSearchString,
  }),
);

// Stub child components not under test. Shared stub factories live in app-detail.test-helpers —
// imported dynamically (not as a static top-level import) because these vi.mock factories run
// while this file's own real "./app-detail" import is still resolving, and a static import here
// would be in the TDZ at that point.
vi.mock("../components/shared/error-banner", async () =>
  (await import("./app-detail.test-helpers")).createErrorBannerStub(),
);
vi.mock("../components/app-detail/handlers-tab", async () =>
  (await import("./app-detail.test-helpers")).createHandlersTabStub(),
);
vi.mock("../components/app-detail/code-tab", async () =>
  (await import("./app-detail.test-helpers")).createCodeTabStub(),
);
vi.mock("../components/app-detail/config-tab", async () =>
  (await import("./app-detail.test-helpers")).createConfigTabStub(),
);
vi.mock("../components/app-detail/overview-tab", async () =>
  (await import("./app-detail.test-helpers")).createOverviewTabStub(),
);
vi.mock("../components/shared/log-table", async () => (await import("./app-detail.test-helpers")).createLogTableStub());
vi.mock("../components/shared/spinner", async () => (await import("./app-detail.test-helpers")).createSpinnerStub());

const mockCorrectUrl = vi.fn();
vi.mock("../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

function renderPage(
  params: { key: string; tab?: AppDetailTab; handler?: string },
  storeOverrides: Partial<AppStore> = {},
) {
  return renderWithAppState(<AppDetailPage params={params} />, {
    storeOverrides: { uptimeSeconds: 120, ...storeOverrides },
  });
}

describe("AppDetailPage instances", () => {
  beforeEach(() => {
    mockSearchString = "";
    mockNavigate.mockClear();
    vi.clearAllMocks();
  });

  it("renders multi-instance parent overview when instance_count > 1 and no index param", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("instance-grid")).toBeDefined();
  });

  it("renders instance grid cards with instance names", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("instance-card-0")).toBeDefined();
    expect(await findByTestId("instance-card-1")).toBeDefined();
  });

  it("instance grid card reflects live appStatus over stale manifest status", async () => {
    // Reproduces a stale-status report: the manifest fetch says inst_0 is still "running",
    // but a WS app_status_changed message (mirrored into the appStatus store) already marked
    // it "stopped". The grid must show the live value, not the cached manifest snapshot.
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage(
      { key: "test_app" },
      { appStatus: { [appStatusKey("test_app", 0)]: { status: "stopped", index: 0 } } },
    );

    const card0 = await findByTestId("instance-card-0");
    expect(card0.textContent).toContain("stopped");
    expect(card0.textContent).not.toContain("running");
  });

  it("instance switcher status dot reflects live appStatus over stale manifest status", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=1";
    const { findByTestId } = renderPage(
      { key: "test_app" },
      { appStatus: { [appStatusKey("test_app", 0)]: { status: "stopped", index: 0 } } },
    );

    const switcherBtn0 = await findByTestId("switcher-instance-0");
    // StatusShape is a bare aria-hidden SVG with no status text or data attribute — "stopped"
    // renders as a "mute" kind (stroke-only circle, fill="none"), "running" as "ok" (filled
    // circle, fill="var(--ok-vivid)"). Assert on the fill to distinguish them.
    expect(switcherBtn0.querySelector("svg circle")?.getAttribute("fill")).toBe("none");
  });

  it("renders instance count badge in parent overview header", async () => {
    const manifest = createManifest({
      instance_count: 3,
      instances: [
        createInstance({ index: 0, instance_name: "a", status: "running" }),
        createInstance({ index: 1, instance_name: "b", status: "running" }),
        createInstance({ index: 2, instance_name: "c", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect((await findByTestId("instance-count-badge")).textContent).toContain("3");
  });

  it("renders instance switcher in detail header when on instance view with siblings", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    // Instance 0 is specified via query param
    mockSearchString = "instance=0";
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("instance-switcher")).toBeDefined();
  });

  it("instance switcher navigates to current tab path with instance query param", async () => {
    const user = userEvent.setup();
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=0";
    const { findByTestId } = renderPage({ key: "test_app", tab: "logs" });
    // Click instance 1 in the switcher
    const inst1Btn = await findByTestId("switcher-instance-1");
    await user.click(inst1Btn);
    // Should navigate to /apps/test_app/logs?instance=1
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/logs?instance=1");
  });

  it("multi-instance parent overview navigates using ?instance= query param", async () => {
    const user = userEvent.setup();
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    // No instance param = parent overview
    const { findByTestId } = renderPage({ key: "test_app" });
    // Click an instance card
    const card0 = await findByTestId("instance-card-0");
    await user.click(card0);
    // Should navigate to /apps/test_app/overview?instance=0
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/overview?instance=0");
  });

  it("reads instance from ?instance= query param for multi-instance detail view", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=1";
    const { findByTestId } = renderPage({ key: "test_app" });
    // Instance switcher should be rendered (not parent overview)
    await findByTestId("instance-switcher");
    // The instance 1 button should be active
    const inst1Btn = await findByTestId("switcher-instance-1");
    expect(inst1Btn.getAttribute("aria-selected")).toBe("true");
  });

  it("corrects out-of-range instance index to instance 0 via correctUrl", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=99";
    renderPage({ key: "test_app", tab: "handlers" });
    // Wait for manifests to load, then check correctUrl was called
    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers?instance=0");
    });
  });

  it("corrects negative instance query params before preserving them in links", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=-1";

    const { findByRole } = renderPage({ key: "test_app", tab: "logs" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/logs?instance=0");
    });
    expect((await findByRole("tab", { name: /overview/i })).getAttribute("href")).toBe("/apps/test_app/overview");
  });

  it.each(["0x1", "1e2"])("corrects malformed instance query param %s", async (instanceParam) => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = `instance=${instanceParam}`;

    renderPage({ key: "test_app", tab: "logs" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/logs?instance=0");
    });
  });

  it("preserves code line deep links when correcting invalid instance params", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "line=42&instance=-1";

    renderPage({ key: "test_app", tab: "code" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/code?line=42&instance=0");
    });
  });

  it("corrects negative instance query params on handlers without redirecting to parent overview", async () => {
    const manifest = createManifest({
      instance_count: 2,
      instances: [
        createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
        createInstance({ index: 1, instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=-1";

    renderPage({ key: "test_app", tab: "handlers" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers?instance=0");
    });
    expect(mockCorrectUrl).not.toHaveBeenCalledWith("/apps/test_app/overview");
  });

  it("parent page renders tab strip with 4 tabs (no handlers)", async () => {
    setupMultiInstanceParent();
    const { findAllByRole } = renderPage({ key: "test_app" });
    const tabs = await findAllByRole("tab");
    const labels = tabs.map((t) => t.textContent?.trim());
    expect(labels).toEqual(["overview", "code", "logs", "config"]);
  });

  it("parent page hides handlers tab", async () => {
    setupMultiInstanceParent();
    const { findByTestId, queryByRole } = renderPage({ key: "test_app" });
    await findByTestId("app-title");
    expect(queryByRole("tab", { name: /handlers/i })).toBeNull();
  });

  it("parent page renders code tab content", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = renderPage({ key: "test_app", tab: "code" });
    expect(await findByTestId("code-tab")).toBeDefined();
  });

  it("parent page renders logs tab content", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = renderPage({ key: "test_app", tab: "logs" });
    expect(await findByTestId("log-table-drawer")).toBeDefined();
  });

  it("parent page renders config tab content", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = renderPage({ key: "test_app", tab: "config" });
    expect(await findByTestId("config-tab")).toBeDefined();
  });

  it("parent page does not render instance switcher", async () => {
    setupMultiInstanceParent();
    const { findByTestId, queryByTestId } = renderPage({ key: "test_app" });
    await findByTestId("app-title");
    expect(queryByTestId("instance-switcher")).toBeNull();
  });

  it("parent page redirects /handlers to /overview via correctUrl", async () => {
    setupMultiInstanceParent();
    renderPage({ key: "test_app", tab: "handlers" });
    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/overview");
    });
  });

  it("parent page hides 'instance N' from subtitle meta", async () => {
    setupMultiInstanceParent();
    const { findByTestId } = renderPage({ key: "test_app" });
    expect((await findByTestId("app-subtitle-meta")).textContent).not.toContain("instance");
  });
});
