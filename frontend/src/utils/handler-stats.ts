import type { JobData, ListenerData } from "../api/endpoints";

export interface HandlerStats {
  totalInvocations: number;
  totalExecutions: number;
  totalFailed: number;
  totalTimedOut: number;
  totalCancelled: number;
  /** Weighted mean of avg_duration_ms across all listeners/jobs with at least one run, or null when none have run. */
  totalAvgDurationMs: number | null;
}

export function computeHandlerStats(listeners: ListenerData[], jobs: JobData[]): HandlerStats {
  let durationWeightedSum = 0;
  let durationRunTotal = 0;

  for (const l of listeners) {
    if (l.total_invocations > 0) {
      durationWeightedSum += l.avg_duration_ms * l.total_invocations;
      durationRunTotal += l.total_invocations;
    }
  }
  for (const j of jobs) {
    if (j.total_executions > 0) {
      durationWeightedSum += j.avg_duration_ms * j.total_executions;
      durationRunTotal += j.total_executions;
    }
  }

  return {
    totalInvocations: listeners.reduce((s, l) => s + l.total_invocations, 0),
    totalExecutions: jobs.reduce((s, j) => s + j.total_executions, 0),
    totalFailed: listeners.reduce((s, l) => s + l.failed, 0) + jobs.reduce((s, j) => s + j.failed, 0),
    totalTimedOut: listeners.reduce((s, l) => s + l.timed_out, 0) + jobs.reduce((s, j) => s + j.timed_out, 0),
    totalCancelled: listeners.reduce((s, l) => s + l.cancelled, 0) + jobs.reduce((s, j) => s + j.cancelled, 0),
    totalAvgDurationMs: durationRunTotal > 0 ? durationWeightedSum / durationRunTotal : null,
  };
}
