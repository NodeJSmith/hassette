import { describe, expect, it } from "vitest";

import type { components } from "../../api/generated-types";
import type { ServiceStatusEntry } from "../../state/store";
import { mergeServices } from "./merge-services";

type ServiceInfoResponse = components["schemas"]["ServiceInfoResponse"];

function makeServiceInfo(overrides: Partial<ServiceInfoResponse> = {}): ServiceInfoResponse {
  return { name: "bus", status: "running", role: "core", ready_phase: null, retry_at: null, ...overrides };
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

describe("mergeServices", () => {
  it("returns the HTTP seed when no WS updates have arrived", () => {
    const merged = mergeServices([makeServiceInfo({ name: "bus", role: "core" })], {});
    expect(merged).toEqual([
      { resource_name: "bus", status: "running", role: "core", ready_phase: null, retry_at: null, exception: null },
    ]);
  });

  it("lets a live WS entry win over the HTTP seed for the same service", () => {
    const merged = mergeServices([makeServiceInfo({ name: "bus", status: "running" })], {
      bus: makeServiceEntry({ status: "failed", exception: "boom" }),
    });
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({ resource_name: "bus", status: "failed", exception: "boom" });
  });

  it("keeps a WS-only service that the HTTP seed never reported", () => {
    const merged = mergeServices([], { scheduler: makeServiceEntry({ resource_name: "scheduler" }) });
    expect(merged.map((s) => s.resource_name)).toEqual(["scheduler"]);
  });

  it("sorts anomalies ahead of running services, then alphabetically within each group", () => {
    const merged = mergeServices(
      [
        makeServiceInfo({ name: "websocket" }),
        makeServiceInfo({ name: "api" }),
        makeServiceInfo({ name: "scheduler", status: "failed" }),
        makeServiceInfo({ name: "bus", status: "exhausted_cooling" }),
      ],
      {},
    );
    expect(merged.map((s) => s.resource_name)).toEqual(["bus", "scheduler", "api", "websocket"]);
  });

  it("normalizes absent optional fields to empty string or null", () => {
    const merged = mergeServices(
      [makeServiceInfo({ role: undefined, ready_phase: undefined, retry_at: undefined })],
      {},
    );
    expect(merged[0]).toMatchObject({ role: "", ready_phase: null, retry_at: null, exception: null });
  });
});
