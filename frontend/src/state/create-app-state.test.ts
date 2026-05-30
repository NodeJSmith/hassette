import { describe, expect, it } from "vitest";

import type { WsLogPayload } from "../api/ws-types";
import { createAppState, createLogStore } from "./create-app-state";

function createLogEntry(seq: number): WsLogPayload {
  return {
    seq,
    timestamp: seq * 1000,
    level: "INFO",
    logger_name: "test",
    func_name: "test_func",
    lineno: 1,
    message: `msg-${seq}`,
    exc_info: null,
    app_key: null,
    execution_id: null,
    instance_name: null,
    instance_index: null,
    source_tier: null,
  };
}

describe("createAppState", () => {
  it("creates independent instances", () => {
    const a = createAppState();
    const b = createAppState();

    a.theme.value = "dark";
    expect(b.theme.value).toBe("light"); // not affected

    a.tick.value = 5;
    expect(b.tick.value).toBe(0);
  });

  it("does not have sessionId signal", () => {
    const state = createAppState();
    expect("sessionId" in state).toBe(false);
  });

  it("does not have sessionScope signal", () => {
    const state = createAppState();
    expect("sessionScope" in state).toBe(false);
  });

  it("has timePreset signal defaulting to since-restart", () => {
    const state = createAppState();
    expect(state.timePreset.value).toBe("since-restart");
  });

  it("has uptimeSeconds signal defaulting to null", () => {
    const state = createAppState();
    expect(state.uptimeSeconds.value).toBeNull();
  });

  it("has executionCompleted signal defaulting to null", () => {
    const state = createAppState();
    expect(state.executionCompleted.value).toBeNull();
  });

  it("has urlWindowParam signal defaulting to null", () => {
    const state = createAppState();
    expect(state.urlWindowParam.value).toBeNull();
  });

  it("effectiveTimePreset falls back to timePreset when urlWindowParam is null", () => {
    const state = createAppState();
    state.timePreset.value = "24h";
    state.urlWindowParam.value = null;
    expect(state.effectiveTimePreset.value).toBe("24h");
  });

  it("effectiveTimePreset returns urlWindowParam when set", () => {
    const state = createAppState();
    state.timePreset.value = "since-restart";
    state.urlWindowParam.value = "7d";
    expect(state.effectiveTimePreset.value).toBe("7d");
  });

  it("effectiveTimePreset updates reactively when urlWindowParam changes", () => {
    const state = createAppState();
    state.timePreset.value = "1h";

    expect(state.effectiveTimePreset.value).toBe("1h");

    state.urlWindowParam.value = "24h";
    expect(state.effectiveTimePreset.value).toBe("24h");

    state.urlWindowParam.value = null;
    expect(state.effectiveTimePreset.value).toBe("1h");
  });

  it("writing to urlWindowParam does not affect timePreset (no localStorage write)", () => {
    const state = createAppState();
    const initialTimePreset = state.timePreset.value;

    state.urlWindowParam.value = "7d";

    // timePreset is unchanged — urlWindowParam is page-scoped, not persisted
    expect(state.timePreset.value).toBe(initialTimePreset);
  });

  it("urlWindowParam and effectiveTimePreset are independent across instances", () => {
    const a = createAppState();
    const b = createAppState();

    a.urlWindowParam.value = "7d";
    expect(b.urlWindowParam.value).toBeNull();
    expect(b.effectiveTimePreset.value).toBe("since-restart");
  });

  it("timePreset and uptimeSeconds are independent across instances", () => {
    const a = createAppState();
    const b = createAppState();

    a.timePreset.value = "1h";
    expect(b.timePreset.value).toBe("since-restart");

    a.uptimeSeconds.value = 300;
    expect(b.uptimeSeconds.value).toBeNull();
  });

  it("log store push/toArray are independent across instances", () => {
    const a = createAppState();
    const b = createAppState();

    a.logs.push({
      seq: 1,
      timestamp: 0,
      level: "INFO",
      logger_name: "",
      func_name: "",
      lineno: 0,
      message: "test",
      exc_info: null,
      app_key: null,
      execution_id: null,
      instance_name: null,
      instance_index: null,
      source_tier: null,
    });

    expect(a.logs.toArray()).toHaveLength(1);
    expect(a.logs.version.value).toBe(1);
    expect(b.logs.toArray()).toHaveLength(0);
    expect(b.logs.version.value).toBe(0);
  });
});

describe("LogStore clear", () => {
  it("resets buffer and increments version", () => {
    const store = createLogStore();
    const versionBefore = store.version.value;

    store.push(createLogEntry(1));
    store.push(createLogEntry(2));
    store.push(createLogEntry(3));

    expect(store.toArray()).toHaveLength(3);
    const versionAfterPush = store.version.value;
    expect(versionAfterPush).toBeGreaterThan(versionBefore);

    store.clear();

    expect(store.toArray()).toHaveLength(0);
    expect(store.version.value).toBeGreaterThan(versionAfterPush);
  });

  it("allows push after clear", () => {
    const store = createLogStore();

    store.push(createLogEntry(1));
    store.clear();
    store.push(createLogEntry(2));

    const entries = store.toArray();
    expect(entries).toHaveLength(1);
    expect(entries[0].seq).toBe(2);
  });
});
