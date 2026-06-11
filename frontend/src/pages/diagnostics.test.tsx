import { signal } from "@preact/signals";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../api/generated-types";
import type { ServiceStatusEntry } from "../state/create-app-state";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
import { DiagnosticsPage } from "./diagnostics";

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

type SystemStatusResponse = components["schemas"]["SystemStatusResponse"];
type ServiceInfoResponse = components["schemas"]["ServiceInfoResponse"];

function makeSystemStatus(overrides: Partial<SystemStatusResponse> = {}): SystemStatusResponse {
  return {
    status: "ok",
    websocket_connected: true,
    uptime_seconds: 120,
    entity_count: 10,
    app_count: 2,
    services_running: ["bus", "scheduler"],
    services: [],
    version: "1.0.0",
    boot_issues: [],
    log_records_dropped: 0,
    ...overrides,
  };
}

function makeServiceInfo(overrides: Partial<ServiceInfoResponse> = {}): ServiceInfoResponse {
  return {
    name: "bus",
    status: "running",
    role: "core",
    ready_phase: null,
    retry_at: null,
    ...overrides,
  };
}

function makeServiceEntry(overrides: Partial<ServiceStatusEntry> = {}): ServiceStatusEntry {
  return {
    resource_name: "bus",
    role: "core",
    status: "running",
    previous_status: null,
    exception: null,
    retry_at: null,
    ready: true,
    ready_phase: null,
    ...overrides,
  };
}

describe("DiagnosticsPage", () => {
  it("renders a spinner while loading", () => {
    // Never resolve so the spinner stays visible synchronously
    server.use(http.get("/api/health", () => new Promise(() => {})));
    const { getByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("shows error state on fetch failure", async () => {
    server.use(http.get("/api/health", () => HttpResponse.json(null, { status: 500 })));
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    const alert = await findByTestId("diag-load-error");
    expect(alert.textContent).toBeTruthy();
  });

  it("renders stats strip and services panel after load; clean boot/telemetry panels stay hidden", async () => {
    const { findByTestId, queryByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-stats-strip")).toBeDefined();
    expect(await findByTestId("diag-services-panel")).toBeDefined();
    expect(queryByTestId("diag-boot-panel")).toBeNull();
    expect(queryByTestId("diag-telemetry-panel")).toBeNull();
  });

  it("shows empty state when no services returned from HTTP seed", async () => {
    server.use(http.get("/api/health", () => HttpResponse.json(makeSystemStatus({ services: [] }))));
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-services-empty")).toBeDefined();
  });

  it("renders service rows from HTTP seed", async () => {
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json(
          makeSystemStatus({
            services: [
              makeServiceInfo({ name: "bus", status: "running" }),
              makeServiceInfo({ name: "scheduler", status: "running" }),
            ],
          }),
        ),
      ),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-service-row-bus")).toBeDefined();
    expect(await findByTestId("diag-service-row-scheduler")).toBeDefined();
  });

  it("overlays WS serviceStatus on top of HTTP seed", async () => {
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json(
          makeSystemStatus({
            services: [makeServiceInfo({ name: "bus", status: "running" })],
          }),
        ),
      ),
    );
    const serviceStatus = signal<Record<string, ServiceStatusEntry>>({
      bus: makeServiceEntry({ resource_name: "bus", status: "exhausted_cooling", retry_at: null }),
    });
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />, {
      stateOverrides: { serviceStatus },
    });
    // WS status wins
    const statusEl = await findByTestId("diag-service-status-bus");
    expect(statusEl.textContent).toBe("exhausted_cooling");
  });

  it("shows a cooling service with relative retry timestamp", async () => {
    const futureRetryAt = Date.now() / 1000 + 180; // 3 minutes from now
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json(
          makeSystemStatus({
            services: [
              makeServiceInfo({ name: "db", status: "exhausted_cooling", role: "storage", retry_at: futureRetryAt }),
            ],
          }),
        ),
      ),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    const retryEl = await findByTestId("diag-service-retry-db");
    expect(retryEl.textContent).toMatch(/retry in \d+m/);
  });

  it("shows stale indicator when WS is disconnected", async () => {
    const connection = signal<import("../state/create-app-state").ConnectionStatus>("disconnected");
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />, {
      stateOverrides: { connection },
    });
    expect(await findByTestId("diag-services-stale")).toBeDefined();
  });

  it("does not show stale indicator when WS is connected", async () => {
    const connection = signal<import("../state/create-app-state").ConnectionStatus>("connected");
    const { findByTestId, queryByTestId } = renderWithAppState(<DiagnosticsPage />, {
      stateOverrides: { connection },
    });
    await findByTestId("diag-services-panel");
    expect(queryByTestId("diag-services-stale")).toBeNull();
  });

  it("hides the boot issues panel when startup was clean", async () => {
    server.use(http.get("/api/health", () => HttpResponse.json(makeSystemStatus({ boot_issues: [] }))));
    const { findByTestId, queryByTestId } = renderWithAppState(<DiagnosticsPage />);
    await findByTestId("diag-services-panel");
    expect(queryByTestId("diag-boot-panel")).toBeNull();
  });

  it("renders boot issues sorted by severity (errors first)", async () => {
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json(
          makeSystemStatus({
            boot_issues: [
              { severity: "warn", label: "Config warning", detail: "check your config" },
              { severity: "err", label: "Critical error", detail: "failed to load something" },
            ],
          }),
        ),
      ),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    const first = await findByTestId("diag-boot-label-0");
    const second = await findByTestId("diag-boot-label-1");
    expect(first.textContent).toBe("Critical error");
    expect(second.textContent).toBe("Config warning");
  });

  it("renders boot issue labels and details", async () => {
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json(
          makeSystemStatus({
            boot_issues: [{ severity: "err", label: "Some error", detail: "The full detail text" }],
          }),
        ),
      ),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect((await findByTestId("diag-boot-label-0")).textContent).toBe("Some error");
    expect((await findByTestId("diag-boot-detail-0")).textContent).toBe("The full detail text");
  });

  it("hides the telemetry panel when all counters are zero", async () => {
    const { findByTestId, queryByTestId } = renderWithAppState(<DiagnosticsPage />);
    await findByTestId("diag-services-panel");
    expect(queryByTestId("diag-telemetry-panel")).toBeNull();
  });

  it("renders per-category drop counters when non-zero", async () => {
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />, {
      stateOverrides: {
        droppedOverflow: signal(5),
        droppedExhausted: signal(3),
        droppedShutdown: signal(2),
        errorHandlerFailures: signal(0),
      },
    });
    await findByTestId("diag-telemetry-panel");
    // Each row should be present
    expect(await findByTestId("diag-drop-overflow")).toBeDefined();
    expect(await findByTestId("diag-drop-exhausted")).toBeDefined();
    expect(await findByTestId("diag-drop-shutdown")).toBeDefined();
    expect(await findByTestId("diag-drop-error-handler")).toBeDefined();
    // Overflow row shows correct count
    const overflowRow = await findByTestId("diag-drop-overflow");
    expect(overflowRow.textContent).toContain("5");
  });

  it("shows degraded banner when telemetryDegraded is true", async () => {
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />, {
      stateOverrides: {
        telemetryDegraded: signal(true),
        droppedOverflow: signal(1),
      },
    });
    expect(await findByTestId("diag-telemetry-degraded")).toBeDefined();
  });

  it("shows degraded banner without drop rows when all counters are zero", async () => {
    const { findByTestId, queryByTestId } = renderWithAppState(<DiagnosticsPage />, {
      stateOverrides: { telemetryDegraded: signal(true) },
    });
    expect(await findByTestId("diag-telemetry-degraded")).toBeDefined();
    expect(queryByTestId("diag-drop-overflow")).toBeNull();
  });

  it("service row shows ready_phase text for a non-running service", async () => {
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json(
          makeSystemStatus({
            services: [
              makeServiceInfo({ name: "db", status: "starting", role: "storage", ready_phase: "migrating schema" }),
            ],
          }),
        ),
      ),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    const phaseEl = await findByTestId("diag-service-phase-db");
    expect(phaseEl.textContent).toBe("migrating schema");
  });

  it("hides status text and phase for running services (the dot carries the signal)", async () => {
    server.use(
      http.get("/api/health", () =>
        HttpResponse.json(
          makeSystemStatus({
            services: [makeServiceInfo({ name: "bus", status: "running", ready_phase: "Bus initialized" })],
          }),
        ),
      ),
    );
    const { findByTestId, queryByTestId } = renderWithAppState(<DiagnosticsPage />);
    await findByTestId("diag-service-row-bus");
    expect(queryByTestId("diag-service-status-bus")).toBeNull();
    expect(queryByTestId("diag-service-phase-bus")).toBeNull();
  });
});
