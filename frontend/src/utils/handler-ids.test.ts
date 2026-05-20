import { describe, expect, it } from "vitest";
import { formatListenerId, formatJobId, parseHandlerId } from "./handler-ids";

describe("formatListenerId", () => {
  it("formats a listener ID with h- prefix", () => {
    expect(formatListenerId(42)).toBe("h-42");
    expect(formatListenerId(0)).toBe("h-0");
  });
});

describe("formatJobId", () => {
  it("formats a job ID with j- prefix", () => {
    expect(formatJobId(7)).toBe("j-7");
    expect(formatJobId(0)).toBe("j-0");
  });
});

describe("parseHandlerId", () => {
  it("parses a listener ID", () => {
    expect(parseHandlerId("h-42")).toEqual({ kind: "listener", id: 42 });
  });

  it("parses a job ID", () => {
    expect(parseHandlerId("j-7")).toEqual({ kind: "job", id: 7 });
  });

  it("returns null for invalid format", () => {
    expect(parseHandlerId("x-5")).toBeNull();
    expect(parseHandlerId("h42")).toBeNull();
    expect(parseHandlerId("h-")).toBeNull();
    expect(parseHandlerId("")).toBeNull();
    expect(parseHandlerId("h-abc")).toBeNull();
  });

  it("roundtrips with format functions", () => {
    const listenerId = 99;
    const jobId = 13;
    expect(parseHandlerId(formatListenerId(listenerId))).toEqual({ kind: "listener", id: listenerId });
    expect(parseHandlerId(formatJobId(jobId))).toEqual({ kind: "job", id: jobId });
  });
});
