import { useState } from "react";

import { GROUP_DEFS, type GroupKey, HEALTHY_GROUP_KEY } from "./sidebar-groups";

const DEFAULT_GROUP_OPEN: Record<GroupKey, boolean> = Object.fromEntries(
  GROUP_DEFS.map((def) => [def.key, def.defaultOpen]),
) as Record<GroupKey, boolean>;

/** RUNNING defaults open while nothing needs attention; an explicit toggle always wins over that default. */
export function useGroupOpen(allHealthy: boolean) {
  const [userOpen, setUserOpen] = useState<Partial<Record<GroupKey, boolean>>>({});

  function isOpen(key: GroupKey): boolean {
    const toggled = userOpen[key];
    if (toggled !== undefined) return toggled;
    if (key === HEALTHY_GROUP_KEY && allHealthy) return true;
    return DEFAULT_GROUP_OPEN[key];
  }

  function toggle(key: GroupKey) {
    const next = !isOpen(key);
    setUserOpen((prev) => ({ ...prev, [key]: next }));
  }

  return { isOpen, toggle };
}
