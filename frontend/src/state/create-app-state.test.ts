import { describe, expect, it } from "vitest";
import { createAppState } from "./create-app-state";

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
  });

  it("log buffer and version signal are independent", () => {
    const a = createAppState();
    const b = createAppState();

    a.logs.buffer.push({
      timestamp: 0,
      level: "INFO",
      logger_name: "",
      func_name: "",
      lineno: 0,
      message: "test",
      exc_info: null,
      app_key: null,
    });
    a.logs.version.value++;

    expect(a.logs.buffer.length).toBe(1);
    expect(b.logs.buffer.length).toBe(0);
    expect(a.logs.version.value).toBe(1);
    expect(b.logs.version.value).toBe(0);
  });
});
