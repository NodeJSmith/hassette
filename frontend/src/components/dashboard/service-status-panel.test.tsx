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
    status: "failed",
    previous_status: null,
    exception: null,
    retry_at: null,
    ...overrides,
  };
}

describe("ServiceStatusPanel", () => {
  describe("visibility", () => {
    it("renders nothing when no service statuses are tracked", () => {
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus: signal({}) },
      });
      expect(container.querySelector("[data-testid='service-status-panel']")).toBeNull();
    });

    it("renders nothing when all services are healthy", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "svc1", status: "running" }),
        makeEntry({ resource_name: "svc2", status: "starting" }),
        makeEntry({ resource_name: "svc3", status: "stopped" }),
      ]);
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      expect(container.querySelector("[data-testid='service-status-panel']")).toBeNull();
    });

    it("shows only degraded services, filtering out healthy ones", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "healthy_svc", status: "running" }),
        makeEntry({ resource_name: "broken_svc", status: "failed" }),
      ]);
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      expect(container.querySelector("[data-testid='service-status-row-healthy_svc']")).toBeNull();
      expect(container.querySelector("[data-testid='service-status-row-broken_svc']")).not.toBeNull();
    });
  });

  describe("EXHAUSTED_DEAD rendering", () => {
    it("renders permanent failure label", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "dead_svc", status: "exhausted_dead" }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const label = getByTestId("service-status-label-dead_svc");
      expect(label.textContent).toBe("Permanently failed");
    });

    it("applies danger variant class", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "dead_svc", status: "exhausted_dead" }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const row = getByTestId("service-status-row-dead_svc");
      expect(row.className).toContain("ht-ssp__row--danger");
    });

    it("does not render a countdown timer", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "dead_svc", status: "exhausted_dead" }),
      ]);
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      expect(container.querySelector(".ht-ssp__detail")).toBeNull();
    });
  });

  describe("EXHAUSTED_COOLING rendering", () => {
    const FUTURE_RETRY_AT = Date.now() / 1000 + 300;

    it("renders countdown timer when retry_at is set", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "cooling_svc", status: "exhausted_cooling", retry_at: FUTURE_RETRY_AT }),
      ]);
      const { container } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const countdown = container.querySelector(".ht-ssp__detail--cooling");
      expect(countdown).not.toBeNull();
      expect(countdown!.textContent).toMatch(/Retrying in \d+m/);
    });

    it("renders cooling down label when retry_at is null", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "cooling_svc", status: "exhausted_cooling", retry_at: null }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const label = getByTestId("service-status-label-cooling_svc");
      expect(label.textContent).toBe("Cooling down");
    });

    it("applies warning variant class", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "cooling_svc", status: "exhausted_cooling", retry_at: FUTURE_RETRY_AT }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const row = getByTestId("service-status-row-cooling_svc");
      expect(row.className).toContain("ht-ssp__row--warning");
    });
  });

  describe("failed/crashed rendering", () => {
    it("renders failed services with label", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "broken_svc", status: "failed" }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const label = getByTestId("service-status-label-broken_svc");
      expect(label.textContent).toBe("Failed");
    });

    it("renders crashed services with label", () => {
      const serviceStatus = makeServiceStatus([
        makeEntry({ resource_name: "crashed_svc", status: "crashed" }),
      ]);
      const { getByTestId } = renderWithAppState(<ServiceStatusPanel />, {
        stateOverrides: { serviceStatus },
      });
      const label = getByTestId("service-status-label-crashed_svc");
      expect(label.textContent).toBe("Crashed");
    });
  });
});
