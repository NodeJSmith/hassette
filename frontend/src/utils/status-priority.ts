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
  exhausted_cooling: 2,
  starting: 3,
  running: 4,
  stopping: 5,
  shutting_down: 5,
  stopped: 6,
  disabled: 7,
  not_started: 8,
};

const UNKNOWN_PRIORITY = 99;

export function statusPriority(status: string): number {
  return STATUS_PRIORITY[status] ?? UNKNOWN_PRIORITY;
}
