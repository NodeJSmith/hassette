import { describe, expect, it } from "vitest";

import type { LogEntry } from "../../../api/endpoints";
import { createLogEntry } from "../../../test/factories";
import { levelClass, resolveSortKey } from "./constants";
import { rowKey } from "./types";
import { sortEntries } from "./use-log-filters";

function entry(overrides: Partial<LogEntry>) {
  return createLogEntry({ app_key: "app", ...overrides });
}

describe("sortEntries", () => {
  it("sorts by timestamp descending", () => {
    const entries = [
      entry({ timestamp: 1000, message: "old" }),
      entry({ timestamp: 3000, message: "new" }),
      entry({ timestamp: 2000, message: "mid" }),
    ];
    const result = sortEntries(entries, { key: "timestamp", dir: "desc" });
    expect(result.map((e) => e.message)).toEqual(["new", "mid", "old"]);
  });

  it("sorts by timestamp ascending", () => {
    const entries = [entry({ timestamp: 3000, message: "new" }), entry({ timestamp: 1000, message: "old" })];
    const result = sortEntries(entries, { key: "timestamp", dir: "asc" });
    expect(result.map((e) => e.message)).toEqual(["old", "new"]);
  });

  it("sorts by level using severity index", () => {
    const entries = [
      entry({ level: "INFO", message: "info" }),
      entry({ level: "CRITICAL", message: "crit" }),
      entry({ level: "DEBUG", message: "debug" }),
      entry({ level: "ERROR", message: "error" }),
      entry({ level: "WARNING", message: "warn" }),
    ];
    const result = sortEntries(entries, { key: "level", dir: "desc" });
    expect(result.map((e) => e.message)).toEqual(["crit", "error", "warn", "info", "debug"]);
  });

  it("sorts by function name", () => {
    const entries = [
      entry({ func_name: "charlie", message: "c" }),
      entry({ func_name: "alpha", message: "a" }),
      entry({ func_name: "bravo", message: "b" }),
    ];
    const result = sortEntries(entries, { key: "function", dir: "asc" });
    expect(result.map((e) => e.message)).toEqual(["a", "b", "c"]);
  });

  it("does not mutate the original array", () => {
    const entries = [entry({ timestamp: 2000 }), entry({ timestamp: 1000 })];
    const original = [...entries];
    sortEntries(entries, { key: "timestamp", dir: "asc" });
    expect(entries).toEqual(original);
  });

  it("handles null app_key by sorting nulls last", () => {
    const entries = [entry({ app_key: null, message: "null" }), entry({ app_key: "alpha", message: "alpha" })];
    const result = sortEntries(entries, { key: "app", dir: "asc" });
    expect(result.map((e) => e.message)).toEqual(["alpha", "null"]);
  });
});

describe("resolveSortKey", () => {
  it("returns the column as-is for valid sort columns", () => {
    expect(resolveSortKey("timestamp")).toBe("timestamp");
    expect(resolveSortKey("level")).toBe("level");
    expect(resolveSortKey("app")).toBe("app");
    expect(resolveSortKey("function")).toBe("function");
    expect(resolveSortKey("message")).toBe("message");
  });

  it("maps deprecated 'source' alias to 'function'", () => {
    expect(resolveSortKey("source")).toBe("function");
  });

  it("falls back to 'timestamp' for invalid input", () => {
    expect(resolveSortKey("bogus")).toBe("timestamp");
    expect(resolveSortKey("")).toBe("timestamp");
  });
});

describe("rowKey", () => {
  it("uses timestamp-seq when seq is present", () => {
    const e = { seq: 42, timestamp: 1000, logger_name: "test", lineno: 10 } as LogEntry;
    expect(rowKey(e)).toBe("1000-42");
  });

  it("falls back to timestamp-logger-lineno when seq is 0", () => {
    const e = { seq: 0, timestamp: 1000, logger_name: "hassette.apps.my_app", lineno: 55 } as LogEntry;
    expect(rowKey(e)).toBe("1000-hassette.apps.my_app-55");
  });
});

describe("levelClass", () => {
  it("returns the matching class for a known level", () => {
    const mockStyles: Record<string, string> = { levelINFO: "abc123", levelERROR: "def456" };
    expect(levelClass(mockStyles, "level", "INFO")).toBe("abc123");
    expect(levelClass(mockStyles, "level", "ERROR")).toBe("def456");
  });

  it("returns undefined for unknown level", () => {
    const mockStyles: Record<string, string> = { levelINFO: "abc123" };
    expect(levelClass(mockStyles, "level", "TRACE")).toBeUndefined();
  });
});
