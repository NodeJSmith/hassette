import type {
  AppActivity,
  AppGridEntry,
  AppGridResponse,
  AppManifest,
  AppStatus,
  NeedsRestart,
  ResourceStatus,
} from "@/api/endpoints";
import { type AppStatusEntry, appStatusKey, type LiveAppStatus } from "@/state/store";
import type { SortState } from "@/utils/sort";

import { statusPriority } from "./status-priority";

/** `AppActivity` parts the server computes only for a request with a `since`; `null` otherwise.
 *  Mirrors `WINDOWED_ACTIVITY_PARTS` in `hassette_wire.telemetry`. */
const WINDOWED_ACTIVITY_PARTS: ReadonlySet<keyof AppActivity> = new Set(["activity_buckets", "last_error"]);
/** Every `AppActivity` part; a `Record` over the type's keys, so adding a part is a compile error here. */
const ACTIVITY_PART_KEYS: Record<keyof AppActivity, true> = {
  stats: true,
  activity_buckets: true,
  last_error: true,
  blocking_event_count: true,
};
// `Object.keys` returns `string[]`; this guard narrows it back to the part names without a cast.
const isActivityPart = (key: string): key is keyof AppActivity =>
  Object.prototype.hasOwnProperty.call(ACTIVITY_PART_KEYS, key);
const ACTIVITY_PARTS = Object.keys(ACTIVITY_PART_KEYS).filter(isActivityPart);

/** `AppSummary` fields `toAppRow` overrides: normalized (optional on the wire, always present on a row) or dropped. */
type OverriddenAppFields = "block_reason" | "instances" | "error_message" | "error_traceback";

/** An app's summary fields side by side with its activity parts. Plain-copied fields track the
 *  generated types; only the normalized ones are spelled out. The activity parts are `null` when
 *  the server couldn't compute them: the part's query failed, or (`activity_buckets`,
 *  `last_error`) it only runs for a window and this was an all-time request. Render a null part
 *  as "—", never as a zero or a healthy value. `last_error` `null`: the lookup didn't run or
 *  failed. `{ error: null }`: it ran and found no error. */
export type AppRow = Omit<AppManifest, OverriddenAppFields> &
  AppActivity & {
    block_reason: string | null;
    instances: NonNullable<AppManifest["instances"]>;
    error_message: string | null;
  };

/**
 * Flatten an app grid entry (`{app, activity}`) into an `AppRow`: the app's fields side by side
 * with its activity parts, defaulting the app's optional fields (instances, error fields) to
 * their empty/null equivalents. The grid endpoint is the sole data source — this is flattening,
 * not a merge of two sources.
 */
export function toAppRow({ app, activity }: AppGridEntry): AppRow {
  // The grid never renders a traceback, so the row drops it.
  const { error_traceback: _traceback, ...fields } = app;
  return {
    ...fields,
    block_reason: app.block_reason ?? null,
    instances: app.instances ?? [],
    error_message: app.error_message ?? null,
    ...activity,
  };
}

/** Sums `pick` over every row, or `null` when any row's value is `null`: a total that skipped
 *  uncomputed rows would read as a smaller real number. */
export function sumOrNull(rows: readonly AppRow[], pick: (row: AppRow) => number | null): number | null {
  let total = 0;
  for (const row of rows) {
    const value = pick(row);
    if (value === null) return null;
    total += value;
  }
  return total;
}

/** True when some row is missing a part the request asked for, i.e. an enrichment failed. A windowed
 *  part is only asked for when the response's `since` echo is set; without one, its `null` means
 *  "not computed", not a failure. */
export function hasFailedActivityPart(grid: AppGridResponse | undefined): boolean {
  if (!grid) return false;
  // The response's `since` echo, not the page's own preset: it states what the server computed.
  const windowed = grid.since !== null && grid.since !== undefined;
  const requested = ACTIVITY_PARTS.filter((part) => windowed || !WINDOWED_ACTIVITY_PARTS.has(part));
  return grid.apps.some(({ activity }) => requested.some((part) => activity[part] === null));
}

/** Handler invocations plus job executions, or `null` when the row's stats weren't computed. */
export function totalRuns(row: Pick<AppRow, "stats">): number | null {
  return row.stats ? row.stats.total_invocations + row.stats.total_executions : null;
}

export type AppSortKey = "name" | "status" | "error" | "runs" | "last";
export type AppSortState = SortState<AppSortKey>;

/** The snapshot fields a live delta is compared against: the app key and the revision the row was read at. */
type StatusRow = Pick<AppRow, "app_key" | "status_revision">;

/** The apply rule for every `app_status_changed` delta: it wins only when strictly newer than the snapshot row, so a
 *  tie goes to the row. Writes that send no delta (blocking, config changes, registration) bump the revision too and
 *  reach the row through the `apps_changed` refetch, so they come out right with no special case. */
function isNewer(entry: { status_revision: number } | undefined, row: StatusRow): boolean {
  return entry !== undefined && entry.status_revision > row.status_revision;
}

/** The instance's stored delta when it applies over `row`, else `undefined`. */
function liveInstanceEntry(live: LiveAppStatus, row: StatusRow, instanceName: string): AppStatusEntry | undefined {
  const entry = live.instances[appStatusKey(row.app_key, instanceName)];
  return isNewer(entry, row) ? entry : undefined;
}

/** The app's status: the server rollup from the newest delta when it applies over `row`, else the row's own. */
export function appLiveStatus(live: LiveAppStatus, row: StatusRow & Pick<AppRow, "status">): AppStatus {
  const entry = live.apps[row.app_key];
  return entry !== undefined && isNewer(entry, row) ? entry.app_status : row.status;
}

/** One instance's status: its delta's when it applies over `row`, else the snapshot instance's own. */
export function instanceLiveStatus(
  live: LiveAppStatus,
  row: StatusRow,
  inst: { instance_name: string; status: ResourceStatus },
): ResourceStatus {
  return liveInstanceEntry(live, row, inst.instance_name)?.status ?? inst.status;
}

/** One instance's error message. An applying delta's `exception` is authoritative, including `null`
 *  (the instance recovered). */
export function instanceLiveError(
  live: LiveAppStatus,
  row: StatusRow,
  inst: { instance_name: string; error_message?: string | null },
): string | null | undefined {
  const entry = liveInstanceEntry(live, row, inst.instance_name);
  return entry ? entry.exception : inst.error_message;
}

/** One instance's needs-restart flag: an applying delta's, else the snapshot instance's. A newer delta with no flag
 *  does clear a cached one: revisions order the two, so the delta is the later write. */
export function instanceLiveNeedsRestart(
  live: LiveAppStatus,
  row: StatusRow,
  inst: { instance_name: string; needs_restart?: NeedsRestart | null },
): NeedsRestart | null {
  const entry = liveInstanceEntry(live, row, inst.instance_name);
  return entry ? (entry.needs_restart ?? null) : (inst.needs_restart ?? null);
}

/** An app's needs-restart summary for its row: how many instances are flagged, and the flag itself when
 *  exactly one is, so the row can show that instance's reason. Counts only the row's own instances. */
export function appNeedsRestart(
  live: LiveAppStatus,
  row: StatusRow & Pick<AppRow, "instances">,
): { count: number; flag: NeedsRestart | null } {
  const flags = row.instances.flatMap((inst) => {
    const flag = instanceLiveNeedsRestart(live, row, inst);
    return flag ? [flag] : [];
  });
  return { count: flags.length, flag: flags.length === 1 ? flags[0] : null };
}

function hasError(row: AppRow): boolean {
  return Boolean(row.error_message);
}

export function compareAppRows(a: AppRow, b: AppRow, sort: AppSortState, live: LiveAppStatus): number {
  const direction = sort.dir === "asc" ? 1 : -1;
  const aStatus = appLiveStatus(live, a);
  const bStatus = appLiveStatus(live, b);
  switch (sort.key) {
    case "name":
      return direction * a.display_name.localeCompare(b.display_name) || a.app_key.localeCompare(b.app_key);
    case "status": {
      const statusDiff = statusPriority(aStatus) - statusPriority(bStatus);
      if (statusDiff !== 0) return direction * statusDiff;
      return a.app_key.localeCompare(b.app_key);
    }
    case "error":
      return direction * ((hasError(a) ? 0 : 1) - (hasError(b) ? 0 : 1));
    case "runs":
      return compareNullsLast(totalRuns(a), totalRuns(b), direction);
    case "last":
      return compareNullsLast(lastActivitySortValue(a), lastActivitySortValue(b), direction);
    default:
      return 0;
  }
}

/** `null` (sorted last) when the row's stats weren't computed. An app whose stats were computed but
 *  that never ran has no `last_activity_ts`, and sorts as the oldest possible activity (0). */
function lastActivitySortValue(row: AppRow): number | null {
  return row.stats ? (row.stats.health.last_activity_ts ?? 0) : null;
}

/** Orders two values by `direction`, with `null` (an uncomputed part) last in either direction. */
function compareNullsLast(a: number | null, b: number | null, direction: number): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return direction * (a - b);
}
