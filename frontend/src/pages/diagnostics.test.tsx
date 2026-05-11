import { describe, expect, it, vi, beforeEach } from "vitest";
import { signal } from "@preact/signals";
import { DiagnosticsPage } from "./diagnostics";
import { renderWithAppState } from "../test/render-helpers";
import { getSystemStatus } from "../api/endpoints";
import type { SystemStatus } from "../api/endpoints";
import type { ServiceStatusEntry } from "../state/create-app-state";

vi.mock("../components/shared/spinner", () => ({
  Spinner: () => <div data-testid="spinner" />,
}));

vi.mock("../api/endpoints", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/endpoints")>();
  return {
    ...original,
    getSystemStatus: vi.fn(),
  };
});

const mockedGetSystemStatus = getSystemStatus as ReturnType<typeof vi.fn>;

function makeSystemStatus(overrides: Partial<SystemStatus> = {}): SystemStatus {
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
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetSystemStatus.mockResolvedValue(makeSystemStatus());
  });

  it("renders a spinner while loading", () => {
    // Never resolve
    mockedGetSystemStatus.mockImplementation(() => new Promise(() => {}));
    const { getByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(getByTestId("spinner")).toBeDefined();
  });

  it("renders all three sections after load", async () => {
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-services-panel")).toBeDefined();
    expect(await findByTestId("diag-boot-panel")).toBeDefined();
    expect(await findByTestId("diag-telemetry-panel")).toBeDefined();
  });

  it("shows empty state when no services returned from HTTP seed", async () => {
    mockedGetSystemStatus.mockResolvedValue(makeSystemStatus({ services: [] }));
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-services-empty")).toBeDefined();
  });

  it("renders service rows from HTTP seed", async () => {
    mockedGetSystemStatus.mockResolvedValue(
      makeSystemStatus({
        services: [
          { name: "bus", status: "running", role: "core", ready_phase: null, retry_at: null },
          { name: "scheduler", status: "running", role: "core", ready_phase: null, retry_at: null },
        ],
      }),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-service-row-bus")).toBeDefined();
    expect(await findByTestId("diag-service-row-scheduler")).toBeDefined();
  });

  it("overlays WS serviceStatus on top of HTTP seed", async () => {
    mockedGetSystemStatus.mockResolvedValue(
      makeSystemStatus({
        services: [
          { name: "bus", status: "running", role: "core", ready_phase: null, retry_at: null },
        ],
      }),
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
    mockedGetSystemStatus.mockResolvedValue(
      makeSystemStatus({
        services: [
          { name: "db", status: "exhausted_cooling", role: "storage", ready_phase: null, retry_at: futureRetryAt },
        ],
      }),
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

  it("shows clean startup when no boot issues", async () => {
    mockedGetSystemStatus.mockResolvedValue(makeSystemStatus({ boot_issues: [] }));
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-boot-clean")).toBeDefined();
  });

  it("renders boot issues sorted by severity (errors first)", async () => {
    mockedGetSystemStatus.mockResolvedValue(
      makeSystemStatus({
        boot_issues: [
          { severity: "warn", label: "Config warning", detail: "check your config" },
          { severity: "err", label: "Critical error", detail: "failed to load something" },
        ],
      }),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    const first = await findByTestId("diag-boot-label-0");
    const second = await findByTestId("diag-boot-label-1");
    expect(first.textContent).toBe("Critical error");
    expect(second.textContent).toBe("Config warning");
  });

  it("renders boot issue labels and details", async () => {
    mockedGetSystemStatus.mockResolvedValue(
      makeSystemStatus({
        boot_issues: [
          { severity: "err", label: "Some error", detail: "The full detail text" },
        ],
      }),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect((await findByTestId("diag-boot-label-0")).textContent).toBe("Some error");
    expect((await findByTestId("diag-boot-detail-0")).textContent).toBe("The full detail text");
  });

  it("shows 'No telemetry drops.' when all counters are zero", async () => {
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    expect(await findByTestId("diag-no-drops")).toBeDefined();
  });

  it("renders per-category drop counters when non-zero", async () => {
    const { findByTestId, queryByTestId } = renderWithAppState(<DiagnosticsPage />, {
      stateOverrides: {
        droppedOverflow: signal(5),
        droppedExhausted: signal(3),
        droppedNoSession: signal(1),
        droppedShutdown: signal(2),
        errorHandlerFailures: signal(0),
      },
    });
    await findByTestId("diag-telemetry-panel");
    // No-drops message should be gone
    expect(queryByTestId("diag-no-drops")).toBeNull();
    // Each row should be present
    expect(await findByTestId("diag-drop-overflow")).toBeDefined();
    expect(await findByTestId("diag-drop-exhausted")).toBeDefined();
    expect(await findByTestId("diag-drop-no-session")).toBeDefined();
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

  it("service row shows ready_phase text", async () => {
    mockedGetSystemStatus.mockResolvedValue(
      makeSystemStatus({
        services: [
          { name: "db", status: "running", role: "storage", ready_phase: "migrating schema", retry_at: null },
        ],
      }),
    );
    const { findByTestId } = renderWithAppState(<DiagnosticsPage />);
    const phaseEl = await findByTestId("diag-service-phase-db");
    expect(phaseEl.textContent).toBe("migrating schema");
  });
});
