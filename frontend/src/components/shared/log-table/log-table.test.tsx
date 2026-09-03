import { describe, expect, it } from "vitest";

import type { LogEntry } from "@/api/endpoints";
import { createLogEntry } from "@/test/factories";

import { getLogLevelStyle, resolveSortKey } from "./constants";
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

  it("uses timestamp-seq-logger-lineno when seq is the 0 fallback marker", () => {
    const e = { seq: 0, timestamp: 1000, logger_name: "hassette.apps.my_app", lineno: 55 } as LogEntry;
    expect(rowKey(e)).toBe("1000-0-hassette.apps.my_app-55");
  });

  it("falls back to timestamp-logger-lineno only when seq is genuinely absent", () => {
    const e = { timestamp: 1000, logger_name: "hassette.apps.my_app", lineno: 55 } as unknown as LogEntry;
    expect(rowKey(e)).toBe("1000-hassette.apps.my_app-55");
  });

  it("gives two seq-0 records with different logger/lineno distinct keys", () => {
    const a = entry({ seq: 0, timestamp: 1000, logger_name: "third_party_a", lineno: 42 });
    const b = entry({ seq: 0, timestamp: 1000, logger_name: "third_party_b", lineno: 99 });
    expect(rowKey(a)).not.toBe(rowKey(b));
  });

  it("documents that two fully-identical seq-0 records still collide", () => {
    // Same timestamp, logger, and line, both carrying the unstamped seq-0 fallback —
    // rowKey has no remaining field to discriminate on. Accepted as an extremely rare
    // edge case rather than a silent regression: it's a documented, deliberate limit.
    const a = entry({ seq: 0, timestamp: 1000, logger_name: "third_party", lineno: 42 });
    const b = entry({ seq: 0, timestamp: 1000, logger_name: "third_party", lineno: 42 });
    expect(rowKey(a)).toBe(rowKey(b));
  });
});

describe("getLogLevelStyle", () => {
  it("is the only exported log-level style resolver", async () => {
    const constantsModule = await import("./constants");

    expect(Object.keys(constantsModule)).not.toContain("levelClass");
  });

  it("returns the matching shared style object for a known level", () => {
    expect(getLogLevelStyle("INFO")).toEqual({
      tableTone: "text-primary",
      drawerSurface: "bg-[var(--status-success-bg)]",
      drawerTone: "text-[var(--status-success)]",
    });

    expect(getLogLevelStyle("WARNING")).toEqual({
      tableTone: "text-[var(--status-warning)]",
      drawerSurface: "bg-[var(--status-warning-bg)]",
      drawerTone: "text-[var(--status-warning)]",
      rowTone: "bg-[var(--status-warning-bg)] hover:brightness-95",
    });
  });

  it("returns undefined for unknown levels", () => {
    expect(getLogLevelStyle("TRACE")).toBeUndefined();
  });
});
