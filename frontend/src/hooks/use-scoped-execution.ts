import type { WsExecutionCompletedPayload } from "../api/ws-types";
import { useAppStore } from "../state/store";

/**
 * Pick the first execution completion matching `match` out of the latest fleet-wide WS batch.
 *
 * Selecting the matching record rather than the whole `executionCompleted` batch is what keeps a
 * component off the fleet-wide render path: a batch carrying only other apps' executions selects
 * to `undefined`, which is `Object.is`-equal to the previous `undefined`, so the store never
 * notifies. The record itself is a fresh object per batch, so consecutive matching completions do
 * each register as a change.
 *
 * One case still costs a render: the batch immediately after a matching completion selects back to
 * `undefined`, which is *not* `Object.is`-equal to the previous matched record, so one extra render
 * fires even if that next batch is unrelated. Bounded to exactly one render per matching
 * completion — steady-state unrelated activity stays undefined-to-undefined.
 *
 * Callers pair the result with `useQueryInvalidator(execution, isExecutionDefined, key)`: the
 * scoping already happened in the selector, so the filter only checks definedness.
 */
function useScopedExecution(
  match: (event: WsExecutionCompletedPayload) => boolean,
): WsExecutionCompletedPayload | undefined {
  return useAppStore((s) => s.executionCompleted?.find(match));
}

/** Shared `useQueryInvalidator` filter for the scoped-execution hooks below — see their docstrings. */
export function isExecutionDefined(execution: WsExecutionCompletedPayload | undefined): boolean {
  return execution !== undefined;
}

/** This app's first completion in the latest batch, optionally narrowed to one completion kind. */
export function useAppExecution(appKey: string, kind?: "handler" | "job"): WsExecutionCompletedPayload | undefined {
  return useScopedExecution((e) => e.app_key === appKey && (kind === undefined || e.kind === kind));
}

/** This job's first completion in the latest batch. */
export function useJobExecution(jobId: number): WsExecutionCompletedPayload | undefined {
  return useScopedExecution((e) => e.kind === "job" && e.job_id === jobId);
}

/** This listener's first completion in the latest batch. */
export function useListenerExecution(listenerId: number): WsExecutionCompletedPayload | undefined {
  return useScopedExecution((e) => e.kind === "handler" && e.listener_id === listenerId);
}
