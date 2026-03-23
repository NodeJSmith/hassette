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

    a.tick.value = 5;
    expect(b.tick.value).toBe(0);
  });

  it("log store push/toArray are independent across instances", () => {
    const a = createAppState();
    const b = createAppState();

    a.logs.push({
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
