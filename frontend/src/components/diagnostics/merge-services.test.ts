import { describe, expect, it } from "vitest";

import { createServiceInfo, createServiceStatusEntry } from "../../test/factories";
import { mergeServices } from "./merge-services";

describe("mergeServices", () => {
  it("returns the HTTP seed when no WS updates have arrived", () => {
    const merged = mergeServices([createServiceInfo({ name: "bus", role: "core" })], {});
    expect(merged).toEqual([
      { resource_name: "bus", status: "running", role: "core", ready_phase: null, retry_at: null, exception: null },
    ]);
  });

  it("lets a live WS entry win over the HTTP seed for the same service", () => {
    const merged = mergeServices([createServiceInfo({ name: "bus", status: "running" })], {
      bus: createServiceStatusEntry({ status: "failed", exception: "boom" }),
    });
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({ resource_name: "bus", status: "failed", exception: "boom" });
  });

  it("keeps a WS-only service that the HTTP seed never reported", () => {
    const merged = mergeServices([], { scheduler: createServiceStatusEntry({ resource_name: "scheduler" }) });
    expect(merged.map((s) => s.resource_name)).toEqual(["scheduler"]);
  });

  it("sorts anomalies ahead of running services, then alphabetically within each group", () => {
    const merged = mergeServices(
      [
        createServiceInfo({ name: "websocket" }),
        createServiceInfo({ name: "api" }),
        createServiceInfo({ name: "scheduler", status: "failed" }),
        createServiceInfo({ name: "bus", status: "exhausted_cooling" }),
      ],
      {},
    );
    expect(merged.map((s) => s.resource_name)).toEqual(["bus", "scheduler", "api", "websocket"]);
  });

  it("normalizes absent optional fields to empty string or null", () => {
    const merged = mergeServices(
      [createServiceInfo({ role: undefined, ready_phase: undefined, retry_at: undefined })],
      {},
    );
    expect(merged[0]).toMatchObject({ role: "", ready_phase: null, retry_at: null, exception: null });
  });

  it("normalizes absent optional fields on the WS overlay too, not just the HTTP seed", () => {
    const merged = mergeServices([], {
      bus: createServiceStatusEntry({
        role: undefined,
        ready_phase: undefined,
        retry_at: undefined,
        exception: undefined,
      }),
    });
    expect(merged[0]).toMatchObject({ role: "", ready_phase: null, retry_at: null, exception: null });
  });

  it("returns nothing when neither source reported a service", () => {
    expect(mergeServices([], {})).toEqual([]);
  });
});
