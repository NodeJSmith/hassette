import { http, HttpResponse } from "msw";

import type { AppManifest, JobData, ListenerData } from "../api/endpoints";
import { createInstance, createManifest } from "../test/factories";
import { server } from "../test/server";

/** Registers MSW handlers for the manifest/listeners/jobs endpoints AppDetailPage queries. */
export function setupApi(manifest: AppManifest, listeners: ListenerData[] = [], jobs: JobData[] = []) {
  server.use(
    http.get("/api/apps/:app_key/manifest", () => HttpResponse.json(manifest)),
    http.get("/api/telemetry/app/:app_key/listeners", () => HttpResponse.json(listeners)),
    http.get("/api/telemetry/app/:app_key/jobs", () => HttpResponse.json(jobs)),
  );
}

/** Registers a 2-instance manifest (no ?instance= param selected) for multi-instance parent-view tests. */
export function setupMultiInstanceParent() {
  const manifest = createManifest({
    instance_count: 2,
    instances: [
      createInstance({ index: 0, instance_name: "inst_0", status: "running" }),
      createInstance({ index: 1, instance_name: "inst_1", status: "stopped" }),
    ],
  });
  setupApi(manifest);
}

/** Stub factory for `../components/shared/error-banner`, shared by all app-detail.*.test.tsx files. */
export function createErrorBannerStub() {
  return {
    ErrorBanner: ({ "data-testid": testId }: { "data-testid"?: string }) => (
      <div data-testid={testId ?? "error-banner"} />
    ),
  };
}

/** Non-capturing stub factory for `../components/app-detail/handlers-tab` — use the capturing variant instead when the test asserts on `HandlersTab` props. */
export function createHandlersTabStub() {
  return { HandlersTab: () => <div data-testid="handlers-tab" /> };
}

/** Stub factory for `../components/app-detail/code-tab`, shared by all app-detail.*.test.tsx files. */
export function createCodeTabStub() {
  return { CodeTab: () => <div data-testid="code-tab" /> };
}

/** Stub factory for `../components/app-detail/config-tab`, shared by all app-detail.*.test.tsx files. */
export function createConfigTabStub() {
  return { ConfigTab: () => <div data-testid="config-tab" /> };
}

/** Stub factory for `../components/app-detail/overview-tab`, shared by all app-detail.*.test.tsx files. */
export function createOverviewTabStub() {
  return { OverviewTab: () => <div data-testid="overview-tab" /> };
}

/** Stub factory for `../components/shared/log-table`, shared by all app-detail.*.test.tsx files. */
export function createLogTableStub() {
  return {
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
  };
}

/** Stub factory for `../components/shared/spinner`, shared by all app-detail.*.test.tsx files. */
export function createSpinnerStub() {
  return { Spinner: () => <div data-testid="spinner" /> };
}

/** Stub factory for `../components/shared/confirm-dialog`, shared by all app-detail.*.test.tsx files. */
export function createConfirmDialogStub() {
  return { ConfirmDialog: () => <div data-testid="confirm-dialog" /> };
}
