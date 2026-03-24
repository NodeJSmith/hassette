import { describe, expect, it } from "vitest";
import { createAppState, createLogStore } from "./create-app-state";
import type { WsLogPayload } from "../api/ws-types";

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
  };
}

describe("createAppState", () => {
  it("creates independent instances", () => {
    const a = createAppState();
    const b = createAppState();

    a.theme.value = "light";
    expect(b.theme.value).toBe("dark"); // not affected

    a.sessionId.value = 42;
    expect(b.sessionId.value).toBeNull();

    a.reconnectVersion.value = 3;
    expect(b.reconnectVersion.value).toBe(0);

    a.tick.value = 5;
    expect(b.tick.value).toBe(0);
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
