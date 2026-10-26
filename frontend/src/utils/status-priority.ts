import type { AppStatus, ResourceStatus } from "../api/endpoints";

type StatusPriorityKey = ResourceStatus | AppStatus | "shutting_down";

/**
 * Canonical status priority ordering. Lower number = more severe / worse.
 * Used for both worst-of-children resolution (sidebar) and table column sorting.
 *
 * This replaces two previously divergent maps. The table sort previously grouped
 * stopping/shutting_down with blocked (tier 1); they now sort between running
 * and stopped, which is more semantically correct for transitional statuses.
 */
export const STATUS_PRIORITY: Readonly<Record<StatusPriorityKey, number>> = {
  failed: 0,
  crashed: 0,
  blocked: 1,
  degraded: 2,
  starting: 4,
  running: 5,
  stopping: 6,
  shutting_down: 6,
  stopped: 7,
  disabled: 8,
  not_started: 9,
} satisfies Record<StatusPriorityKey, number>;

export function statusPriority(status: StatusPriorityKey): number {
  return STATUS_PRIORITY[status] ?? 99;
}
