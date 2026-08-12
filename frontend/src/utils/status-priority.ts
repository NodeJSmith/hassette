/**
 * Canonical status priority ordering. Lower number = more severe / worse.
 * Used for both worst-of-children resolution (sidebar) and table column sorting.
 *
 * This replaces two previously divergent maps. The table sort previously grouped
 * stopping/shutting_down with blocked (tier 1); they now sort between running (4)
 * and stopped (6), which is more semantically correct for transitional statuses.
 */
export const STATUS_PRIORITY: Readonly<Record<string, number>> = {
  failed: 0,
  crashed: 0,
  exhausted_dead: 0,
  blocked: 1,
  degraded: 2,
  exhausted_cooling: 3,
  starting: 4,
  running: 5,
  stopping: 6,
  shutting_down: 6,
  stopped: 7,
  disabled: 8,
  not_started: 9,
};

const UNKNOWN_PRIORITY = 99;

export function statusPriority(status: string): number {
  return STATUS_PRIORITY[status] ?? UNKNOWN_PRIORITY;
}
