import type { components } from "../../api/generated-types";
import { statusPriority } from "../../utils/status-priority";

type AppManifest = components["schemas"]["AppManifestResponse"];

export type GroupKey = "err" | "blocked" | "warn" | "ok" | "stopped" | "disabled";

export interface GroupDef {
  key: GroupKey;
  label: string;
  tone: "err" | "warn" | "ok" | "mute";
  defaultOpen: boolean;
}

export const GROUP_DEFS: GroupDef[] = [
  { key: "err", label: "FAILING", tone: "err", defaultOpen: true },
  { key: "blocked", label: "BLOCKED", tone: "err", defaultOpen: true },
  { key: "warn", label: "SLOW", tone: "warn", defaultOpen: true },
  { key: "ok", label: "RUNNING", tone: "ok", defaultOpen: false },
  { key: "stopped", label: "STOPPED", tone: "mute", defaultOpen: true },
  { key: "disabled", label: "DISABLED", tone: "mute", defaultOpen: false },
];

const WARN_STATUSES = new Set(["exhausted_cooling", "stopping", "shutting_down"]);

export function worstStatus(manifest: AppManifest): string {
  const instances = manifest.instances ?? [];
  if (instances.length === 0) return manifest.status;
  return instances.reduce<string>((worst, inst) => {
    return statusPriority(inst.status) < statusPriority(worst) ? inst.status : worst;
  }, manifest.status);
}

export interface GroupedApps {
  groups: Map<GroupKey, AppManifest[]>;
  allHealthy: boolean;
}

export function groupAndSortApps(manifests: AppManifest[]): GroupedApps {
  const groups = new Map<GroupKey, AppManifest[]>(GROUP_DEFS.map((g) => [g.key, []]));
  for (const m of manifests) {
    const key = getGroupKey(m);
    groups.get(key)!.push(m);
  }
  for (const [, apps] of groups) {
    apps.sort((a, b) => a.display_name.localeCompare(b.display_name));
  }
  const allHealthy =
    (groups.get("err")?.length ?? 0) === 0 &&
    (groups.get("blocked")?.length ?? 0) === 0 &&
    (groups.get("warn")?.length ?? 0) === 0 &&
    (groups.get("stopped")?.length ?? 0) === 0;
  return { groups, allHealthy };
}

export function getGroupKey(manifest: AppManifest): GroupKey {
  const status = manifest.instance_count > 1 ? worstStatus(manifest) : manifest.status;

  if (status === "blocked") return "blocked";
  if (status === "disabled") return "disabled";
  if (status === "failed" || status === "crashed" || status === "exhausted_dead") return "err";
  if (WARN_STATUSES.has(status)) return "warn";
  if (status === "stopped" || status === "not_started") return "stopped";
  // "running", "starting", and any unknown status map to the healthy group
  return "ok";
}
