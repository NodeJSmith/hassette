import { beforeEach, describe, expect, it, vi } from "vitest";

import { createManifest } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import type { AppDetailTab } from "../utils/app-routes";
import { AppDetailPage } from "./app-detail";
import { setupApi } from "./app-detail.test-helpers";

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
vi.mock("../components/shared/confirm-dialog", async () =>
  (await import("./app-detail.test-helpers")).createConfirmDialogStub(),
);

const mockCorrectUrl = vi.fn();
vi.mock("../hooks/use-correct-url", () => ({
  useCorrectUrl: () => mockCorrectUrl,
}));

function renderPage(params: { key: string; tab?: AppDetailTab; handler?: string }) {
  return renderWithAppState(<AppDetailPage params={params} />, { storeOverrides: { uptimeSeconds: 120 } });
}

describe("AppDetailPage header", () => {
  beforeEach(() => {
    mockSearchString = "";
    mockNavigate.mockClear();
    vi.clearAllMocks();
  });

  it("renders app_key in the header", async () => {
    const manifest = createManifest({ app_key: "test_app", display_name: "Motion Sensor App" });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect((await findByTestId("app-title")).textContent).toContain("test_app");
  });

  it("renders action buttons", async () => {
    setupApi(createManifest());
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("action-buttons")).toBeDefined();
  });

  it("renders error display for failed app with error_message", async () => {
    const manifest = createManifest({
      status: "failed",
      error_message: "Module not found: light_controller",
      error_traceback: null,
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("error-display")).toBeDefined();
  });

  it("does not render error display when app has no error_message", async () => {
    const manifest = createManifest({ error_message: null });
    setupApi(manifest);
    const { findByTestId, queryByTestId } = renderPage({ key: "test_app" });
    // Wait for data to load before asserting absence
    await findByTestId("app-title");
    expect(queryByTestId("error-display")).toBeNull();
  });

  it("renders auto-loaded badge when auto_loaded is true", async () => {
    const manifest = createManifest({ auto_loaded: true });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("auto-loaded-badge")).toBeDefined();
  });

  it("does not render auto-loaded badge when auto_loaded is false", async () => {
    const manifest = createManifest({ auto_loaded: false });
    setupApi(manifest);
    const { findByTestId, queryByTestId } = renderPage({ key: "test_app" });
    // Wait for data to load before asserting absence
    await findByTestId("app-title");
    expect(queryByTestId("auto-loaded-badge")).toBeNull();
  });

  it("renders no-autostart badge when autostart is false", async () => {
    const manifest = createManifest({ autostart: false });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    expect(await findByTestId("no-autostart-badge")).toBeDefined();
  });

  it("does not render no-autostart badge when autostart is true", async () => {
    const manifest = createManifest({ autostart: true });
    setupApi(manifest);
    const { findByTestId, queryByTestId } = renderPage({ key: "test_app" });
    await findByTestId("app-title");
    expect(queryByTestId("no-autostart-badge")).toBeNull();
  });

  it("shows filename and class name in subtitle meta", async () => {
    const manifest = createManifest({
      app_key: "test_app",
      filename: "apps/test_app.py",
      class_name: "TestApp",
    });
    setupApi(manifest);
    const { findByTestId } = renderPage({ key: "test_app" });
    const subtitleMeta = await findByTestId("app-subtitle-meta");
    expect(subtitleMeta.textContent).toContain("apps/test_app.py");
    expect(subtitleMeta.textContent).toContain("TestApp");
  });
});
