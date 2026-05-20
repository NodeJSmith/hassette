/**
 * Canonical status priority ordering. Lower number = more severe / worse.
 * Used for both worst-of-children resolution (sidebar) and table column sorting.
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
