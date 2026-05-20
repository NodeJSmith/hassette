import type { AppManifest, DashboardAppGridEntry } from "../api/endpoints";
import type { SortState } from "../components/shared/sort-header";
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
  instance_count: number;
  instances: AppManifest["instances"];
  error_message: string | null;
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

export function mergeManifestsAndGrid(
  manifests: AppManifest[],
  gridEntries: DashboardAppGridEntry[],
): AppRow[] {
  const gridMap = new Map(gridEntries.map((e) => [e.app_key, e]));
  return manifests.map((m) => {
    const g = gridMap.get(m.app_key);
    return {
      app_key: m.app_key,
      class_name: m.class_name,
      display_name: m.display_name,
      filename: m.filename,
      status: m.status,
      block_reason: m.block_reason ?? null,
      enabled: m.enabled,
      auto_loaded: m.auto_loaded,
      instance_count: m.instance_count,
      instances: m.instances,
      error_message: g?.last_error_message ?? m.error_message ?? null,
      last_error_message: g?.last_error_message ?? null,
      last_error_type: g?.last_error_type ?? null,
      last_error_ts: g?.last_error_ts ?? null,
      handler_count: g?.handler_count ?? 0,
      job_count: g?.job_count ?? 0,
      total_invocations: g?.total_invocations ?? 0,
      total_executions: g?.total_executions ?? 0,
      total_errors: g?.total_errors ?? 0,
      total_timed_out: g?.total_timed_out ?? 0,
      total_job_errors: g?.total_job_errors ?? 0,
      total_job_timed_out: g?.total_job_timed_out ?? 0,
      error_rate: g?.error_rate ?? 0,
      last_activity_ts: g?.last_activity_ts ?? null,
      activity_buckets: g?.activity_buckets ?? [],
    };
  });
}

export type AppSortKey = "name" | "status" | "error" | "runs" | "last";
export type AppSortState = SortState<AppSortKey>;


export function compareAppRows(
  a: AppRow,
  b: AppRow,
  sort: AppSortState,
  liveStatuses: Record<string, { status: string } | undefined>,
): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  const aStatus = liveStatuses[a.app_key]?.status ?? a.status;
  const bStatus = liveStatuses[b.app_key]?.status ?? b.status;
  switch (sort.key) {
    case "name":
      return dir * a.app_key.localeCompare(b.app_key);
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
