import type {
  AppActivity,
  AppGridEntry,
  AppGridResponse,
  AppManifest,
  AppStatus,
  ResourceStatus,
} from "../api/endpoints";
import type { SortState } from "../components/shared/sort-header";
import { type AppStatusEntry, appStatusKey } from "../state/store";
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

/** "disabled" and "blocked" are manifest-level configuration states, not derived from instance
 *  activity, so they must override any live or synthetic per-instance status a caller uses to
 *  decide what to render or which actions to allow — a leftover per-instance WS status, or a
 *  not-yet-tracked configured index's synthetic "stopped" placeholder (see
 *  AppRegistry.build_manifest_info() on the backend), would otherwise mask the app-level
 *  config state. Single source of truth for this rule — `appLiveStatus` and the per-instance
 *  action-button gating in `AppTableRow`/`AppDetailHeader` all call this instead of
 *  reimplementing the `"disabled" | "blocked"` check inline. */
export function configStatusOverride(status: AppStatus | ResourceStatus): "disabled" | "blocked" | undefined {
  return status === "disabled" || status === "blocked" ? status : undefined;
}

/** Resolve the live status for an app row's parent view.
 *  Single-instance: WS status for index 0.
 *  Multi-instance: overlays live per-instance WS statuses (falling back to the snapshot's
 *  per-instance status where no WS update has arrived yet) and derives "degraded" from that
 *  live view whenever a "running" and a "failed" instance coexist — mirroring `AppRegistry`'s
 *  own binary model server-side (an instance entry is either running or failed, nothing else),
 *  though the live WS status of an individual instance can transiently be a finer-grained
 *  value (e.g. "starting") that this check doesn't treat as "running". This must be computed
 *  from live data, not read off the cached `row.status`: the app-grid query is
 *  invalidated on execution events, not `app_status_changed`, so a cached `row.status` can be
 *  stale in either direction (still "running" after an instance fails, or still "degraded"
 *  after all instances recover) for as long as no execution event happens to refetch it.
 *
 *  The index set is also live, not just the statuses: a hot reload that adds an instance
 *  delivers a WS update for the new index before any execution event refetches the grid, so
 *  the cached `row.instances` list can be missing an index entirely. Server-side, instance
 *  indices are always assigned contiguously from 0 (`enumerate(app_configs)` in
 *  `AppFactory.create_instances`), so a reload only ever extends the range upward — probing
 *  forward from the highest cached index with direct key lookups finds any new indices without
 *  scanning the whole (cross-app) `appStatuses` record or prefix-matching app_key by hand.
 *
 *  Config states win over any live status — see `configStatusOverride`. */
export function appLiveStatus(
  appStatuses: Record<string, AppStatusEntry>,
  row: Pick<AppRow, "app_key" | "status"> & { instances?: AppRow["instances"] },
): AppStatus | ResourceStatus {
  const override = configStatusOverride(row.status);
  if (override) return override;
  const instances = row.instances ?? [];
  const knownIndices = new Set(instances.map((inst) => inst.index));
  const maxKnownIndex = knownIndices.size > 0 ? Math.max(...knownIndices) : -1;
  for (let index = maxKnownIndex + 1; appStatuses[appStatusKey(row.app_key, index)]; index++) {
    knownIndices.add(index);
  }
  // Fast path for the common case (0 or 1 known indices) — skips the two-way includes() check
  // and the per-index instances.find() scan below, both of which only matter once there's more
  // than one index to reduce over.
  if (knownIndices.size <= 1) {
    const index = knownIndices.size === 1 ? [...knownIndices][0] : 0;
    return appStatuses[appStatusKey(row.app_key, index)]?.status ?? row.status;
  }
  const liveStatuses = [...knownIndices].map(
    (index) =>
      appStatuses[appStatusKey(row.app_key, index)]?.status ??
      instances.find((inst) => inst.index === index)?.status ??
      row.status,
  );
  if (liveStatuses.includes("running") && liveStatuses.includes("failed")) return "degraded";
  return liveStatuses.reduce((worst, live) => (statusPriority(live) < statusPriority(worst) ? live : worst));
}

/** Resolve the live status for a single instance row: the WS status for that exact index,
 *  falling back to the cached instance's own status. Unlike `appLiveStatus`, this is a plain
 *  single-key overlay, not a rollup — no degraded derivation, no forward index-probing, since
 *  a per-instance row only ever represents the one index it's given, not the whole app. */
export function instanceLiveStatus(
  appStatuses: Record<string, AppStatusEntry>,
  appKey: string,
  inst: { index: number; status: ResourceStatus },
): ResourceStatus {
  return appStatuses[appStatusKey(appKey, inst.index)]?.status ?? inst.status;
}

/** Resolve the live error message for a single instance row. Once a WS `app_status_changed`
 *  event has been seen for this index, its `exception` field is authoritative — including
 *  `null`, which means the instance recovered and the cached manifest's `error_message` (from
 *  before the config reload that produced this row) must not keep showing. Only fall back to
 *  the cached value when no live status has been observed for this index yet. */
export function instanceLiveError(
  appStatuses: Record<string, AppStatusEntry>,
  appKey: string,
  inst: { index: number; error_message?: string | null },
): string | null | undefined {
  const entry = appStatuses[appStatusKey(appKey, inst.index)];
  return entry ? entry.exception : inst.error_message;
}

function hasError(row: AppRow): boolean {
  return Boolean(row.error_message);
}

export function compareAppRows(
  a: AppRow,
  b: AppRow,
  sort: AppSortState,
  appStatuses: Record<string, AppStatusEntry>,
): number {
  const direction = sort.dir === "asc" ? 1 : -1;
  const aStatus = appLiveStatus(appStatuses, a);
  const bStatus = appLiveStatus(appStatuses, b);
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
