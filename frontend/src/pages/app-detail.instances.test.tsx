import { signal } from "@preact/signals";
import { fireEvent } from "@testing-library/preact";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

// Stub child components not under test
vi.mock("../components/shared/error-banner", () => ({
  ErrorBanner: ({ "data-testid": testId }: { "data-testid"?: string }) => (
    <div data-testid={testId ?? "error-banner"} />
  ),
}));
vi.mock("../components/app-detail/handlers-tab", () => ({
  HandlersTab: () => <div data-testid="handlers-tab" />,
}));
vi.mock("../components/app-detail/code-tab", () => ({
  CodeTab: () => <div data-testid="code-tab" />,
}));
vi.mock("../components/app-detail/config-tab", () => ({
  ConfigTab: () => <div data-testid="config-tab" />,
}));
vi.mock("../components/app-detail/overview-tab", () => ({
  OverviewTab: () => <div data-testid="overview-tab" />,
}));
vi.mock("../components/shared/log-table", () => ({
  useLogTable: () => ({
    tableProps: {
      visibleColumns: [],
      sort: { key: "timestamp", dir: "desc" },
      onSort: () => {},
      columnFilters: {},
      entries: [],
      selectedKey: null,
      onRowClick: () => {},
      isMobile: false,
    },
    drawerProps: { selectedKey: null, entries: [], onClose: () => {}, onNavigate: () => {} },
    columnFilters: {},
    countLabel: "0 entries",
    hasActiveFilter: false,
    resetFilters: () => {},
    livePaused: false,
    resetSort: () => {},
    columnPickerProps: { selectedColumns: [], viewportHidden: new Set(), onToggle: () => {}, onReset: () => {} },
    isMobile: false,
    isEmpty: true,
    isLoading: false,
  }),
  LogTableView: () => <div data-testid="log-table" />,
  LogTableWithDrawer: ({ children }: { children: preact.ComponentChildren }) => (
    <div data-testid="log-table-drawer">{children}</div>
  ),
}));
vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));
vi.mock("../components/shared/confirm-dialog", () => ({
  ConfirmDialog: () => <div data-testid="confirm-dialog" />,
}));

const mockCorrectUrl = vi.fn();
vi.mock("../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

function renderPage(params: { key: string; tab?: AppDetailTab; handler?: string }) {
  return renderWithAppState(<AppDetailPage params={params} />, { stateOverrides: { uptimeSeconds: signal(120) } });
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
    fireEvent.click(inst1Btn);
    // Should navigate to /apps/test_app/logs?instance=1
    expect(mockNavigate).toHaveBeenCalledWith("/apps/test_app/logs?instance=1");
  });

  it("multi-instance parent overview navigates using ?instance= query param", async () => {
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
    fireEvent.click(card0);
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
