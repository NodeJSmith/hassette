import { statusPriority } from "../../utils/status-priority";
import type { components } from "../../api/generated-types";

type AppManifest = components["schemas"]["AppManifestResponse"];

export type GroupKey = "err" | "blocked" | "warn" | "ok" | "stopped" | "disabled";

export interface GroupDef {
  key: GroupKey;
  label: string;
  tone: "err" | "warn" | "ok" | "mute";
  defaultOpen: boolean;
}

export const GROUP_DEFS: GroupDef[] = [
  { key: "err",      label: "FAILING",  tone: "err",  defaultOpen: true  },
  { key: "blocked",  label: "BLOCKED",  tone: "err",  defaultOpen: true  },
  { key: "warn",     label: "SLOW",     tone: "warn", defaultOpen: true  },
  { key: "ok",       label: "RUNNING",  tone: "ok",   defaultOpen: false },
  { key: "stopped",  label: "STOPPED",  tone: "mute", defaultOpen: true  },
  { key: "disabled", label: "DISABLED", tone: "mute", defaultOpen: false },
];

const WARN_STATUSES = new Set(["exhausted_cooling", "stopping", "shutting_down"]);

export function worstStatus(manifest: AppManifest): string {
  const instances = manifest.instances ?? [];
  if (instances.length === 0) return manifest.status;
  return instances.reduce((worst, inst) => {
    return statusPriority(inst.status) < statusPriority(worst) ? inst.status : worst;
  }, manifest.status);
}

function isMultiInstance(m: AppManifest): boolean {
  return m.instance_count > 1;
}

export function getGroupKey(manifest: AppManifest): GroupKey {
  const status = isMultiInstance(manifest) ? worstStatus(manifest) : manifest.status;

  if (status === "blocked") return "blocked";
  if (status === "disabled") return "disabled";
  if (status === "failed" || status === "crashed" || status === "exhausted_dead") return "err";
  if (WARN_STATUSES.has(status)) return "warn";
  if (status === "stopped" || status === "not_started") return "stopped";
  return "ok";
}
