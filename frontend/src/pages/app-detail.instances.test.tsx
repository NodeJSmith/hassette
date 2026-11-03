import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { appStatusKey, type AppStore } from "../state/store";
import { createBlockingFinding } from "../test/blocking-fixtures";
import { createAppSummary, createInstance } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
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

  it("renders multi-instance parent overview when instance_count > 1 and no instance param", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("instance-grid")).toBeDefined();
  });

  it("parent overview lists blocking findings across every instance", async () => {
    setupMultiInstanceParent();
    const seen: URL[] = [];
    server.use(
      http.get("/api/telemetry/app/:app_key/blocking", ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json({ findings: [createBlockingFinding()], truncated: false });
      }),
    );
    const { findByTestId } = renderPage({ key: "test_app" });

    expect((await findByTestId("overview-blocking-findings")).textContent).toContain("all instances");
    expect(seen[0]?.searchParams.has("instance_name")).toBe(false);
  });

  it("requests listeners and jobs for every instance when no instance is picked", async () => {
    setupMultiInstanceParent();
    const seen: URL[] = [];
    server.use(
      http.get("/api/telemetry/app/:app_key/listeners", ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json([]);
      }),
    );
    const { findByTestId } = renderPage({ key: "test_app" });
    await findByTestId("instance-grid");
    expect(seen[0]?.searchParams.has("instance_name")).toBe(false);
  });

  it("requests the picked instance's listeners by name", async () => {
    setupMultiInstanceParent();
    mockSearchString = "instance=inst_1";
    const seen: URL[] = [];
    server.use(
      http.get("/api/telemetry/app/:app_key/listeners", ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json([]);
      }),
    );
    const { findByTestId } = renderPage({ key: "test_app" });
    await findByTestId("app-title");
    await vi.waitFor(() => expect(seen[0]?.searchParams.get("instance_name")).toBe("inst_1"));
  });

  it("renders instance grid cards with instance names", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("instance-card-inst_0")).toBeDefined();
    expect(await findByTestId("instance-card-inst_1")).toBeDefined();
  });

  it("instance grid card reflects live appStatus over stale manifest status", async () => {
    // Reproduces a stale-status report: the manifest fetch says inst_0 is still "running",
    // but a WS app_status_changed message (mirrored into the appStatus store) already marked
    // it "stopped". The grid must show the live value, not the cached manifest snapshot.
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage(
      { key: "test_app" },
      { appStatus: { [appStatusKey("test_app", "inst_0")]: { status: "stopped", instance_name: "inst_0" } } },
    );

    const card0 = await findByTestId("instance-card-inst_0");
    expect(card0.textContent).toContain("stopped");
    expect(card0.textContent).not.toContain("running");
  });

  it("instance grid card suppresses a stale cached error once the live status shows recovery", async () => {
    // Reproduces a stale-error report: the manifest fetch cached inst_0's error_message from
    // before it recovered, but a WS app_status_changed message (mirrored into the appStatus
    // store) already reports it "running" with no exception. The grid must not keep showing
    // the old error alongside the now-live "running" status.
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "failed", error_message: "boom" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage(
      { key: "test_app" },
      {
        appStatus: {
          [appStatusKey("test_app", "inst_0")]: { status: "running", instance_name: "inst_0", exception: null },
        },
      },
    );

    const card0 = await findByTestId("instance-card-inst_0");
    expect(card0.textContent).not.toContain("boom");
  });

  it("instance grid card shows a newly live exception the cached manifest never had", async () => {
    // Reproduces the inverse: the manifest fetch cached inst_0 as healthy, but a WS
    // app_status_changed message already reports it "failed" with a live exception. The grid
    // must surface that exception, not the cached (empty) error_message.
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage(
      { key: "test_app" },
      {
        appStatus: {
          [appStatusKey("test_app", "inst_0")]: { status: "failed", instance_name: "inst_0", exception: "kaboom" },
        },
      },
    );

    const card0 = await findByTestId("instance-card-inst_0");
    expect(card0.textContent).toContain("kaboom");
  });

  it("instance switcher status dot reflects live appStatus over stale manifest status", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=inst_1";
    const { findByTestId } = renderPage(
      { key: "test_app" },
      { appStatus: { [appStatusKey("test_app", "inst_0")]: { status: "stopped", instance_name: "inst_0" } } },
    );

    const switcherBtn0 = await findByTestId("switcher-instance-inst_0");
    // StatusShape is a bare aria-hidden SVG with no status text or data attribute — "stopped"
    // renders as a "mute" kind (stroke-only circle, fill="none"), "running" as "ok" (filled
    // circle, fill="var(--ok-vivid)"). Assert on the fill to distinguish them.
    expect(switcherBtn0.querySelector("svg circle")?.getAttribute("fill")).toBe("none");
  });

  it("renders instance count badge in parent overview header", async () => {
    const manifest = createAppSummary({
      instance_count: 3,
      instances: [
        createInstance({ instance_name: "a", status: "running" }),
        createInstance({ instance_name: "b", status: "running" }),
        createInstance({ instance_name: "c", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect((await findByTestId("instance-count-badge")).textContent).toContain("3");
  });

  it("renders instance switcher in detail header when on instance view with siblings", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    // inst_0 is specified via query param
    mockSearchString = "instance=inst_0";
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("instance-switcher")).toBeDefined();
  });

  it("instance switcher navigates to current tab path with instance query param", async () => {
    const user = userEvent.setup();
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=inst_0";
    const { findByTestId } = renderPage({ key: "test_app", tab: "logs" });
    // Click instance 1 in the switcher
    const inst1Btn = await findByTestId("switcher-instance-inst_1");
    await user.click(inst1Btn);
    // Should navigate to /apps/test_app/logs?instance=inst_1
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/logs?instance=inst_1");
  });

  it("multi-instance parent overview navigates using ?instance= query param", async () => {
    const user = userEvent.setup();
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "stopped" }),
      ],
    });
    setupApi(manifest);
    // No instance param = parent overview
    const { findByTestId } = renderPage({ key: "test_app" });
    // Click an instance card
    const card0 = await findByTestId("instance-card-inst_0");
    await user.click(card0);
    // Should navigate to /apps/test_app/overview?instance=inst_0
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/overview?instance=inst_0");
  });

  it("reads instance from ?instance= query param for multi-instance detail view", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=inst_1";
    const { findByTestId } = renderPage({ key: "test_app" });
    // Instance switcher should be rendered (not parent overview)
    await findByTestId("instance-switcher");
    // The instance 1 button should be active
    const inst1Btn = await findByTestId("switcher-instance-inst_1");
    expect(inst1Btn.getAttribute("aria-selected")).toBe("true");
  });

  it("drops an instance param that names no instance via correctUrl", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=no_such_instance";
    renderPage({ key: "test_app", tab: "handlers" });
    // Wait for manifests to load, then check correctUrl was called
    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers");
    });
  });

  it("keeps a tracked instance orphaned by a config shrink addressable", async () => {
    // Config shrank to one instance while "orphan" was still running. The manifest lists it
    // alongside the configured names, so its page (and Stop control) stays reachable.
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "orphan", status: "running", in_current_config: false }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=orphan";
    const { findByTestId } = renderPage({ key: "test_app", tab: "handlers" });

    await findByTestId("app-title");
    expect(mockCorrectUrl).not.toHaveBeenCalled();
  });

  it("corrects an instance name when the manifest omits its instances array", async () => {
    // `instances` is optional on AppSummary, so the membership check can find nothing to
    // consult. With no listed names, no name is addressable and the correction must still fire.
    const manifest = createAppSummary({ instance_count: 2, instances: undefined });
    setupApi(manifest);
    mockSearchString = "instance=inst_5";
    renderPage({ key: "test_app", tab: "handlers" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers");
    });
  });

  it("corrects a numeric instance query param (an old bookmark) to the same page with no instance param", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=0";

    renderPage({ key: "test_app", tab: "logs" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/logs");
    });
  });

  it.each(["  ", "0x1"])("corrects an unusable or unknown instance query param %j", async (instanceParam) => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = `instance=${instanceParam}`;

    renderPage({ key: "test_app", tab: "logs" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/logs");
    });
  });

  it("preserves code line deep links when correcting invalid instance params", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "line=42&instance=0";

    renderPage({ key: "test_app", tab: "code" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/code?line=42");
    });
  });

  it("corrects a numeric instance query param on handlers without redirecting to parent overview", async () => {
    const manifest = createAppSummary({
      instance_count: 2,
      instances: [
        createInstance({ instance_name: "inst_0", status: "running" }),
        createInstance({ instance_name: "inst_1", status: "running" }),
      ],
    });
    setupApi(manifest);
    mockSearchString = "instance=0";

    renderPage({ key: "test_app", tab: "handlers" });

    await vi.waitFor(() => {
      expect(mockCorrectUrl).toHaveBeenCalledWith("/apps/test_app/handlers");
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
