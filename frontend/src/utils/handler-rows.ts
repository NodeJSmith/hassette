import type { JobData, ListenerData } from "../api/endpoints";
import type { SortState } from "../components/shared/sort-header";
import { lastDotSegment } from "./format";
import { formatJobId, formatListenerId } from "./handler-ids";

export interface UnifiedRow {
  kind: "listener" | "job";
  id: string;
  app_key: string;
  name: string;
  handler_method: string;
  trigger: string | null;
  runs: number;
  failed: number;
  timed_out: number;
  avg_duration_ms: number;
  next_run_ts: number | null;
  source_tier: string;
}

export function listenerToRow(l: ListenerData): UnifiedRow {
  return {
    kind: "listener",
    id: formatListenerId(l.listener_id),
    app_key: l.app_key,
    name: lastDotSegment(l.handler_method),
    handler_method: l.handler_method,
    trigger: l.listener_kind,
    runs: l.total_invocations,
    failed: l.failed,
    timed_out: l.timed_out,
    avg_duration_ms: l.avg_duration_ms,
    next_run_ts: null,
    source_tier: l.source_tier,
  };
}

export function jobToRow(j: JobData): UnifiedRow {
  return {
    kind: "job",
    id: formatJobId(j.job_id),
    app_key: j.app_key,
    name: j.job_name,
    handler_method: j.handler_method,
    trigger: j.trigger_label || j.trigger_type || null,
    runs: j.total_executions,
    failed: j.failed,
    timed_out: j.timed_out,
    avg_duration_ms: j.avg_duration_ms,
    next_run_ts: j.next_run ?? null,
    source_tier: j.source_tier,
  };
}

export type HandlerSortKey =
  | "kind"
  | "app"
  | "name"
  | "trigger"
  | "runs"
  | "failed"
  | "timed_out"
  | "error_rate"
  | "avg_duration"
  | "next_run";

const NO_NEXT_RUN = Number.MAX_SAFE_INTEGER;

export function compareHandlerRows(a: UnifiedRow, b: UnifiedRow, sort: SortState<HandlerSortKey>): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  switch (sort.key) {
    case "kind":
      return dir * a.kind.localeCompare(b.kind);
    case "app":
      return dir * a.app_key.localeCompare(b.app_key);
    case "name":
      return dir * a.name.localeCompare(b.name);
    case "trigger":
      return dir * (a.trigger ?? "").localeCompare(b.trigger ?? "");
    case "runs":
      return dir * (a.runs - b.runs);
    case "failed":
      return dir * (a.failed - b.failed);
    case "timed_out":
      return dir * (a.timed_out - b.timed_out);
    case "error_rate": {
      const rateA = a.runs > 0 ? a.failed / a.runs : 0;
      const rateB = b.runs > 0 ? b.failed / b.runs : 0;
      return dir * (rateA - rateB);
    }
    case "avg_duration":
      return dir * (a.avg_duration_ms - b.avg_duration_ms);
    case "next_run": {
      const ts = (r: UnifiedRow) => r.next_run_ts ?? NO_NEXT_RUN;
      return dir * (ts(a) - ts(b));
    }
    default:
      return 0;
  }
}
