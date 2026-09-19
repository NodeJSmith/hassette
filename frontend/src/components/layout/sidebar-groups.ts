import type { components } from "../../api/generated-types";
import type { AppStatusEntry } from "../../state/store";
import { appLiveStatus } from "../../utils/app-data";

type AppManifest = components["schemas"]["AppManifestResponse"];
type ManifestStatus = components["schemas"]["ManifestStatus"];
type ResourceStatus = components["schemas"]["ResourceStatus"];

export type GroupKey = "err" | "blocked" | "warn" | "ok" | "stopped" | "disabled";

export const HEALTHY_GROUP_KEY: GroupKey = "ok";

export interface GroupDef {
  key: GroupKey;
  label: string;
  tone: "err" | "warn" | "ok" | "mute";
  defaultOpen: boolean;
  /** Whether apps in this group are excluded from the `allHealthy` tally.
   *  `true` for "ok" (genuinely healthy) and "disabled" (inert — neither healthy nor unhealthy). */
  healthy: boolean;
}

export const GROUP_DEFS: GroupDef[] = [
  { key: "err", label: "FAILING", tone: "err", defaultOpen: true, healthy: false },
  { key: "blocked", label: "BLOCKED", tone: "err", defaultOpen: true, healthy: false },
  { key: "warn", label: "SLOW", tone: "warn", defaultOpen: true, healthy: false },
  { key: HEALTHY_GROUP_KEY, label: "RUNNING", tone: "ok", defaultOpen: false, healthy: true },
  { key: "stopped", label: "STOPPED", tone: "mute", defaultOpen: true, healthy: false },
  { key: "disabled", label: "DISABLED", tone: "mute", defaultOpen: false, healthy: true },
];

/** Legacy frontend-only status value not present in either backend enum — see
 *  `ShuttingDownStatus` in `utils/status.ts` for the full rationale. */
type StatusGroupKey = ManifestStatus | ResourceStatus | "shutting_down";

const STATUS_TO_GROUP = {
  failed: "err",
  crashed: "err",
  exhausted_dead: "err",
  blocked: "blocked",
  exhausted_cooling: "warn",
  stopping: "warn",
  shutting_down: "warn",
  degraded: "warn",
  stopped: "stopped",
  not_started: "stopped",
  running: HEALTHY_GROUP_KEY,
  starting: HEALTHY_GROUP_KEY,
  disabled: "disabled",
} satisfies Record<StatusGroupKey, GroupKey>;

/** Derived from GROUP_DEFS so allHealthy stays in sync if a group is added or reclassified. */
const UNHEALTHY_KEYS: ReadonlySet<GroupKey> = new Set(GROUP_DEFS.filter((def) => !def.healthy).map((def) => def.key));

export interface GroupedApps {
  groups: Map<GroupKey, AppManifest[]>;
  allHealthy: boolean;
}

export function groupAndSortApps(manifests: AppManifest[], appStatuses: Record<string, AppStatusEntry>): GroupedApps {
  const groups = new Map<GroupKey, AppManifest[]>(GROUP_DEFS.map((def) => [def.key, []]));
  for (const manifest of manifests) {
    const key = getGroupKey(manifest, appStatuses);
    groups.get(key)!.push(manifest);
  }
  for (const [, apps] of groups) {
    apps.sort((a, b) => a.display_name.localeCompare(b.display_name));
  }
  const allHealthy = [...UNHEALTHY_KEYS].every((key) => (groups.get(key)?.length ?? 0) === 0);
  return { groups, allHealthy };
}

/** Display names that appear on 2+ manifests — these need a disambiguating label instead
 * of the bare (colliding) display_name. Computed against the full manifest list so a given
 * app's label doesn't flip based on unrelated search-filtering state. */
export function findDuplicateDisplayNames(manifests: AppManifest[]): Set<string> {
  const counts = new Map<string, number>();
  for (const m of manifests) {
    counts.set(m.display_name, (counts.get(m.display_name) ?? 0) + 1);
  }
  return new Set([...counts.entries()].filter(([, count]) => count > 1).map(([name]) => name));
}

/** Groups from the live WS-overlaid status, not manifest.status — see appLiveStatus. */
export function getGroupKey(manifest: AppManifest, appStatuses: Record<string, AppStatusEntry>): GroupKey {
  const status = appLiveStatus(appStatuses, manifest);
  // Fallback: any status not in the map (e.g. a new backend enum value before types are
  // regenerated) defaults to the healthy group, matching the old if-chain's implicit default.
  return STATUS_TO_GROUP[status] ?? HEALTHY_GROUP_KEY;
}
