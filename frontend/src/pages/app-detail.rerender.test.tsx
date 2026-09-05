import { act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WsExecutionCompletedPayload } from "../api/ws-types";
import type { ExecutionKind } from "../components/shared/execution-table";
import { appStatusKey, useAppStore } from "../state/store";
import { createManifest } from "../test/factories";
import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import { AppDetailPage } from "./app-detail";
import { setupApi } from "./app-detail.test-helpers";

const mockNavigate = vi.fn();

vi.mock("wouter", () =>
  createWouterMock({
    useLocation: () => ["/apps/test_app", mockNavigate],
    useSearch: () => "",
  }),
);

// Render counter for the page body. `OverviewTab` is not memoized, so it renders exactly once per
// AppDetailPage render — that makes it the seam for asserting the page stayed put.
const counter = vi.hoisted(() => ({ renders: 0 }));

vi.mock("../components/app-detail/overview-tab", () => ({
  OverviewTab: ({ appStatus }: { appStatus?: string }) => {
    counter.renders += 1;
    return <div data-testid="overview-tab">{appStatus}</div>;
  },
}));

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
vi.mock("../components/shared/log-table", async () => (await import("./app-detail.test-helpers")).createLogTableStub());
vi.mock("../components/shared/spinner", async () => (await import("./app-detail.test-helpers")).createSpinnerStub());

vi.mock("../hooks/use-correct-url", () => ({ useCorrectUrl: () => vi.fn() }));

function makeExecution(appKey: string, kind: ExecutionKind): WsExecutionCompletedPayload {
  return { kind, app_key: appKey, instance_index: 0, status: "success", duration_ms: 5 };
}

/** Renders the overview tab and waits for the initial load to settle. */
async function renderSettled() {
  setupApi(createManifest({ app_key: "test_app" }));
  const view = renderWithAppState(<AppDetailPage params={{ key: "test_app" }} />, {
    storeOverrides: { uptimeSeconds: 120 },
  });
  await view.findByTestId("overview-tab");
  return view;
}

describe("AppDetailPage store subscriptions", () => {
  beforeEach(() => {
    counter.renders = 0;
    vi.clearAllMocks();
  });

  it("does not re-render when an unrelated app's status changes", async () => {
    await renderSettled();
    const before = counter.renders;

    act(() => {
      useAppStore.getState().updateAppStatus(appStatusKey("other_app", 0), { status: "failed", index: 0 });
    });

    expect(counter.renders).toBe(before);
  });

  it("re-renders when its own app's status changes", async () => {
    const { findByTestId } = await renderSettled();
    const before = counter.renders;

    act(() => {
      useAppStore.getState().updateAppStatus(appStatusKey("test_app", 0), { status: "failed", index: 0 });
    });

    expect(counter.renders).toBeGreaterThan(before);
    expect((await findByTestId("overview-tab")).textContent).toBe("failed");
  });

  it("does not re-render on an unrelated app's execution completions", async () => {
    await renderSettled();
    const before = counter.renders;

    act(() => {
      useAppStore
        .getState()
        .setExecutionCompleted([makeExecution("other_app", "handler"), makeExecution("other_app", "job")]);
    });

    expect(counter.renders).toBe(before);
  });

  it.each(["handler", "job"] as const)("re-renders on its own app's %s execution completion", async (kind) => {
    await renderSettled();
    const before = counter.renders;

    act(() => {
      useAppStore.getState().setExecutionCompleted([makeExecution("test_app", kind)]);
    });

    expect(counter.renders).toBeGreaterThan(before);
  });
});
