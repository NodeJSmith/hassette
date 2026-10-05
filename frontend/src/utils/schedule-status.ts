/**
 * Source of truth for schedule_status/schedule_status_reason display text, for every
 * combination that has static text. The one exception is "scheduled" with no reason: its text
 * depends on whether live next_run timing is available, which only the caller knows — see the
 * fallback in `scheduleStatusDisplay()`'s docstring and in `job-detail.tsx`'s
 * `scheduleStatusText`.
 */
import type { components } from "../api/generated-types";

type ScheduleStatus = components["schemas"]["ScheduleStatus"];
type ScheduleStatusReason = components["schemas"]["ScheduleStatusReason"];

export interface ScheduleStatusDisplay {
  /** Short list-view label. */
  label: string;
  /** Full sentence for the job detail view. */
  text: string;
}

/** status -> display info, when no reason-specific override below applies. No "scheduled"
 * entry: that status has no default text, only the "legacy_unknown" override below. */
const COMPLETED_DISPLAY: ScheduleStatusDisplay = { label: "completed", text: "Schedule completed." };

const SCHEDULE_STATUS_DISPLAY: Partial<Record<ScheduleStatus, ScheduleStatusDisplay>> = {
  manual: { label: "manual", text: "Manual only." },
  waiting: { label: "waiting", text: "Waiting for entity time." },
  completed: COMPLETED_DISPLAY,
};

/** (status, reason) -> display info, overriding the status-level default above. */
const SCHEDULE_STATUS_REASON_DISPLAY: Partial<
  Record<ScheduleStatus, Partial<Record<ScheduleStatusReason, ScheduleStatusDisplay>>>
> = {
  completed: {
    // Same label as the default "completed" entry — only the detail-view text differs for
    // this reason, so it's derived by spreading rather than duplicating the label string.
    trigger_error: { ...COMPLETED_DISPLAY, text: "Schedule stopped after trigger error." },
  },
  scheduled: {
    legacy_unknown: { label: "unknown", text: "Legacy status unknown." },
  },
};

/**
 * Looks up display info for a schedule_status/schedule_status_reason pair.
 *
 * Returns null for "scheduled" without a `legacy_unknown` reason — that combination has no
 * static text because it depends on whether live next_run timing is available, which callers
 * must resolve themselves (see `job-detail.tsx`'s `scheduleStatusText`).
 */
export function scheduleStatusDisplay(
  status: ScheduleStatus | null,
  reason?: ScheduleStatusReason | null,
): ScheduleStatusDisplay | null {
  if (status === null) return null;
  if (reason) {
    const override = SCHEDULE_STATUS_REASON_DISPLAY[status]?.[reason];
    if (override) return override;
  }
  return SCHEDULE_STATUS_DISPLAY[status] ?? null;
}
