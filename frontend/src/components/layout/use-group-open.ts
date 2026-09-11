import { useState } from "react";

import { GROUP_DEFS, type GroupKey, HEALTHY_GROUP_KEY } from "./sidebar-groups";

const DEFAULT_GROUP_OPEN: Record<GroupKey, boolean> = Object.fromEntries(
  GROUP_DEFS.map((def) => [def.key, def.defaultOpen]),
) as Record<GroupKey, boolean>;

export function useGroupOpen(allHealthy: boolean) {
  const [groupOpen, setGroupOpen] = useState<Record<GroupKey, boolean>>(DEFAULT_GROUP_OPEN);

  function isOpen(key: GroupKey): boolean {
    if (key === HEALTHY_GROUP_KEY && allHealthy) return true;
    return groupOpen[key];
  }

  function toggle(key: GroupKey) {
    setGroupOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return { isOpen, toggle };
}
