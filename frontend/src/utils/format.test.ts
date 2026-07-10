import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatAge,
  formatDuration,
  formatDurationOrDash,
  formatOptionalDuration,
  formatRate,
  formatRelativeTime,
  formatTimestamp,
  formatTriggerDetail,
  pluralize,
} from "./format";

describe("formatTimestamp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats Unix epoch zero without throwing", () => {
    const result = formatTimestamp(0);
    // "MM/DD H:MM:SS AM/PM" — ICU-safe regex matcher
    expect(result).toMatch(/^\d{2}\/\d{2} \d{1,2}:\d{2}:\d{2} (AM|PM)$/i);
  });

  it("formats a known recent timestamp with correct date parts", () => {
    // 2024-06-15 00:00:00 UTC → date depends on local tz, so we only assert the pattern
    const result = formatTimestamp(1718409600);
    expect(result).toMatch(/^\d{2}\/\d{2} \d{1,2}:\d{2}:\d{2} (AM|PM)$/i);
  });

  it("formats a large timestamp without throwing", () => {
    // year 2100 — 4102444800
    const result = formatTimestamp(4102444800);
    expect(result).toMatch(/^\d{2}\/\d{2} \d{1,2}:\d{2}:\d{2} (AM|PM)$/i);
  });
});

describe("formatDuration", () => {
  it("returns '<1ms' for values below 1ms", () => {
    expect(formatDuration(0)).toBe("<1ms");
    expect(formatDuration(0.5)).toBe("<1ms");
    expect(formatDuration(0.999)).toBe("<1ms");
  });

  it("formats millisecond values with one decimal", () => {
    expect(formatDuration(158.0)).toBe("158.0ms");
    expect(formatDuration(1)).toBe("1.0ms");
    expect(formatDuration(999.9)).toBe("999.9ms");
  });

  it("1000ms converts to seconds", () => {
    expect(formatDuration(1000)).toBe("1.0s");
  });

  it("formats values >= 1000ms as seconds", () => {
    expect(formatDuration(1500)).toBe("1.5s");
    expect(formatDuration(10000)).toBe("10.0s");
  });

  it("zero returns '<1ms'", () => {
    expect(formatDuration(0)).toBe("<1ms");
  });
});

describe("formatDurationOrDash", () => {
  it("returns dash for null", () => {
    expect(formatDurationOrDash(null)).toBe("—");
  });

  it("returns dash for undefined", () => {
    expect(formatDurationOrDash(undefined)).toBe("—");
  });

  it("returns dash for zero", () => {
    expect(formatDurationOrDash(0)).toBe("—");
  });

  it("formats positive values", () => {
    expect(formatDurationOrDash(150)).toBe("150.0ms");
    expect(formatDurationOrDash(2500)).toBe("2.5s");
  });
});

describe("formatOptionalDuration", () => {
  it("returns dash for null", () => {
    expect(formatOptionalDuration(null)).toBe("—");
  });

  it("returns dash for undefined", () => {
    expect(formatOptionalDuration(undefined)).toBe("—");
  });

  it("formats zero as a valid duration", () => {
    expect(formatOptionalDuration(0)).toBe("<1ms");
  });

  it("formats positive values", () => {
    expect(formatOptionalDuration(150)).toBe("150.0ms");
  });
});

describe("pluralize", () => {
  it("count=1 uses singular form", () => {
    expect(pluralize(1, "entry", "entries")).toBe("1 entry");
    expect(pluralize(1, "job")).toBe("1 job");
  });

  it("count != 1 appends 's' when no plural given", () => {
    expect(pluralize(0, "job")).toBe("0 jobs");
    expect(pluralize(2, "job")).toBe("2 jobs");
    expect(pluralize(10, "listener")).toBe("10 listeners");
  });

  it("count != 1 uses custom plural form", () => {
    expect(pluralize(0, "entry", "entries")).toBe("0 entries");
    expect(pluralize(2, "entry", "entries")).toBe("2 entries");
  });

  it("count=0 uses plural (default 's')", () => {
    expect(pluralize(0, "item")).toBe("0 items");
  });
});

describe("formatTriggerDetail", () => {
  it("small seconds value passes through as-is", () => {
    expect(formatTriggerDetail("30s")).toBe("30s");
    expect(formatTriggerDetail("0s")).toBe("0s");
    expect(formatTriggerDetail("59s")).toBe("59s");
  });

  it("large seconds converts to days", () => {
    // 432000s = 5 days exactly
    expect(formatTriggerDetail("432000s")).toBe("5d");
  });

  it("mixed units display all components", () => {
    // 3661s = 1h 1m 1s
    expect(formatTriggerDetail("3661s")).toBe("1h 1m 1s");
  });

  it("hours and minutes without seconds", () => {
    // 3660s = 1h 1m
    expect(formatTriggerDetail("3660s")).toBe("1h 1m");
  });

  it("exactly 60s displays as 1m", () => {
    expect(formatTriggerDetail("60s")).toBe("1m");
  });

  it("cron strings are not modified", () => {
    expect(formatTriggerDetail("30 7 * * 1-5")).toBe("30 7 * * 1-5");
  });

  it("time strings pass through unchanged", () => {
    expect(formatTriggerDetail("07:00")).toBe("07:00");
  });
});

const BASE_TIME_S = 1_700_000_000; // arbitrary fixed epoch in seconds

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE_TIME_S * 1000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("diff < 60s returns 'just now'", () => {
    expect(formatRelativeTime(BASE_TIME_S - 0)).toBe("just now");
    expect(formatRelativeTime(BASE_TIME_S - 1)).toBe("just now");
    expect(formatRelativeTime(BASE_TIME_S - 59)).toBe("just now");
  });

  it("59s diff is still 'just now'", () => {
    expect(formatRelativeTime(BASE_TIME_S - 59)).toBe("just now");
  });

  it("exactly 60s diff switches to minutes", () => {
    expect(formatRelativeTime(BASE_TIME_S - 60)).toBe("1m ago");
  });

  it("minutes between 1 and 59", () => {
    expect(formatRelativeTime(BASE_TIME_S - 120)).toBe("2m ago");
    expect(formatRelativeTime(BASE_TIME_S - 3599)).toBe("59m ago");
  });

  it("3599s diff is still minutes", () => {
    expect(formatRelativeTime(BASE_TIME_S - 3599)).toBe("59m ago");
  });

  it("exactly 3600s diff switches to hours", () => {
    expect(formatRelativeTime(BASE_TIME_S - 3600)).toBe("1h ago");
  });

  it("hours between 1 and 23", () => {
    expect(formatRelativeTime(BASE_TIME_S - 10800)).toBe("3h ago");
    expect(formatRelativeTime(BASE_TIME_S - 86399)).toBe("23h ago");
  });

  it("86399s diff is still hours", () => {
    expect(formatRelativeTime(BASE_TIME_S - 86399)).toBe("23h ago");
  });

  it("exactly 86400s diff switches to days", () => {
    expect(formatRelativeTime(BASE_TIME_S - 86400)).toBe("1d ago");
  });

  it("multiple days", () => {
    expect(formatRelativeTime(BASE_TIME_S - 432000)).toBe("5d ago");
  });

  it("future timestamp <60s returns 'in <1m'", () => {
    expect(formatRelativeTime(BASE_TIME_S + 30)).toBe("in <1m");
  });

  it("future timestamp minutes", () => {
    expect(formatRelativeTime(BASE_TIME_S + 480)).toBe("in 8m");
  });

  it("future timestamp hours", () => {
    expect(formatRelativeTime(BASE_TIME_S + 7200)).toBe("in 2h");
  });

  it("future timestamp days", () => {
    expect(formatRelativeTime(BASE_TIME_S + 172800)).toBe("in 2d");
  });
});

describe("formatAge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE_TIME_S * 1000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns seconds for < 60s", () => {
    expect(formatAge(BASE_TIME_S - 12)).toBe("12s");
  });

  it("returns 0s for current time", () => {
    expect(formatAge(BASE_TIME_S)).toBe("0s");
  });

  it("clamps future timestamps to 0s", () => {
    expect(formatAge(BASE_TIME_S + 100)).toBe("0s");
  });

  it("returns minutes at 60s boundary", () => {
    expect(formatAge(BASE_TIME_S - 60)).toBe("1m");
  });

  it("returns minutes for < 3600s", () => {
    expect(formatAge(BASE_TIME_S - 300)).toBe("5m");
  });

  it("returns hours at 3600s boundary", () => {
    expect(formatAge(BASE_TIME_S - 3600)).toBe("1h");
  });

  it("returns hours for < 86400s", () => {
    expect(formatAge(BASE_TIME_S - 7200)).toBe("2h");
  });

  it("returns days at 86400s boundary", () => {
    expect(formatAge(BASE_TIME_S - 86400)).toBe("1d");
  });

  it("returns days for large values", () => {
    expect(formatAge(BASE_TIME_S - 432000)).toBe("5d");
  });
});

describe("formatRate", () => {
  it("0 failures out of 100 runs returns '0.0%'", () => {
    expect(formatRate(0, 100)).toBe("0.0%");
  });

  it("3 failures out of 100 runs returns '3.0%'", () => {
    expect(formatRate(3, 100)).toBe("3.0%");
  });

  it("1 failure out of 3 runs returns '33.3%'", () => {
    expect(formatRate(1, 3)).toBe("33.3%");
  });

  it("0 total runs returns em-dash", () => {
    expect(formatRate(0, 0)).toBe("—");
  });

  it("failures with 0 total returns em-dash", () => {
    expect(formatRate(5, 0)).toBe("—");
  });

  it("100 failures out of 100 runs returns '100.0%'", () => {
    expect(formatRate(100, 100)).toBe("100.0%");
  });
});
