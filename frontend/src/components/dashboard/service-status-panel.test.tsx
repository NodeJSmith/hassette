import { describe, expect, it } from "vitest";
import { signal } from "@preact/signals";
import { renderWithAppState } from "../../test/render-helpers";
import { ServiceStatusPanel } from "./service-status-panel";
import type { ServiceStatusEntry } from "../../state/create-app-state";

function makeServiceStatus(entries: ServiceStatusEntry[]) {
  const map: Record<string, ServiceStatusEntry> = {};
  for (const entry of entries) {
    map[entry.resource_name] = entry;
  }
  return signal(map);
}

function makeEntry(overrides: Partial<ServiceStatusEntry> = {}): ServiceStatusEntry {
  return {
    resource_name: "test_service",
    role: "service",
    status: "running",
    previous_status: null,
    exception: null,
    retry_at: null,
    ...overrides,
  };
}

describe("ServiceStatusPanel", () => {
  describe("empty state", () => {
    it("renders nothing when no service statuses are tracked", () => {
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus: signal({}) },
      });
      expect(container.querySelector("[data-testid='service-status-panel']")).toBeNull();
    });
  });

  describe("EXHAUSTED_DEAD rendering", () => {
    it("renders permanent failure indicator for exhausted_dead status", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "dead_svc", status: "exhausted_dead", retry_at: null }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const label = getByTestId("service-status-label-dead_svc");
      expect(label.textContent).toBe("Permanently failed");
    });

    it("applies dead row class for exhausted_dead", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "dead_svc", status: "exhausted_dead", retry_at: null }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const row = getByTestId("service-status-row-dead_svc");
      expect(row.className).toContain("ht-service-status-panel__row--dead");
    });

    it("does not render a countdown timer for exhausted_dead", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "dead_svc", status: "exhausted_dead", retry_at: null }),
      ]);
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      expect(container.querySelector(".ht-service-status-panel__countdown")).toBeNull();
    });

    it("marks panel as urgent when a dead service is present", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "dead_svc", status: "exhausted_dead", retry_at: null }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const panel = getByTestId("service-status-panel");
      expect(panel.className).toContain("ht-card--urgent");
    });
  });

  describe("EXHAUSTED_COOLING rendering", () => {
    const FUTURE_RETRY_AT = Date.now() / 1000 + 300; // 5 minutes from now

    it("renders cooling row class for exhausted_cooling", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "cooling_svc", status: "exhausted_cooling", retry_at: FUTURE_RETRY_AT }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const row = getByTestId("service-status-row-cooling_svc");
      expect(row.className).toContain("ht-service-status-panel__row--cooling");
    });

    it("renders countdown timer for exhausted_cooling with retry_at", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "cooling_svc", status: "exhausted_cooling", retry_at: FUTURE_RETRY_AT }),
      ]);
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const countdown = container.querySelector(".ht-service-status-panel__countdown");
      expect(countdown).not.toBeNull();
      // Countdown should show "Retrying in Xm Ys"
      expect(countdown!.textContent).toMatch(/Retrying in \d+m/);
    });

    it("renders fallback label for exhausted_cooling without retry_at", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "cooling_svc", status: "exhausted_cooling", retry_at: null }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const label = getByTestId("service-status-label-cooling_svc");
      expect(label.textContent).toBe("Cooling down");
    });

    it("marks panel as urgent when a cooling service is present", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "cooling_svc", status: "exhausted_cooling", retry_at: FUTURE_RETRY_AT }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const panel = getByTestId("service-status-panel");
      expect(panel.className).toContain("ht-card--urgent");
    });
  });

  describe("normal status rendering", () => {
    it("renders running services without countdown or dead label", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "running_svc", status: "running", retry_at: null }),
      ]);
      const { getByTestId, container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const label = getByTestId("service-status-label-running_svc");
      expect(label.textContent).toBe("running");
      expect(container.querySelector(".ht-service-status-panel__countdown")).toBeNull();
    });

    it("does not mark panel as urgent when all services are running", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "svc1", status: "running" }),
        makeEntry({ resource_name: "svc2", status: "starting" }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const panel = getByTestId("service-status-panel");
      expect(panel.className).not.toContain("ht-card--urgent");
    });

    it("renders multiple services in the list", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "svc1", status: "running" }),
        makeEntry({ resource_name: "svc2", status: "failed" }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      expect(getByTestId("service-status-row-svc1")).toBeDefined();
      expect(getByTestId("service-status-row-svc2")).toBeDefined();
    });
  });
});
