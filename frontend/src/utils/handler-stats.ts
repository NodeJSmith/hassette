import type { JobData, ListenerData } from "../api/endpoints";

export interface HandlerStats {
  totalInvocations: number;
  totalExecutions: number;
  totalFailed: number;
  totalTimedOut: number;
}

export function computeHandlerStats(listeners: ListenerData[], jobs: JobData[]): HandlerStats {
  return {
    totalInvocations: listeners.reduce((s, l) => s + l.total_invocations, 0),
    totalExecutions: jobs.reduce((s, j) => s + j.total_executions, 0),
    totalFailed: listeners.reduce((s, l) => s + l.failed, 0) + jobs.reduce((s, j) => s + j.failed, 0),
    totalTimedOut: listeners.reduce((s, l) => s + l.timed_out, 0) + jobs.reduce((s, j) => s + j.timed_out, 0),
  };
}
