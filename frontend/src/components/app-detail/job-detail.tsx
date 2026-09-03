import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

import type { JobData } from "../../api/endpoints";
import { getJobExecutions, triggerJob } from "../../api/endpoints";
import { useAsyncAction } from "../../hooks/use-async-action";
import { useQueryInvalidator } from "../../hooks/use-query-invalidator";
import { useRelativeTime } from "../../hooks/use-relative-time";
import { isExecutionDefined, useJobExecution } from "../../hooks/use-scoped-execution";
import { useScopedQuery } from "../../hooks/use-scoped-query";
import { queryKeys } from "../../lib/query-keys";
import { DETAIL_FETCH_LIMIT } from "../../utils/constants";
import { formatTriggerDetail } from "../../utils/format";
import { scheduleStatusDisplay } from "../../utils/schedule-status";
import { handlerKindLabel } from "../../utils/status";
import type { DetailStatsCell } from "../shared/detail-stats";
import { DetailStats } from "../shared/detail-stats";
import { ErrorBanner } from "../shared/error-banner";
import { IconPlay } from "../shared/icons";
import { Spinner } from "../shared/spinner";
import { type Chip, ChipsRow } from "./chips-row";
import { DetailHeader } from "./detail-header";
import { ExecutionSection } from "./execution-section";
import { HandlerDetailLayout } from "./handler-detail-layout";
import { jobHealthKind } from "./handler-list";
import { RegistrationFooter } from "./registration-footer";
import { buildCommonStatCells, type CommonStatInput } from "./stat-cell-builders";

/** Max time to wait for an execution record after Run Now submission before showing the timeout fallback. */
const RUN_NOW_FEEDBACK_TIMEOUT_MS = 8000;

function ScheduleChips({ job }: { job: JobData }) {
  const chips: Chip[] = [];
  if (job.jitter) chips.push({ label: `±${job.jitter}s jitter` });
  if (job.group) chips.push({ label: `group: ${job.group}` });

  return <ChipsRow mode={job.mode} variant="job" testId="schedule-chips" chips={chips} />;
}

interface RunNowFeedback {
  /** Arm the watcher before submitting, so a completion event racing the POST isn't missed. */
  startWatching: () => void;
  /** Disarm the watcher without a toast — call when the submission itself fails. */
  cancelWatching: () => void;
}

/** Suppressed/dropped invocations never emit an execution event, so a timeout fallback toast is the only signal for them. */
function useRunNowFeedback(jobId: number): RunNowFeedback {
  const execution = useJobExecution(jobId);
  const watchingRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!watchingRef.current) return;
    if (execution === undefined) return;
    watchingRef.current = false;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    toast.success("Execution recorded");
  }, [execution]);

  useEffect(
    () => () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    },
    [],
  );

  const startWatching = () => {
    watchingRef.current = true;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      if (!watchingRef.current) return;
      watchingRef.current = false;
      toast.error("No execution recorded");
    }, RUN_NOW_FEEDBACK_TIMEOUT_MS);
  };

  const cancelWatching = () => {
    watchingRef.current = false;
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  return { startWatching, cancelWatching };
}

function RunNowButton({ jobId }: { jobId: number }) {
  const { loading, error, run } = useAsyncAction();
  const { startWatching, cancelWatching } = useRunNowFeedback(jobId);

  return (
    <div className="flex flex-col items-start gap-1">
      <Button
        variant="default"
        size="sm"
        data-testid="run-now-btn"
        disabled={loading}
        onClick={() =>
          void run(async () => {
            startWatching();
            try {
              await triggerJob(jobId);
            } catch (err) {
              cancelWatching();
              throw err;
            }
          })
        }
      >
        {loading ? (
          <>
            <Spinner /> Running…
          </>
        ) : (
          <>
            <IconPlay /> Run Now
          </>
        )}
      </Button>
      {error && (
        <p className="text-sm text-destructive" role="alert" data-testid="run-now-error">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Status-specific text for a job's `schedule_status`, per design/specs/090 Operator Surfaces.
 * Returns null for a normally-scheduled job with live timing — `nextRunText` already conveys
 * that state, so the caller falls back to it.
 */
function scheduleStatusText(job: JobData, nextRunText: string | null): string | null {
  const display = scheduleStatusDisplay(job.schedule_status, job.schedule_status_reason);
  if (display) return display.text;
  if (job.schedule_status === "scheduled") return nextRunText === null ? "Timing unavailable." : null;
  return null;
}

function resolveLastCell(
  statusText: string | null,
  nextRunText: string | null,
  lastExecutedLabel: string,
): { label: string; fieldLabel: string } {
  if (statusText) return { label: statusText, fieldLabel: "Schedule" };
  if (nextRunText) return { label: nextRunText, fieldLabel: "Next" };
  return { label: lastExecutedLabel || "—", fieldLabel: "Last" };
}

function buildJobStatsCells(job: JobData, lastExecutedLabel: string, nextRunText: string | null): DetailStatsCell[] {
  const statusText = scheduleStatusText(job, nextRunText);
  const lastCell = resolveLastCell(statusText, nextRunText, lastExecutedLabel);
  const input: CommonStatInput = {
    totalLabel: "Runs",
    total: job.total_executions,
    failed: job.failed,
    avgDurationMs: job.avg_duration_ms,
    lastLabel: lastCell.label,
    lastFieldLabel: lastCell.fieldLabel,
    timedOut: job.timed_out,
    cancelled: job.cancelled,
    threadLeaked: job.thread_leaked,
    suppressedCount: job.suppressed_count,
    droppedCount: job.dropped_count,
    extraCell: job.skipped > 0 ? { label: "Skipped", value: job.skipped, tone: "mute" } : undefined,
  };
  return buildCommonStatCells(input);
}

interface Props {
  job: JobData;
  appKey: string;
  instanceQs?: string;
  onSwitchToCode?: (line?: number) => void;
}

export function JobDetail({ job, appKey, instanceQs, onSwitchToCode }: Props) {
  const { data: executions, isPending: loading } = useScopedQuery(
    queryKeys.jobExecutions(job.job_id),
    (since, signal) => getJobExecutions(job.job_id, DETAIL_FETCH_LIMIT, since, signal),
  );

  const execution = useJobExecution(job.job_id);
  const lastExecutedLabel = useRelativeTime(job.last_executed_at);
  const nextRunLabel = useRelativeTime(job.next_run ?? null);
  const fireAtLabel = useRelativeTime(job.fire_at ?? null);

  useQueryInvalidator(execution, isExecutionDefined, queryKeys.jobExecutions(job.job_id));

  const kindLabel = handlerKindLabel("job", null, job.trigger_type);
  const jobKind = jobHealthKind(job);
  const testId = `job-detail-${job.job_id}`;
  const predicateDescription = job.human_description || job.predicate_description || null;

  let nextRunText: string | null = null;
  if (job.next_run) nextRunText = `next ${nextRunLabel}`;
  else if (job.fire_at) nextRunText = `fire at ${fireAtLabel}`;

  return (
    <HandlerDetailLayout testId={testId}>
      <DetailHeader
        name={job.job_name}
        kindLabel={kindLabel}
        statusKind={jobKind}
        kind="job"
        subtitle={
          [job.trigger_label, job.trigger_detail ? formatTriggerDetail(job.trigger_detail) : null]
            .filter(Boolean)
            .join(" ") || null
        }
        headerActions={<RunNowButton jobId={job.job_id} />}
      />

      {predicateDescription && (
        <p
          className="mb-3 flex flex-wrap items-center gap-2 text-sm text-muted-foreground"
          data-testid="job-predicate-description"
        >
          {predicateDescription}
        </p>
      )}

      <ScheduleChips job={job} />

      {jobKind === "err" && (job.last_error_message || job.last_error_type) && (
        <ErrorBanner
          errorType={job.last_error_type ?? null}
          errorMessage={job.last_error_message ?? null}
          traceback={job.last_error_traceback ?? null}
          data-testid="job-error-banner"
        />
      )}

      <DetailStats cells={buildJobStatsCells(job, lastExecutedLabel, nextRunText)} data-testid="job-stats-row" />

      <ExecutionSection
        heading="executions"
        records={executions}
        kind="job"
        tableId={`execution-table-${job.job_id}`}
        loading={loading}
        appKey={appKey}
        handlerKind="job"
        handlerId={job.job_id}
        instanceQs={instanceQs}
      />

      <RegistrationFooter
        kind="job"
        testId={testId}
        sourceLocation={job.source_location}
        registrationSource={job.registration_source}
        onViewCode={onSwitchToCode}
      />
    </HandlerDetailLayout>
  );
}
