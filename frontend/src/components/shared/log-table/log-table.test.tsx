import { describe, expect, it } from "vitest";

import type { LogEntry } from "../../../api/endpoints";
import { levelClass, resolveSortColumn } from "./constants";
import { rowKey } from "./types";
import { sortEntries } from "./use-log-filters";

function entry(overrides: Partial<LogEntry>): LogEntry {
  return {
    seq: 1,
    timestamp: 1000,
    level: "INFO",
    logger_name: "test",
    func_name: "fn",
    lineno: 1,
    message: "msg",
    exc_info: null,
    app_key: "app",
    ...overrides,
  } as LogEntry;
}

describe("sortEntries", () => {
  it("sorts by timestamp descending", () => {
    const entries = [
      entry({ timestamp: 1000, message: "old" }),
      entry({ timestamp: 3000, message: "new" }),
      entry({ timestamp: 2000, message: "mid" }),
    ];
    const result = sortEntries(entries, "timestamp", false);
    expect(result.map((e) => e.message)).toEqual(["new", "mid", "old"]);
  });

  it("sorts by timestamp ascending", () => {
    const entries = [entry({ timestamp: 3000, message: "new" }), entry({ timestamp: 1000, message: "old" })];
    const result = sortEntries(entries, "timestamp", true);
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
    const result = sortEntries(entries, "level", false);
    expect(result.map((e) => e.message)).toEqual(["crit", "error", "warn", "info", "debug"]);
  });

  it("sorts by function name", () => {
    const entries = [
      entry({ func_name: "charlie", message: "c" }),
      entry({ func_name: "alpha", message: "a" }),
      entry({ func_name: "bravo", message: "b" }),
    ];
    const result = sortEntries(entries, "function", true);
    expect(result.map((e) => e.message)).toEqual(["a", "b", "c"]);
  });

  it("does not mutate the original array", () => {
    const entries = [entry({ timestamp: 2000 }), entry({ timestamp: 1000 })];
    const original = [...entries];
    sortEntries(entries, "timestamp", true);
    expect(entries).toEqual(original);
  });

  it("handles null app_key by sorting nulls last", () => {
    const entries = [entry({ app_key: null, message: "null" }), entry({ app_key: "alpha", message: "alpha" })];
    const result = sortEntries(entries, "app", true);
    expect(result.map((e) => e.message)).toEqual(["alpha", "null"]);
  });
});

describe("resolveSortColumn", () => {
  it("returns the column as-is for valid sort columns", () => {
    expect(resolveSortColumn("timestamp")).toBe("timestamp");
    expect(resolveSortColumn("level")).toBe("level");
    expect(resolveSortColumn("app")).toBe("app");
    expect(resolveSortColumn("function")).toBe("function");
    expect(resolveSortColumn("message")).toBe("message");
  });

  it("maps deprecated 'source' alias to 'function'", () => {
    expect(resolveSortColumn("source")).toBe("function");
  });

  it("falls back to 'timestamp' for invalid input", () => {
    expect(resolveSortColumn("bogus")).toBe("timestamp");
    expect(resolveSortColumn("")).toBe("timestamp");
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
