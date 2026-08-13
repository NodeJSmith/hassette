import type { DashboardAppGridEntry } from "../api/endpoints";
import type { SortState } from "../components/shared/sort-header";
import { type AppStatusEntry, appStatusKey } from "../state/store";
import { statusPriority } from "./status-priority";

export interface AppRow {
  app_key: string;
  class_name: string;
  display_name: string;
  filename: string;
  status: string;
  block_reason: string | null;
  enabled: boolean;
  auto_loaded: boolean;
  autostart: boolean;
  instance_count: number;
  instances: NonNullable<DashboardAppGridEntry["instances"]>;
  error_message: string | null;
  in_current_config: boolean;
  handler_count: number;
  job_count: number;
  total_invocations: number;
  total_executions: number;
  total_errors: number;
  total_timed_out: number;
  total_job_errors: number;
  total_job_timed_out: number;
  error_rate: number;
  last_activity_ts: number | null;
  activity_buckets: Array<{ ok: number; err: number }>;
  last_error_message: string | null;
  last_error_type: string | null;
  last_error_ts: number | null;
}

/**
 * Normalize a dashboard grid entry into an `AppRow`, defaulting the entry's
 * optional enrichment fields (activity buckets, last-error fields, instances)
 * to their empty/null equivalents. The grid endpoint is the sole data source —
 * this is field defaulting, not a merge of two sources.
 */
export function toAppRow(entry: DashboardAppGridEntry): AppRow {
  return {
    app_key: entry.app_key,
    class_name: entry.class_name,
    display_name: entry.display_name,
    filename: entry.filename,
    status: entry.status,
    block_reason: entry.block_reason ?? null,
    enabled: entry.enabled,
    auto_loaded: entry.auto_loaded,
    autostart: entry.autostart,
    instance_count: entry.instance_count,
    instances: entry.instances ?? [],
    error_message: entry.error_message ?? null,
    in_current_config: entry.in_current_config,
    handler_count: entry.handler_count,
    job_count: entry.job_count,
    total_invocations: entry.total_invocations,
    total_executions: entry.total_executions,
    total_errors: entry.total_errors,
    total_timed_out: entry.total_timed_out,
    total_job_errors: entry.total_job_errors,
    total_job_timed_out: entry.total_job_timed_out,
    error_rate: entry.error_rate,
    last_activity_ts: entry.last_activity_ts,
    activity_buckets: entry.activity_buckets ?? [],
    last_error_message: entry.last_error_message ?? null,
    last_error_type: entry.last_error_type ?? null,
    last_error_ts: entry.last_error_ts ?? null,
  };
}

export type AppSortKey = "name" | "status" | "error" | "runs" | "last";
export type AppSortState = SortState<AppSortKey>;

/** Resolve the live status for an app row's parent view.
 *  Single-instance: WS status for index 0.
 *  Multi-instance: overlays live per-instance WS statuses (falling back to the snapshot's
 *  per-instance status where no WS update has arrived yet) and derives "degraded" from that
 *  live view whenever a "running" and a "failed" instance coexist — mirroring `AppRegistry`'s
 *  own binary model server-side (an instance entry is either running or failed, nothing else),
 *  though the live WS status of an individual instance can transiently be a finer-grained
 *  value (e.g. "starting") that this check doesn't treat as "running". This must be computed
 *  from live data, not read off the cached `row.status`: the dashboard grid query is
 *  invalidated on execution events, not `app_status_changed`, so a cached `row.status` can be
 *  stale in either direction (still "running" after an instance fails, or still "degraded"
 *  after all instances recover) for as long as no execution event happens to refetch it. */
export function appLiveStatus(
  appStatuses: Record<string, AppStatusEntry>,
  row: Pick<AppRow, "app_key" | "status"> & { instances?: AppRow["instances"] },
): string {
  const instances = row.instances ?? [];
  if (instances.length <= 1) {
    return appStatuses[appStatusKey(row.app_key, 0)]?.status ?? row.status;
  }
  const liveStatuses = instances.map(
    (inst) => appStatuses[appStatusKey(row.app_key, inst.index)]?.status ?? inst.status,
  );
  if (liveStatuses.includes("running") && liveStatuses.includes("failed")) return "degraded";
  return liveStatuses.reduce((worst, live) => (statusPriority(live) < statusPriority(worst) ? live : worst));
}

export function compareAppRows(
  a: AppRow,
  b: AppRow,
  sort: AppSortState,
  appStatuses: Record<string, AppStatusEntry>,
): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  const aStatus = appLiveStatus(appStatuses, a);
  const bStatus = appLiveStatus(appStatuses, b);
  switch (sort.key) {
    case "name":
      return dir * a.display_name.localeCompare(b.display_name) || a.app_key.localeCompare(b.app_key);
    case "status": {
      const statusDiff = statusPriority(aStatus) - statusPriority(bStatus);
      if (statusDiff !== 0) return dir * statusDiff;
      return a.app_key.localeCompare(b.app_key);
    }
    case "error":
      return dir * ((a.error_message ? 0 : 1) - (b.error_message ? 0 : 1));
    case "runs": {
      const aRuns = a.total_invocations + a.total_executions;
      const bRuns = b.total_invocations + b.total_executions;
      return dir * (aRuns - bRuns);
    }
    case "last":
      return dir * ((a.last_activity_ts ?? 0) - (b.last_activity_ts ?? 0));
    default:
      return 0;
  }
}
