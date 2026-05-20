import { useState } from "preact/hooks";
import { GROUP_DEFS, type GroupKey } from "./sidebar-groups";

const DEFAULT_GROUP_OPEN: Record<GroupKey, boolean> = Object.fromEntries(
  GROUP_DEFS.map((g) => [g.key, g.defaultOpen]),
) as Record<GroupKey, boolean>;

export function useGroupOpen(allHealthy: boolean) {
  const [groupOpen, setGroupOpen] = useState<Record<GroupKey, boolean>>(DEFAULT_GROUP_OPEN);

  function isOpen(key: GroupKey): boolean {
    if (key === "ok" && allHealthy) return true;
    return groupOpen[key];
  }

  function toggle(key: GroupKey) {
    setGroupOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return { isOpen, toggle };
}
