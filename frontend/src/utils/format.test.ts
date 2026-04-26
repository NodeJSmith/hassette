import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  formatDuration,
  formatRelativeTime,
  formatTimestamp,
  formatTriggerDetail,
  pluralize,
} from "./format";

// ---------------------------------------------------------------------------
// formatTimestamp
// ---------------------------------------------------------------------------

describe("formatTimestamp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("test_formatTimestamp_epoch_zero: formats Unix epoch zero without throwing", () => {
    const result = formatTimestamp(0);
    // "MM/DD H:MM:SS AM/PM" — ICU-safe regex matcher
    expect(result).toMatch(/^\d{2}\/\d{2} \d{1,2}:\d{2}:\d{2} (AM|PM)$/i);
  });

  it("test_formatTimestamp_recent: formats a known recent timestamp with correct date parts", () => {
    // 2024-06-15 00:00:00 UTC → date depends on local tz, so we only assert the pattern
    const result = formatTimestamp(1718409600);
    expect(result).toMatch(/^\d{2}\/\d{2} \d{1,2}:\d{2}:\d{2} (AM|PM)$/i);
  });

  it("test_formatTimestamp_large: formats a large timestamp without throwing", () => {
    // year 2100 — 4102444800
    const result = formatTimestamp(4102444800);
    expect(result).toMatch(/^\d{2}\/\d{2} \d{1,2}:\d{2}:\d{2} (AM|PM)$/i);
  });
});

// ---------------------------------------------------------------------------
// formatDuration
// ---------------------------------------------------------------------------

describe("formatDuration", () => {
  it("test_formatDuration_sub_ms: returns '<1ms' for values below 1ms", () => {
    expect(formatDuration(0)).toBe("<1ms");
    expect(formatDuration(0.5)).toBe("<1ms");
    expect(formatDuration(0.999)).toBe("<1ms");
  });

  it("test_formatDuration_ms: formats millisecond values with one decimal", () => {
    expect(formatDuration(158.0)).toBe("158.0ms");
    expect(formatDuration(1)).toBe("1.0ms");
    expect(formatDuration(999.9)).toBe("999.9ms");
  });

  it("test_formatDuration_boundary_1000ms: 1000ms converts to seconds", () => {
    expect(formatDuration(1000)).toBe("1.0s");
  });

  it("test_formatDuration_seconds: formats values >= 1000ms as seconds", () => {
    expect(formatDuration(1500)).toBe("1.5s");
    expect(formatDuration(10000)).toBe("10.0s");
  });

  it("test_formatDuration_zero: zero returns '<1ms'", () => {
    expect(formatDuration(0)).toBe("<1ms");
  });
});

// ---------------------------------------------------------------------------
// pluralize
// ---------------------------------------------------------------------------

describe("pluralize", () => {
  it("test_pluralize_singular: count=1 uses singular form", () => {
    expect(pluralize(1, "entry", "entries")).toBe("1 entry");
    expect(pluralize(1, "job")).toBe("1 job");
  });

  it("test_pluralize_default_plural: count != 1 appends 's' when no plural given", () => {
    expect(pluralize(0, "job")).toBe("0 jobs");
    expect(pluralize(2, "job")).toBe("2 jobs");
    expect(pluralize(10, "listener")).toBe("10 listeners");
  });

  it("test_pluralize_custom_plural: count != 1 uses custom plural form", () => {
    expect(pluralize(0, "entry", "entries")).toBe("0 entries");
    expect(pluralize(2, "entry", "entries")).toBe("2 entries");
  });

  it("test_pluralize_zero_default: count=0 uses plural (default 's')", () => {
    expect(pluralize(0, "item")).toBe("0 items");
  });
});

// ---------------------------------------------------------------------------
// formatTriggerDetail
// ---------------------------------------------------------------------------

describe("formatTriggerDetail", () => {
  it("test_formatTriggerDetail_seconds: small seconds value passes through as-is", () => {
    expect(formatTriggerDetail("30s")).toBe("30s");
    expect(formatTriggerDetail("0s")).toBe("0s");
    expect(formatTriggerDetail("59s")).toBe("59s");
  });

  it("test_formatTriggerDetail_days: large seconds converts to days", () => {
    // 432000s = 5 days exactly
    expect(formatTriggerDetail("432000s")).toBe("5d");
  });

  it("test_formatTriggerDetail_mixed: mixed units display all components", () => {
    // 3661s = 1h 1m 1s
    expect(formatTriggerDetail("3661s")).toBe("1h 1m 1s");
  });

  it("test_formatTriggerDetail_hours_minutes: hours and minutes without seconds", () => {
    // 3660s = 1h 1m
    expect(formatTriggerDetail("3660s")).toBe("1h 1m");
  });

  it("test_formatTriggerDetail_exact_minute: exactly 60s displays as 1m", () => {
    expect(formatTriggerDetail("60s")).toBe("1m");
  });

  it("test_formatTriggerDetail_cron_passthrough: cron strings are not modified", () => {
    expect(formatTriggerDetail("30 7 * * 1-5")).toBe("30 7 * * 1-5");
  });

  it("test_formatTriggerDetail_time_passthrough: time strings pass through unchanged", () => {
    expect(formatTriggerDetail("07:00")).toBe("07:00");
  });
});

// ---------------------------------------------------------------------------
// formatRelativeTime
// ---------------------------------------------------------------------------

describe("formatRelativeTime", () => {
  const BASE_TIME_S = 1_700_000_000; // arbitrary fixed epoch in seconds

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE_TIME_S * 1000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("test_formatRelativeTime_just_now: diff < 60s returns 'just now'", () => {
    expect(formatRelativeTime(BASE_TIME_S - 0)).toBe("just now");
    expect(formatRelativeTime(BASE_TIME_S - 1)).toBe("just now");
    expect(formatRelativeTime(BASE_TIME_S - 59)).toBe("just now");
  });

  it("test_formatRelativeTime_boundary_59s_just_now: 59s diff is still 'just now'", () => {
    expect(formatRelativeTime(BASE_TIME_S - 59)).toBe("just now");
  });

  it("test_formatRelativeTime_boundary_60s_minutes: exactly 60s diff switches to minutes", () => {
    expect(formatRelativeTime(BASE_TIME_S - 60)).toBe("1m ago");
  });

  it("test_formatRelativeTime_minutes: minutes between 1 and 59", () => {
    expect(formatRelativeTime(BASE_TIME_S - 120)).toBe("2m ago");
    expect(formatRelativeTime(BASE_TIME_S - 3599)).toBe("59m ago");
  });

  it("test_formatRelativeTime_boundary_3599s_minutes: 3599s diff is still minutes", () => {
    expect(formatRelativeTime(BASE_TIME_S - 3599)).toBe("59m ago");
  });

  it("test_formatRelativeTime_boundary_3600s_hours: exactly 3600s diff switches to hours", () => {
    expect(formatRelativeTime(BASE_TIME_S - 3600)).toBe("1h ago");
  });

  it("test_formatRelativeTime_hours: hours between 1 and 23", () => {
    expect(formatRelativeTime(BASE_TIME_S - 10800)).toBe("3h ago");
    expect(formatRelativeTime(BASE_TIME_S - 86399)).toBe("23h ago");
  });

  it("test_formatRelativeTime_boundary_86399s_hours: 86399s diff is still hours", () => {
    expect(formatRelativeTime(BASE_TIME_S - 86399)).toBe("23h ago");
  });

  it("test_formatRelativeTime_boundary_86400s_days: exactly 86400s diff switches to days", () => {
    expect(formatRelativeTime(BASE_TIME_S - 86400)).toBe("1d ago");
  });

  it("test_formatRelativeTime_days: multiple days", () => {
    expect(formatRelativeTime(BASE_TIME_S - 432000)).toBe("5d ago");
  });
});
