import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PRESET_WINDOW_SECONDS, resolveSince } from "./time-window";

const BASE_TIME_S = 1_700_000_000; // arbitrary fixed epoch in seconds

describe("PRESET_WINDOW_SECONDS", () => {
  it("has correct value for 1h", () => {
    expect(PRESET_WINDOW_SECONDS["1h"]).toBe(3600);
  });

  it("has correct value for 24h", () => {
    expect(PRESET_WINDOW_SECONDS["24h"]).toBe(86400);
  });

  it("has correct value for 7d", () => {
    expect(PRESET_WINDOW_SECONDS["7d"]).toBe(604800);
  });
});

describe("resolveSince", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE_TIME_S * 1000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns Date.now()/1000 - uptimeSeconds for since-restart", () => {
    const uptimeSeconds = 300;
    const result = resolveSince("since-restart", uptimeSeconds);
    expect(result).toBe(BASE_TIME_S - uptimeSeconds);
  });

  it("returns undefined for since-restart when uptimeSeconds is null", () => {
    const result = resolveSince("since-restart", null);
    expect(result).toBeUndefined();
  });

  it("returns Date.now()/1000 - 3600 for 1h preset", () => {
    const result = resolveSince("1h", null);
    expect(result).toBe(BASE_TIME_S - 3600);
  });

  it("returns Date.now()/1000 - 86400 for 24h preset", () => {
    const result = resolveSince("24h", null);
    expect(result).toBe(BASE_TIME_S - 86400);
  });

  it("returns Date.now()/1000 - 604800 for 7d preset", () => {
    const result = resolveSince("7d", null);
    expect(result).toBe(BASE_TIME_S - 604800);
  });

  it("returns a valid number for 1h even when uptimeSeconds is provided", () => {
    // Fixed-window presets ignore uptimeSeconds
    const result = resolveSince("1h", 7200);
    expect(result).toBe(BASE_TIME_S - 3600);
  });
});
