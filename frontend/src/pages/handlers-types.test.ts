import { describe, it, expect } from "vitest";
import { listenerToRow, jobToRow, compareHandlerRows } from "./handlers-types";
import type { UnifiedRow, HandlerSortKey } from "./handlers-types";
import type { SortState } from "../components/shared/sort-header";
import { createListener, createJob } from "../test/factories";

// ---------------------------------------------------------------------------
// listenerToRow
// ---------------------------------------------------------------------------

describe("listenerToRow", () => {
  it("sets kind to listener", () => {
    const row = listenerToRow(createListener());
    expect(row.kind).toBe("listener");
  });

  it("prefixes id with h-", () => {
    const row = listenerToRow(createListener({ listener_id: 42 }));
    expect(row.id).toBe("h-42");
  });

  it("maps app_key", () => {
    const row = listenerToRow(createListener({ app_key: "my_app" }));
    expect(row.app_key).toBe("my_app");
  });

  it("extracts last dot segment of handler_method for name", () => {
    const row = listenerToRow(createListener({ handler_method: "my.module.MyApp.on_motion" }));
    expect(row.name).toBe("on_motion");
  });

  it("uses bare handler_method as name when no dots", () => {
    const row = listenerToRow(createListener({ handler_method: "on_motion" }));
    expect(row.name).toBe("on_motion");
  });

  it("carries handler_method verbatim", () => {
    const row = listenerToRow(createListener({ handler_method: "my.app.MyApp.on_change" }));
    expect(row.handler_method).toBe("my.app.MyApp.on_change");
  });

  it("maps listener_kind to trigger", () => {
    const row = listenerToRow(createListener({ listener_kind: "attribute change" }));
    expect(row.trigger).toBe("attribute change");
  });

  it("maps total_invocations to runs", () => {
    const row = listenerToRow(createListener({ total_invocations: 99 }));
    expect(row.runs).toBe(99);
  });

  it("maps failed", () => {
    const row = listenerToRow(createListener({ failed: 3 }));
    expect(row.failed).toBe(3);
  });

  it("maps timed_out", () => {
    const row = listenerToRow(createListener({ timed_out: 2 }));
    expect(row.timed_out).toBe(2);
  });

  it("maps avg_duration_ms", () => {
    const row = listenerToRow(createListener({ avg_duration_ms: 150 }));
    expect(row.avg_duration_ms).toBe(150);
  });

  it("maps source_tier", () => {
    const row = listenerToRow(createListener({ source_tier: "framework" }));
    expect(row.source_tier).toBe("framework");
  });

  it("always sets next_run_ts to null", () => {
    const row = listenerToRow(createListener());
    expect(row.next_run_ts).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// jobToRow
// ---------------------------------------------------------------------------

describe("jobToRow", () => {
  it("sets kind to job", () => {
    const row = jobToRow(createJob());
    expect(row.kind).toBe("job");
  });

  it("prefixes id with j-", () => {
    const row = jobToRow(createJob({ job_id: 7 }));
    expect(row.id).toBe("j-7");
  });

  it("maps app_key", () => {
    const row = jobToRow(createJob({ app_key: "schedule_app" }));
    expect(row.app_key).toBe("schedule_app");
  });

  it("uses job_name as name (not handler_method)", () => {
    const row = jobToRow(createJob({ job_name: "cleanup_task", handler_method: "tasks.cleanup" }));
    expect(row.name).toBe("cleanup_task");
  });

  it("carries handler_method verbatim", () => {
    const row = jobToRow(createJob({ handler_method: "tasks.cleanup" }));
    expect(row.handler_method).toBe("tasks.cleanup");
  });

  it("prefers trigger_label over trigger_type when both present", () => {
    const row = jobToRow(createJob({ trigger_label: "every 60s", trigger_type: "interval" }));
    expect(row.trigger).toBe("every 60s");
  });

  it("falls back to trigger_type when trigger_label is empty", () => {
    const row = jobToRow(createJob({ trigger_label: "", trigger_type: "cron" }));
    expect(row.trigger).toBe("cron");
  });

  it("sets trigger to null when both trigger_label and trigger_type are falsy", () => {
    const row = jobToRow(createJob({ trigger_label: "", trigger_type: null }));
    expect(row.trigger).toBeNull();
  });

  it("maps total_executions to runs", () => {
    const row = jobToRow(createJob({ total_executions: 25 }));
    expect(row.runs).toBe(25);
  });

  it("maps failed", () => {
    const row = jobToRow(createJob({ failed: 1 }));
    expect(row.failed).toBe(1);
  });

  it("maps timed_out", () => {
    const row = jobToRow(createJob({ timed_out: 4 }));
    expect(row.timed_out).toBe(4);
  });

  it("maps avg_duration_ms", () => {
    const row = jobToRow(createJob({ avg_duration_ms: 200 }));
    expect(row.avg_duration_ms).toBe(200);
  });

  it("maps source_tier", () => {
    const row = jobToRow(createJob({ source_tier: "framework" }));
    expect(row.source_tier).toBe("framework");
  });

  it("maps next_run timestamp when present", () => {
    const row = jobToRow(createJob({ next_run: 1700000000 }));
    expect(row.next_run_ts).toBe(1700000000);
  });

  it("sets next_run_ts to null when next_run is null", () => {
    const row = jobToRow(createJob({ next_run: null }));
    expect(row.next_run_ts).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// compareHandlerRows — helpers
// ---------------------------------------------------------------------------

function asc(key: HandlerSortKey): SortState<HandlerSortKey> {
  return { key, dir: "asc" };
}

function desc(key: HandlerSortKey): SortState<HandlerSortKey> {
  return { key, dir: "desc" };
}

function row(overrides: Partial<UnifiedRow>): UnifiedRow {
  return {
    kind: "listener",
    id: "h-1",
    app_key: "app_a",
    name: "handler",
    handler_method: "app.Handler.handler",
    trigger: "state change",
    runs: 10,
    failed: 0,
    timed_out: 0,
    avg_duration_ms: 50,
    next_run_ts: null,
    source_tier: "app",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// compareHandlerRows — sort key tests
// ---------------------------------------------------------------------------

describe("compareHandlerRows — kind", () => {
  it("asc: job sorts before listener (j < l lexically)", () => {
    // "job".localeCompare("listener") < 0, so job rows appear first ascending
    const a = row({ kind: "listener" });
    const b = row({ kind: "job" });
    expect(compareHandlerRows(a, b, asc("kind"))).toBeGreaterThan(0);
  });

  it("desc: listener sorts before job", () => {
    const a = row({ kind: "listener" });
    const b = row({ kind: "job" });
    expect(compareHandlerRows(a, b, desc("kind"))).toBeLessThan(0);
  });
});

describe("compareHandlerRows — app", () => {
  it("asc: app_a before app_b", () => {
    const a = row({ app_key: "app_a" });
    const b = row({ app_key: "app_b" });
    expect(compareHandlerRows(a, b, asc("app"))).toBeLessThan(0);
  });

  it("desc: app_b before app_a", () => {
    const a = row({ app_key: "app_a" });
    const b = row({ app_key: "app_b" });
    expect(compareHandlerRows(a, b, desc("app"))).toBeGreaterThan(0);
  });
});

describe("compareHandlerRows — name", () => {
  it("asc: alpha sorts before beta", () => {
    const a = row({ name: "alpha" });
    const b = row({ name: "beta" });
    expect(compareHandlerRows(a, b, asc("name"))).toBeLessThan(0);
  });

  it("desc: beta sorts before alpha", () => {
    const a = row({ name: "alpha" });
    const b = row({ name: "beta" });
    expect(compareHandlerRows(a, b, desc("name"))).toBeGreaterThan(0);
  });
});

describe("compareHandlerRows — trigger", () => {
  it("asc: attribute change before state change", () => {
    const a = row({ trigger: "attribute change" });
    const b = row({ trigger: "state change" });
    expect(compareHandlerRows(a, b, asc("trigger"))).toBeLessThan(0);
  });

  it("desc: state change before attribute change", () => {
    const a = row({ trigger: "attribute change" });
    const b = row({ trigger: "state change" });
    expect(compareHandlerRows(a, b, desc("trigger"))).toBeGreaterThan(0);
  });

  it("null trigger treated as empty string — sorts before non-null asc", () => {
    const a = row({ trigger: null });
    const b = row({ trigger: "state change" });
    expect(compareHandlerRows(a, b, asc("trigger"))).toBeLessThan(0);
  });

  it("both null triggers compare equal", () => {
    const a = row({ trigger: null });
    const b = row({ trigger: null });
    expect(compareHandlerRows(a, b, asc("trigger"))).toBe(0);
  });
});

describe("compareHandlerRows — runs", () => {
  it("asc: fewer runs first", () => {
    const a = row({ runs: 5 });
    const b = row({ runs: 20 });
    expect(compareHandlerRows(a, b, asc("runs"))).toBeLessThan(0);
  });

  it("desc: more runs first", () => {
    const a = row({ runs: 5 });
    const b = row({ runs: 20 });
    expect(compareHandlerRows(a, b, desc("runs"))).toBeGreaterThan(0);
  });
});

describe("compareHandlerRows — failed", () => {
  it("asc: fewer failures first", () => {
    const a = row({ failed: 1 });
    const b = row({ failed: 10 });
    expect(compareHandlerRows(a, b, asc("failed"))).toBeLessThan(0);
  });

  it("desc: more failures first", () => {
    const a = row({ failed: 1 });
    const b = row({ failed: 10 });
    expect(compareHandlerRows(a, b, desc("failed"))).toBeGreaterThan(0);
  });
});

describe("compareHandlerRows — timed_out", () => {
  it("asc: fewer timeouts first", () => {
    const a = row({ timed_out: 0 });
    const b = row({ timed_out: 3 });
    expect(compareHandlerRows(a, b, asc("timed_out"))).toBeLessThan(0);
  });

  it("desc: more timeouts first", () => {
    const a = row({ timed_out: 0 });
    const b = row({ timed_out: 3 });
    expect(compareHandlerRows(a, b, desc("timed_out"))).toBeGreaterThan(0);
  });
});

describe("compareHandlerRows — error_rate", () => {
  it("asc: lower rate first", () => {
    const a = row({ runs: 100, failed: 1 });   // 1%
    const b = row({ runs: 100, failed: 10 });  // 10%
    expect(compareHandlerRows(a, b, asc("error_rate"))).toBeLessThan(0);
  });

  it("desc: higher rate first", () => {
    const a = row({ runs: 100, failed: 1 });
    const b = row({ runs: 100, failed: 10 });
    expect(compareHandlerRows(a, b, desc("error_rate"))).toBeGreaterThan(0);
  });

  it("treats zero runs as 0% rate", () => {
    const a = row({ runs: 0, failed: 0 });
    const b = row({ runs: 100, failed: 10 });
    expect(compareHandlerRows(a, b, asc("error_rate"))).toBeLessThan(0);
  });
});

describe("compareHandlerRows — avg_duration", () => {
  it("asc: shorter duration first", () => {
    const a = row({ avg_duration_ms: 10 });
    const b = row({ avg_duration_ms: 500 });
    expect(compareHandlerRows(a, b, asc("avg_duration"))).toBeLessThan(0);
  });

  it("desc: longer duration first", () => {
    const a = row({ avg_duration_ms: 10 });
    const b = row({ avg_duration_ms: 500 });
    expect(compareHandlerRows(a, b, desc("avg_duration"))).toBeGreaterThan(0);
  });
});

describe("compareHandlerRows — next_run", () => {
  it("asc: sooner timestamp first", () => {
    const a = row({ next_run_ts: 1000 });
    const b = row({ next_run_ts: 2000 });
    expect(compareHandlerRows(a, b, asc("next_run"))).toBeLessThan(0);
  });

  it("desc: later timestamp first", () => {
    const a = row({ next_run_ts: 1000 });
    const b = row({ next_run_ts: 2000 });
    expect(compareHandlerRows(a, b, desc("next_run"))).toBeGreaterThan(0);
  });

  it("null next_run_ts sorts after any timestamp (asc)", () => {
    const a = row({ next_run_ts: 999999 });
    const b = row({ next_run_ts: null });
    expect(compareHandlerRows(a, b, asc("next_run"))).toBeLessThan(0);
  });

  it("both null produce NaN (Infinity - Infinity)", () => {
    // The implementation uses Infinity for null timestamps; Infinity - Infinity = NaN.
    // Sort is stable for equal-timestamp rows in practice (browser sort treats NaN as 0).
    const a = row({ next_run_ts: null });
    const b = row({ next_run_ts: null });
    expect(compareHandlerRows(a, b, asc("next_run"))).toBeNaN();
  });
});

describe("compareHandlerRows — default case", () => {
  it("returns 0 for unrecognised sort key", () => {
    const a = row({});
    const b = row({});
    // Cast unknown key through the type system to test the default branch
    const unknownSort = { key: "nonexistent" as HandlerSortKey, dir: "asc" as const };
    expect(compareHandlerRows(a, b, unknownSort)).toBe(0);
  });
});
